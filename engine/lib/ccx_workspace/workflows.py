"""Durable provider-neutral workflows; model output never grants authority.

Approval entry points belong to the authenticated operator API, not ScopedTools.
A completed task requires engine-observed tests and independent review of the
same filesystem snapshot. Unknown in-flight outcomes require human recovery.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import re
import math
import ccx_platform as native
from .store import allowed, file_path
import subprocess
import threading
import time
import uuid

def provider_identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value) is not None
DEFAULT_BUDGETS = {'max_tasks': 24, 'max_depth': 4, 'max_retries': 2,
                   'max_concurrency': 1, 'max_tokens': 50000, 'max_seconds': 1800,
                   'max_cost': 0.0, 'call_timeout': 180, 'max_tool_calls': 32,
                   'max_output_tokens': 4096}
TERMINAL = {'COMPLETED', 'CANCELLED', 'FAILED'}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def _load(value, default=None):
    return json.loads(value) if value else default


def _id():
    return str(uuid.uuid4())


def _decode_object(text):
    text = text.strip()
    if text.startswith('```') and text.endswith('```'):
        text = '\n'.join(text.splitlines()[1:-1])
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('Provider must return a JSON object')
    return value


def snapshot(project, exclusions=()):
    """Fingerprint actual project files, including untracked nonignored content.

    Git projects respect .gitignore; tracked ignored files remain included. For
    non-Git projects only engine metadata and known dependency caches are omitted.
    Links are hashed as links, never followed outside the project.
    """
    root = Path(project).resolve(strict=True)
    result = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
    if result.returncode != 0:
        raise ValueError('Snapshot requires the registered Git project')
    names = sorted(set(os.fsdecode(p) for p in result.stdout.split(b'\0') if p))
    if len(names) > 50000:
        raise ValueError('Snapshot exceeds bounded file count')
    records, total = [], 0
    for name in names:
        if not allowed(name, exclusions):
            continue
        path = file_path(root, name)
        if native.is_link(path):
            raise PermissionError('Snapshot refuses links/reparse points')
        if path.is_file():
            info = path.stat()
            if info.st_size > 4 * 1024 * 1024 or info.st_nlink != 1:
                raise ValueError('Snapshot file exceeds bounded single-link policy')
            total += info.st_size
            if total > 128 * 1024 * 1024:
                raise ValueError('Snapshot exceeds bounded byte budget')
            with path.open('rb') as stream:
                data = stream.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('Snapshot file grew beyond byte budget')
            records.append((name, 'file', hashlib.sha256(data).hexdigest(), info.st_mode & 0o111))
        elif not path.exists():
            records.append((name, 'deleted'))
    return {'hash': _hash(records), 'files': records}


class WorkflowEngine:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS w5_workflows (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, objective TEXT NOT NULL,
                    criteria TEXT NOT NULL, providers TEXT NOT NULL, budgets TEXT NOT NULL,
                    status TEXT NOT NULL, reason TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    started_at REAL, tokens_used INTEGER NOT NULL DEFAULT 0, cost_used REAL NOT NULL DEFAULT 0,
                    lease_owner TEXT, lease_until REAL, revision INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS w5_tasks (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, parent_id TEXT, title TEXT NOT NULL,
                    description TEXT NOT NULL, executor TEXT NOT NULL, reviewer TEXT NOT NULL,
                    status TEXT NOT NULL, depth INTEGER NOT NULL, delegation_depth INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0,
                    evidence TEXT NOT NULL DEFAULT '{}', error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS w5_actions (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, task_id TEXT, role TEXT NOT NULL,
                    provider TEXT NOT NULL, state TEXT NOT NULL, request TEXT NOT NULL,
                    response TEXT, before_hash TEXT NOT NULL, after_hash TEXT, consumed INTEGER NOT NULL DEFAULT 0,
                    started_at REAL NOT NULL, finished_at REAL);
                CREATE TABLE IF NOT EXISTS w5_approvals (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, kind TEXT NOT NULL,
                    scope TEXT NOT NULL, scope_hash TEXT NOT NULL, actor TEXT NOT NULL,
                    created_at REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS w5_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL,
                    task_id TEXT, action_id TEXT, event TEXT NOT NULL, data TEXT NOT NULL, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS w5_sessions (
                    workflow_id TEXT NOT NULL, task_id TEXT NOT NULL, provider TEXT NOT NULL,
                    role TEXT NOT NULL, session_id TEXT, history TEXT NOT NULL DEFAULT '[]',
                    PRIMARY KEY(workflow_id,task_id,provider,role));
                CREATE INDEX IF NOT EXISTS w5_tasks_workflow ON w5_tasks(workflow_id,created_at);
                CREATE INDEX IF NOT EXISTS w5_actions_workflow ON w5_actions(workflow_id,state);
            ''')
            if 'consumed' not in {r['name'] for r in db.execute('PRAGMA table_info(w5_actions)')}:
                db.execute('ALTER TABLE w5_actions ADD COLUMN consumed INTEGER NOT NULL DEFAULT 0')

    def _snapshot(self, workflow):
        project = self.store.project(workflow['project_id'])
        return snapshot(project['path'], exclusions=_load(project.get('exclusions'), []))

    def _checkpoint(self, db, workflow_id, event, data=None, task_id=None, action_id=None):
        db.execute('INSERT INTO w5_checkpoints(workflow_id,task_id,action_id,event,data,created_at) VALUES(?,?,?,?,?,?)',
                   (workflow_id, task_id, action_id, event, _json(data or {}), time.time()))

    def create(self, project_id, objective, criteria, providers=None, budgets=None):
        self.store.project(project_id)
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError('Objective is required')
        if not isinstance(criteria, list) or not criteria or not all(isinstance(c, str) and c.strip() for c in criteria):
            raise ValueError('Explicit nonempty acceptance criteria are required')
        roles = {'planner': 'claude', 'executor': 'codex', 'reviewer': 'claude'}
        roles.update(providers or {})
        if set(roles) != {'planner', 'executor', 'reviewer'} or any(not provider_identifier(v) for v in roles.values()):
            raise ValueError('Unknown provider role')
        limits = dict(DEFAULT_BUDGETS)
        if budgets and set(budgets) - set(limits):
            raise ValueError('Unknown budget')
        limits.update(budgets or {})
        for key, value in limits.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError('Budgets must be nonnegative numbers')
            if key not in ('max_cost',) and (not isinstance(value, int) or (value == 0 and key not in ('max_depth', 'max_retries'))):
                raise ValueError('Count/time budgets must be positive integers')
        if limits['max_depth'] > 8 or limits['max_retries'] > 5 or limits['max_tasks'] > 1000 or limits['max_concurrency'] > 16 or limits['max_output_tokens'] > 32768 or limits['call_timeout'] > 3600:
            raise ValueError('Budget exceeds engine safety maximum')
        identifier, now = _id(), time.time()
        with self.store.connect() as db:
            db.execute('INSERT INTO w5_workflows(id,project_id,objective,criteria,providers,budgets,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier, project_id, objective.strip(), _json(criteria), _json(roles), _json(limits), 'READY', now, now))
            self._checkpoint(db, identifier, 'WORKFLOW_CREATED', {'criteria': criteria, 'providers': roles, 'budgets': limits})
        return self.status(identifier)

    def _workflow(self, db, workflow_id):
        row = db.execute('SELECT * FROM w5_workflows WHERE id=?', (workflow_id,)).fetchone()
        if not row:
            raise KeyError('Unknown workflow')
        value = dict(row)
        for key in ('criteria', 'providers', 'budgets'):
            value[key] = _load(value[key])
        return value

    def _task(self, db, task_id):
        row = db.execute('SELECT * FROM w5_tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise KeyError('Unknown task')
        value = dict(row)
        value['evidence'] = _load(value['evidence'], {})
        return value

    def _new_task(self, db, workflow, title, description='', parent_id=None, executor=None, reviewer=None):
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Task title required')
        count = db.execute('SELECT COUNT(*) FROM w5_tasks WHERE workflow_id=?', (workflow['id'],)).fetchone()[0]
        if count >= workflow['budgets']['max_tasks']:
            raise ValueError('Task budget exhausted')
        depth = 0
        if parent_id:
            parent = self._task(db, parent_id)
            if parent['workflow_id'] != workflow['id']:
                raise ValueError('Parent task belongs to another workflow')
            depth = parent['depth'] + 1
        if depth > workflow['budgets']['max_depth']:
            raise ValueError('Task depth budget exhausted')
        executor = executor or workflow['providers']['executor']
        reviewer = reviewer or workflow['providers']['reviewer']
        if not provider_identifier(executor) or not provider_identifier(reviewer):
            raise ValueError('Execution requires valid executor and reviewer identifiers')
        identifier, now = _id(), time.time()
        db.execute('INSERT INTO w5_tasks(id,workflow_id,parent_id,title,description,executor,reviewer,status,depth,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                   (identifier, workflow['id'], parent_id, title.strip(), str(description), executor, reviewer, 'PENDING', depth, now, now))
        self._checkpoint(db, workflow['id'], 'TASK_CREATED', {'title': title, 'executor': executor, 'reviewer': reviewer}, identifier)
        return self._task(db, identifier)

    def create_task(self, workflow_id, title, description='', parent_id=None, executor=None, reviewer=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL or workflow['lease_until'] and workflow['lease_until'] > time.time():
                raise ValueError('Cannot alter a running or terminal workflow plan')
            return self._new_task(db, workflow, title, description, parent_id, executor, reviewer)

    def delegate(self, task_id, to_provider, from_provider=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            workflow = self._workflow(db, task['workflow_id'])
            source = from_provider or task['executor']
            if source != task['executor'] or not provider_identifier(to_provider) or source == to_provider:
                raise ValueError('Delegation must name the current executor and a different known provider')
            if task['status'] not in ('PENDING', 'BLOCKED') or workflow['lease_until'] and workflow['lease_until'] > time.time():
                raise ValueError('Cannot delegate an active or verified task')
            if task['delegation_depth'] >= workflow['budgets']['max_depth']:
                raise ValueError('Delegation depth budget exhausted')
            db.execute("UPDATE w5_tasks SET executor=?,reviewer=?,status='PENDING',delegation_depth=delegation_depth+1,revision=revision+1,evidence='{}',updated_at=? WHERE id=?",
                       (to_provider, source, time.time(), task_id))
            self._checkpoint(db, task['workflow_id'], 'TASK_DELEGATED', {'from': source, 'to': to_provider}, task_id)
            return self._task(db, task_id)

    def failover(self, task_id, to_provider, actor='user'):
        if actor != 'user':
            raise PermissionError('Only the user may authorize a provider transition')
        with self.store.connect() as db:
            task = self._task(db, task_id)
        if not self._approved(task['workflow_id'], 'failover', task_id=task_id, to_provider=to_provider):
            raise PermissionError('Explicit failover approval required')
        if self.status(task['workflow_id'])['pending_actions']:
            raise PermissionError('Resolve unknown provider outcomes before failover')
        result = self.delegate(task_id, to_provider)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, task['workflow_id'])
            if not workflow['lease_until'] or workflow['lease_until'] <= time.time():
                db.execute("UPDATE w5_workflows SET status='READY',reason=?,updated_at=? WHERE id=?",
                    ('User-approved provider failover; destination approvals checked before dispatch', time.time(), task['workflow_id']))
        return result

    def approve(self, workflow_id, kind, scope, actor='user'):
        """Trusted operator endpoint. This method is deliberately not a model tool."""
        if actor != 'user':
            raise PermissionError('Only an authenticated user may grant approval')
        allowed = {'sharing', 'cost', 'native_agent_access', 'native_agent_write', 'command', 'recovery', 'failover', 'operations'}
        if kind not in allowed or not isinstance(scope, dict):
            raise ValueError('Invalid approval kind or scope')
        scope = dict(scope)
        if kind in {'sharing', 'cost', 'native_agent_access', 'native_agent_write'} and not provider_identifier(scope.get('provider')):
            raise ValueError('Approval must identify a provider')
        if kind == 'cost':
            if any(isinstance(scope.get(k), bool) or not isinstance(scope.get(k), (int, float)) or not math.isfinite(scope[k]) or scope[k] <= 0 for k in ('max_cost', 'max_call_cost')):
                raise ValueError('Cost approval requires positive max_cost and conservative max_call_cost reservations')
            if scope['max_call_cost'] > scope['max_cost']:
                raise ValueError('Per-call reservation exceeds cost approval')
        if kind == 'operations':
            operations = scope.get('operations')
            if not isinstance(operations, list) or not operations or set(operations) - {'patch'}:
                raise ValueError('Scoped-write approval must explicitly name patch')
        if kind == 'command':
            argv = scope.get('argv')
            if not scope.get('name') or not isinstance(argv, list) or not argv or not all(isinstance(x, str) and '\0' not in x for x in argv):
                raise ValueError('Command approval requires an exact named argv')
            relative = Path(scope.get('cwd', '.'))
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Test command must remain in the project')
            scope['cwd'] = relative.as_posix()
            scope['timeout'] = min(600, max(1, int(scope.get('timeout', 60))))
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            identifier = _id()
            db.execute('INSERT INTO w5_approvals(id,workflow_id,kind,scope,scope_hash,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                       (identifier, workflow_id, kind, _json(scope), _hash(scope), actor, time.time()))
            self._checkpoint(db, workflow_id, 'USER_APPROVAL', {'id': identifier, 'kind': kind, 'scope_hash': _hash(scope)})
        return {'id': identifier, 'kind': kind, 'scope': scope, 'actor': actor}

    def revoke(self, workflow_id, approval_id, actor='user'):
        if actor != 'user':
            raise PermissionError('Only an authenticated user may revoke approval')
        with self.store.connect() as db:
            db.execute('UPDATE w5_approvals SET revoked=1 WHERE id=? AND workflow_id=?', (approval_id, workflow_id))
            self._checkpoint(db, workflow_id, 'APPROVAL_REVOKED', {'id': approval_id})

    def approvals(self, workflow_id):
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            return [dict(row, scope=_load(row['scope'])) for row in db.execute('SELECT * FROM w5_approvals WHERE workflow_id=? ORDER BY created_at', (workflow_id,))]

    def _approved(self, workflow_id, kind, **match):
        return [a for a in self.approvals(workflow_id) if not a['revoked'] and a['kind'] == kind
                and all(a['scope'].get(k) == v for k, v in match.items())]

    def _set_status(self, workflow_id, status, reason=None, operator=False):
        with self.store.connect() as db:
            current = self._workflow(db, workflow_id)
            if current['status'] in TERMINAL or (current['status'] == 'PAUSED' and not operator):
                return self.status(workflow_id)
            db.execute('UPDATE w5_workflows SET status=?,reason=?,updated_at=?,revision=revision+1 WHERE id=?',
                       (status, reason, time.time(), workflow_id))
            self._checkpoint(db, workflow_id, 'WORKFLOW_' + status, {'reason': reason})
        return self.status(workflow_id)

    def pause(self, workflow_id):
        return self._set_status(workflow_id, 'PAUSED', 'Paused by user', operator=True)

    def cancel(self, workflow_id):
        return self._set_status(workflow_id, 'CANCELLED', 'Cancelled by user; completed evidence retained', operator=True)

    def resume(self, workflow_id):
        with self.store.connect() as db:
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL:
                raise ValueError('Terminal workflow cannot be resumed')
            if workflow['lease_until'] and workflow['lease_until'] > time.time():
                raise ValueError('Wait for the active worker to finish before resuming')
            uncertain = list(db.execute("SELECT * FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN')", (workflow_id,)))
        for action in uncertain:
            approvals = self._approved(workflow_id, 'recovery', action_id=action['id'])
            if not approvals:
                raise PermissionError('Unknown action outcome requires explicit user recovery approval')
            decision = approvals[-1]['scope'].get('decision')
            if decision not in ('retry', 'fail'):
                raise ValueError('Recovery decision must be retry or fail')
            with self.store.connect() as db:
                db.execute('UPDATE w5_actions SET state=?,finished_at=? WHERE id=?',
                           ('RETRY_AUTHORIZED' if decision == 'retry' else 'FAILED', time.time(), action['id']))
                if action['task_id']:
                    current_task = self._task(db, action['task_id'])
                    recovery_phase = 'TESTING' if action['role'].startswith('test:') and decision == 'retry' else 'PENDING'
                    recovery_evidence = _json(current_task['evidence']) if recovery_phase == 'TESTING' else '{}'
                    db.execute("UPDATE w5_actions SET consumed=1 WHERE workflow_id=? AND task_id=? AND state='COMPLETED'", (workflow_id, action['task_id']))
                    db.execute('UPDATE w5_tasks SET status=?,evidence=?,updated_at=? WHERE id=?',
                               (recovery_phase if decision == 'retry' else 'BLOCKED', recovery_evidence, time.time(), action['task_id']))
                self._checkpoint(db, workflow_id, 'RECOVERY_DECISION', {'decision': decision}, action['task_id'], action['id'])
        return self._set_status(workflow_id, 'READY', operator=True)

    def status(self, workflow_id):
        with self.store.connect() as db:
            workflow = self._workflow(db, workflow_id)
            workflow['tasks'] = [self._task(db, row['id']) for row in db.execute('SELECT id FROM w5_tasks WHERE workflow_id=? ORDER BY created_at,id', (workflow_id,))]
            workflow['pending_actions'] = [dict(row) for row in db.execute("SELECT id,task_id,role,provider,state,started_at FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN')", (workflow_id,))]
            workflow.pop('lease_owner', None)
            workflow['cost_accounting'] = 'conservative_call_reservations_or_larger_reported_cost; not an upstream billing cap'
            workflow['token_accounting'] = 'reported where available; otherwise explicitly estimated UTF-8 bytes/4'
            return workflow

    def list(self, project_id=None):
        with self.store.connect() as db:
            rows = db.execute('SELECT id FROM w5_workflows' + (' WHERE project_id=?' if project_id else '') + ' ORDER BY created_at DESC', (project_id,) if project_id else ())
            identifiers = [r['id'] for r in rows]
        return [self.status(identifier) for identifier in identifiers]

    def checkpoints(self, workflow_id):
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            return [dict(row, data=_load(row['data'])) for row in db.execute('SELECT * FROM w5_checkpoints WHERE workflow_id=? ORDER BY id', (workflow_id,))]

    def _budget(self, workflow):
        limits = workflow['budgets']
        if workflow['tokens_used'] >= limits['max_tokens']:
            return 'Token budget exhausted'
        if workflow['started_at'] and time.time() - workflow['started_at'] >= limits['max_seconds']:
            return 'Workflow time budget exhausted'
        if limits['max_cost'] > 0 and workflow['cost_used'] >= limits['max_cost']:
            return 'Workflow cost budget exhausted'
        return None

    def _gate(self, workflow, provider, role, registry):
        identifier = workflow['id']
        if not self._approved(identifier, 'sharing', provider=provider):
            return 'Sharing approval required for ' + provider
        if not getattr(registry, 'offline', False):
            capabilities = registry.get(provider).status().get('capabilities', {})
            cost = self._approved(identifier, 'cost', provider=provider)
            if not cost or workflow['budgets']['max_cost'] <= 0:
                return 'Billable-call approval and positive workflow cost budget required for ' + provider
            if capabilities.get('native_agent_authorization_required') and not self._approved(identifier, 'native_agent_access', provider=provider):
                return 'Native agent filesystem-access approval required for ' + provider
            if capabilities.get('native_tools') and role == 'executor' and not self._approved(identifier, 'native_agent_write', provider=provider):
                return 'Native agent workspace-write approval required for ' + provider
            reservation = cost[-1]['scope']['max_call_cost']
            with self.store.connect() as db:
                spent = sum(max(_load(row['request'], {}).get('cost_reservation', 0),
                                (_load(row['response'], {}).get('usage') or {}).get('cost', 0)) for row in db.execute(
                    'SELECT request,response FROM w5_actions WHERE workflow_id=? AND provider=?', (identifier, provider)))
            if workflow['cost_used'] + reservation > workflow['budgets']['max_cost'] or spent + reservation > cost[-1]['scope']['max_cost']:
                return 'Conservative cost reservation budget exhausted'
        return self._budget(workflow)

    def _session(self, workflow_id, task_id, provider, role):
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM w5_sessions WHERE workflow_id=? AND task_id=? AND provider=? AND role=?',
                             (workflow_id, task_id or '', provider, role)).fetchone()
            return dict(row) if row else {'session_id': None, 'history': '[]'}

    def _invoke(self, workflow, task, role, provider, registry, prompt, cancel_event):
        task_id = task['id'] if task else None
        gate = self._gate(workflow, provider, role, registry)
        if gate:
            self._set_status(workflow['id'], 'APPROVAL_REQUIRED' if 'approval' in gate.lower() else 'BUDGET_EXHAUSTED', gate)
            return None
        project = self.store.project(workflow['project_id'])['path']
        initial = self._snapshot(workflow)
        with self.store.connect() as db:
            cached = db.execute("SELECT * FROM w5_actions WHERE workflow_id=? AND task_id IS ? AND role=? AND provider=? AND state='COMPLETED' AND consumed=0 ORDER BY started_at DESC LIMIT 1",
                                (workflow['id'], task_id, role, provider)).fetchone()
        if cached:
            if cached['after_hash'] != initial['hash']:
                with self.store.connect() as db:
                    db.execute("UPDATE w5_actions SET state='UNCERTAIN' WHERE id=?", (cached['id'],))
                self._set_status(workflow['id'], 'RECOVERY_REQUIRED', 'Project changed after a durable action checkpoint')
                return None
            result = _load(cached['response'], {})
            result['_action_id'], result['_snapshot_hash'] = cached['id'], cached['after_hash']
            return result
        session = self._session(workflow['id'], task_id, provider, role)
        operations = ['list_directory', 'read_file', 'search', 'git_diff']
        if role == 'executor':
            if any('patch' in a['scope']['operations'] for a in self._approved(workflow['id'], 'operations')):
                operations.append('patch')
            if self._commands(workflow['id']):
                operations.append('run_command')
        for capability in ('native_agent_access', 'native_agent_write'):
            if (capability != 'native_agent_write' or role == 'executor') and self._approved(workflow['id'], capability, provider=provider):
                operations.append(capability)
        remaining = workflow['budgets']['max_tokens'] - workflow['tokens_used']
        if remaining < 128:
            self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Insufficient remaining context/token budget')
            return None
        query = task['title'] + ' ' + task['description'] if task else workflow['objective']
        context = self.store.context(workflow['project_id'], query, budget=min(2000, remaining // 2),
                                     critical=[workflow['objective']] + workflow['criteria'])
        prompt = dict(prompt, context={'content': context['content'], 'references': context['references'],
                                      'estimated_tokens': context['estimated_tokens'], 'id': context['id']})
        request = {'project': project, 'prompt': _json(prompt), 'role': role, 'session_id': session['session_id'],
                   'timeout': min(workflow['budgets']['call_timeout'], max(1, workflow['budgets']['max_seconds'] - int(time.time() - workflow['started_at']))),
                   'allowed_operations': operations, 'history': _load(session['history'], []),
                   'max_output_tokens': min(workflow['budgets']['max_output_tokens'], workflow['budgets']['max_tokens'] - workflow['tokens_used'])}
        estimate_input = max(1, (len(request['prompt'].encode('utf-8')) + len(_json(request['history']).encode('utf-8')) + 3) // 4)
        if estimate_input >= remaining:
            self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Prompt/transcript exceeds remaining estimated token budget')
            return None
        request['max_output_tokens'] = min(request['max_output_tokens'], remaining - estimate_input)
        reservation = 0 if getattr(registry, 'offline', False) else self._approved(workflow['id'], 'cost', provider=provider)[-1]['scope']['max_call_cost']
        journal_request = dict(request, cost_reservation=reservation)
        action_id = _id()
        with self.store.connect() as db:
            db.execute('INSERT INTO w5_actions(id,workflow_id,task_id,role,provider,state,request,before_hash,started_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (action_id, workflow['id'], task_id, role, provider, 'RUNNING', _json(journal_request), initial['hash'], time.time()))
            db.execute('UPDATE w5_workflows SET cost_used=cost_used+? WHERE id=?', (reservation, workflow['id']))
            self._checkpoint(db, workflow['id'], 'ACTION_STARTED', {'role': role, 'provider': provider}, task_id, action_id)
        request['cancel_event'] = cancel_event
        try:
            result = registry.invoke(provider, request)
            if not isinstance(result, dict):
                raise ValueError('Provider returned an invalid result')
            if session['session_id'] and result.get('session_id') and result['session_id'] != session['session_id']:
                raise ValueError('Provider changed the exact persistent session ID')
            if result.get('session_id'):
                with self.store.connect() as db:
                    collision = db.execute('SELECT 1 FROM w5_sessions WHERE provider=? AND session_id=? AND NOT(workflow_id=? AND task_id=? AND role=?) LIMIT 1',
                        (provider, result['session_id'], workflow['id'], task_id or '', role)).fetchone()
                if collision:
                    raise ValueError('Provider reused a session across isolated workflow/task roles')
            if role == 'reviewer' and task and task['executor'] == provider:
                executor_session = self._session(workflow['id'], task_id, provider, 'executor')['session_id']
                if not executor_session or not result.get('session_id') or executor_session == result['session_id']:
                    raise ValueError('Same-provider reviewer must use a different actual session from executor')
            final = self._snapshot(workflow)
            usage = result.get('usage') or {}
            measured = sum(max(0, int(usage.get(key, usage.get(alias, 0)))) for key, alias in
                           (('input_tokens', 'prompt_tokens'), ('output_tokens', 'completion_tokens')))
            estimated = estimate_input + max(1, (len(str(result.get('output', '')).encode('utf-8')) + 3) // 4)
            used = measured or estimated
            reported_cost = max(0.0, float(usage.get('cost', 0.0)))
            if not math.isfinite(reported_cost):
                raise ValueError('Invalid provider cost usage')
            cost = max(0.0, reported_cost - reservation)
            stored = {key: value for key, value in result.items() if key not in ('events',)}
            # Provider approval requests are ordinary output, never capability grants.
            stored['usage_accounting'] = 'reported' if measured else 'estimated_utf8_bytes_div4'
            stored['cost_accounting'] = 'reported_or_reserved_maximum' if reservation else 'offline_mock'
            stored['cost_reserved'] = reservation
            stored['tokens_accounted'] = used
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if result.get('session_id'):
                    collision = db.execute('SELECT 1 FROM w5_sessions WHERE provider=? AND session_id=? AND NOT(workflow_id=? AND task_id=? AND role=?) LIMIT 1',
                        (provider, result['session_id'], workflow['id'], task_id or '', role)).fetchone()
                    if collision:
                        raise ValueError('Concurrent provider session collision across isolated roles')
                db.execute('UPDATE w5_actions SET state=?,response=?,after_hash=?,finished_at=? WHERE id=?',
                           ('COMPLETED', _json(stored), final['hash'], time.time(), action_id))
                db.execute('UPDATE w5_workflows SET tokens_used=tokens_used+?,cost_used=cost_used+?,updated_at=? WHERE id=?',
                           (used, cost, time.time(), workflow['id']))
                if result.get('session_id'):
                    db.execute('INSERT OR REPLACE INTO w5_sessions(workflow_id,task_id,provider,role,session_id,history) VALUES(?,?,?,?,?,?)',
                               (workflow['id'], task_id or '', provider, role, result['session_id'], _json(result.get('history', request['history']))))
                self._checkpoint(db, workflow['id'], 'ACTION_COMPLETED', {'status': result.get('status'), 'before_hash': initial['hash'], 'after_hash': final['hash'], 'tokens': used, 'accounting': stored['usage_accounting']}, task_id, action_id)
            if role != 'executor' and initial['hash'] != final['hash']:
                self._set_status(workflow['id'], 'FAILED', 'Read-only provider modified the project')
                return None
            result['_action_id'] = action_id
            result['_snapshot_hash'] = final['hash']
            return result
        except Exception as error:
            with self.store.connect() as db:
                db.execute("UPDATE w5_actions SET state='UNCERTAIN',response=?,finished_at=? WHERE id=?",
                           (_json({'error': type(error).__name__, 'message': str(error)[:500]}), time.time(), action_id))
                self._checkpoint(db, workflow['id'], 'ACTION_OUTCOME_UNCERTAIN', {'error': type(error).__name__}, task_id, action_id)
            self._set_status(workflow['id'], 'RECOVERY_REQUIRED', 'Provider action outcome uncertain; explicit recovery approval required')
            return None

    def _commands(self, workflow_id):
        commands = {}
        for approval in self._approved(workflow_id, 'command'):
            commands[approval['scope']['name']] = approval['scope']
        return commands

    def _tools(self, project, operations, commands, exclusions=()):
        from .tools import ScopedTools
        return ScopedTools(project, allowed_operations=operations,
                           approved_commands=commands, exclusions=exclusions)

    def _tests(self, workflow, task):
        commands = self._commands(workflow['id'])
        if not commands:
            self._set_status(workflow['id'], 'APPROVAL_REQUIRED', 'At least one exact test command needs user approval')
            return None
        project = self.store.project(workflow['project_id'])['path']
        before = self._snapshot(workflow)
        results = []
        for name, spec in commands.items():
            # Command permissions are exact argv; provider claims never supply this evidence.
            approved_scope_hash = _hash(spec)
            remaining = max(1, workflow['budgets']['max_seconds'] - int(time.time() - workflow['started_at']))
            spec = dict(spec, timeout=min(spec['timeout'], workflow['budgets']['call_timeout'], remaining))
            tools = self._tools(project, ['run_command'], {name: spec},
                                exclusions=_load(self.store.project(workflow['project_id']).get('exclusions'), []))
            test_key = _hash(['test', workflow['id'], task['id'], task['attempts'], task['revision'], before['hash'], approved_scope_hash])
            result = self._execute_tool(workflow, task, 'engine', test_key,
                {'id': name, 'name': 'run_command', 'arguments': {'name': name}}, tools, role='test:' + name)
            results.append({'name': name, 'argv_hash': _hash(spec['argv']), 'exit_code': result.get('exit_code'),
                            'output': str(result.get('output', ''))[-12000:], 'truncated': bool(result.get('truncated')),
                            'action_id': result.get('_engine_action_id'), 'executed_at': result.get('_engine_executed_at'),
                            'replayed': bool(result.get('_engine_replayed')),
                            'project_changed': bool(result.get('_engine_project_changed'))})
        after = self._snapshot(workflow)
        record = {'source': 'engine', 'snapshot_hash': before['hash'], 'after_hash': after['hash'],
                  'commands': results, 'passed': all(r['exit_code'] == 0 and not r['project_changed'] for r in results) and before['hash'] == after['hash'], 'at': time.time()}
        with self.store.connect() as db:
            self._checkpoint(db, workflow['id'], 'TESTS_EXECUTED', record, task['id'])
        return record

    def _task_evidence(self, task_id, status, evidence, error=None, increment=False):
        with self.store.connect() as db:
            db.execute('UPDATE w5_tasks SET status=?,evidence=?,error=?,attempts=attempts+?,updated_at=? WHERE id=?',
                       (status, _json(evidence), error, 1 if increment else 0, time.time(), task_id))
            for stage in ('execution', 'review'):
                action_id = evidence.get(stage, {}).get('action_id')
                if action_id:
                    db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (action_id,))

    def _correction(self, workflow, task, evidence, reason):
        exhausted = task['attempts'] >= workflow['budgets']['max_retries']
        self._task_evidence(task['id'], 'BLOCKED' if exhausted else 'PENDING', evidence, reason, increment=not exhausted)
        with self.store.connect() as db:
            self._checkpoint(db, workflow['id'], 'CORRECTION_LIMIT' if exhausted else 'CORRECTION_REQUIRED', {'reason': reason}, task['id'])
        if exhausted:
            self._set_status(workflow['id'], 'BLOCKED', 'Correction budget exhausted: ' + task['title'])
        return not exhausted

    def _handle_tools(self, workflow, task, provider, role, result, registry, prompt, cancel_event):
        rounds = 0
        while result and result.get('status') == 'tool_calls':
            calls = result.get('tool_calls') or []
            rounds += len(calls)
            with self.store.connect() as db:
                used_tools = db.execute("SELECT COUNT(*) FROM w5_actions WHERE workflow_id=? AND role LIKE 'tool:%'", (workflow['id'],)).fetchone()[0]
            if used_tools + len(calls) > workflow['budgets']['max_tool_calls']:
                self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Workflow tool-call budget exhausted')
                return None
            if not calls or rounds > workflow['budgets']['max_tool_calls']:
                self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Tool-call budget exhausted')
                return None
            operations = ['list_directory', 'read_file', 'search', 'git_diff']
            if role == 'executor':
                if any('patch' in a['scope']['operations'] for a in self._approved(workflow['id'], 'operations')):
                    operations.append('patch')
                if self._commands(workflow['id']):
                    operations.append('run_command')
            commands = self._commands(workflow['id'])
            tools = self._tools(self.store.project(workflow['project_id'])['path'], operations, commands,
                                exclusions=_load(self.store.project(workflow['project_id']).get('exclusions'), []))
            session = self._session(workflow['id'], task['id'] if task else None, provider, role)
            history = _load(session['history'], [])
            message = result.get('message') or {'role': 'assistant', 'content': result.get('output') or None,
                'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': _json(c['arguments'])}} for c in calls]}
            if not history or history[-1] != message:
                history.append(message)
            for call in calls:
                if call['name'] not in operations:
                    value = {'error': 'Operation not authorized'}
                else:
                    value = self._execute_tool(workflow, task, provider, result['_action_id'], call, tools)
                history.append({'role': 'tool', 'tool_call_id': call['id'], 'content': _json(value)})
                with self.store.connect() as db:
                    self._checkpoint(db, workflow['id'], 'SCOPED_TOOL_EXECUTED', {'name': call['name'], 'result': value}, task['id'] if task else None, result['_action_id'])
            with self.store.connect() as db:
                db.execute('INSERT OR REPLACE INTO w5_sessions(workflow_id,task_id,provider,role,session_id,history) VALUES(?,?,?,?,?,?)',
                           (workflow['id'], task['id'] if task else '', provider, role, session.get('session_id'), _json(history)))
                db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (result['_action_id'],))
            workflow = self.status(workflow['id'])
            result = self._invoke(workflow, task, role, provider, registry, prompt, cancel_event)
        return result

    def _execute_tool(self, workflow, task, provider, parent_action, call, tools, role=None):
        identifier = _hash([parent_action, call['id']])
        project = self.store.project(workflow['project_id'])['path']
        with self.store.connect() as db:
            prior = db.execute('SELECT * FROM w5_actions WHERE id=?', (identifier,)).fetchone()
        if prior:
            if prior['state'] == 'COMPLETED':
                result = _load(prior['response'])
                result['_engine_replayed'] = True
                result['_engine_project_changed'] = prior['before_hash'] != prior['after_hash']
                return result
            if prior['state'] != 'RETRY_AUTHORIZED':
                raise RuntimeError('Tool outcome requires recovery approval')
        before = self._snapshot(workflow)['hash']
        with self.store.connect() as db:
            db.execute("INSERT INTO w5_actions(id,workflow_id,task_id,role,provider,state,request,before_hash,started_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state='RUNNING',response=NULL,after_hash=NULL,finished_at=NULL,started_at=excluded.started_at",
                       (identifier, workflow['id'], task['id'] if task else None, role or 'tool:' + call['name'], provider,
                        'RUNNING', _json(call), before, time.time()))
            self._checkpoint(db, workflow['id'], 'SCOPED_TOOL_STARTED', {'name': call['name']}, task['id'] if task else None, identifier)
        try:
            result = tools.execute(call['name'], call.get('arguments') or {})
        except Exception as error:
            with self.store.connect() as db:
                db.execute("UPDATE w5_actions SET state='UNCERTAIN',response=? WHERE id=?",
                           (_json({'error': type(error).__name__}), identifier))
            raise
        after = self._snapshot(workflow)['hash']
        result = dict(result, _engine_action_id=identifier, _engine_executed_at=time.time(),
                      _engine_project_changed=before != after)
        with self.store.connect() as db:
            db.execute("UPDATE w5_actions SET state='COMPLETED',response=?,after_hash=?,consumed=1,finished_at=? WHERE id=?",
                       (_json(result), after, time.time(), identifier))
        return result

    def run(self, workflow_id, registry):
        owner, stop, cancel_event = _id(), threading.Event(), threading.Event()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL or workflow['status'] in ('PAUSED', 'RECOVERY_REQUIRED', 'BLOCKED', 'BUDGET_EXHAUSTED'):
                return self.status(workflow_id)
            active_project = db.execute('SELECT id FROM w5_workflows WHERE project_id=? AND id!=? AND lease_until>?',
                                        (workflow['project_id'], workflow_id, time.time())).fetchone()
            if active_project or workflow['lease_until'] and workflow['lease_until'] > time.time():
                return dict(self.status(workflow_id), busy=True)
            uncertain = db.execute("SELECT id FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN') LIMIT 1", (workflow_id,)).fetchone()
            if uncertain:
                db.execute("UPDATE w5_workflows SET status='RECOVERY_REQUIRED',reason='Unfinished action requires recovery approval' WHERE id=?", (workflow_id,))
                return dict(workflow, status='RECOVERY_REQUIRED')
            db.execute("UPDATE w5_workflows SET status='RUNNING',reason=NULL,lease_owner=?,lease_until=?,started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
                       (owner, time.time()+60, time.time(), time.time(), workflow_id))
        def heartbeat():
            while not stop.wait(1):
                with self.store.connect() as db:
                    row = db.execute('SELECT status,lease_owner FROM w5_workflows WHERE id=?', (workflow_id,)).fetchone()
                    if not row or row['lease_owner'] != owner or row['status'] in ('PAUSED', 'CANCELLED'):
                        cancel_event.set()
                        return
                    db.execute('UPDATE w5_workflows SET lease_until=? WHERE id=? AND lease_owner=?', (time.time()+60, workflow_id, owner))
        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            workflow = self.status(workflow_id)
            if not workflow['tasks']:
                prompt = {'role': 'planner', 'objective': workflow['objective'], 'criteria': workflow['criteria'],
                          'instruction': 'Return JSON {"tasks":[{"title":"...","description":"..."}]}. No approvals or commands may be granted.',
                          'max_tasks': workflow['budgets']['max_tasks']}
                result = self._invoke(workflow, None, 'planner', workflow['providers']['planner'], registry, prompt, cancel_event)
                result = self._handle_tools(workflow, None, workflow['providers']['planner'], 'planner', result, registry, prompt, cancel_event)
                if not result:
                    return self.status(workflow_id)
                plan = _decode_object(result.get('output', ''))
                tasks = plan.get('tasks')
                if not isinstance(tasks, list) or not tasks or len(tasks) > workflow['budgets']['max_tasks']:
                    raise ValueError('Planner returned an invalid or oversized plan')
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for task in tasks:
                        self._new_task(db, workflow, task['title'], task.get('description', ''))
                    self._checkpoint(db, workflow_id, 'PLAN_ACCEPTED', {'tasks': len(tasks)})
                    db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (result['_action_id'],))
            while True:
                workflow = self.status(workflow_id)
                if workflow['status'] != 'RUNNING' or cancel_event.is_set():
                    break
                reason = self._budget(workflow)
                if reason:
                    self._set_status(workflow_id, 'BUDGET_EXHAUSTED', reason)
                    break
                unfinished = [t for t in workflow['tasks'] if t['status'] != 'VERIFIED']
                unfinished.sort(key=lambda t: (t['status'] not in ('PENDING', 'EXECUTING'), -t['depth'], t['created_at']))
                task = unfinished[0] if unfinished else None
                if task is None:
                    # Later tasks can invalidate earlier evidence; verify the full
                    # final tree against every task before declaring completion.
                    current = self._snapshot(workflow)['hash']
                    stale = [t for t in workflow['tasks'] if t['evidence'].get('review', {}).get('snapshot_hash') != current]
                    if stale:
                        for item in stale:
                            self._task_evidence(item['id'], 'TESTING', item['evidence'], 'Final tree changed after review')
                        continue
                    summary = {'workflow_id': workflow_id, 'snapshot_hash': current,
                               'criteria': workflow['criteria'], 'tasks': [
                                   {'id': t['id'], 'reviewer': t['reviewer'],
                                    'test_exit_codes': [c['exit_code'] for c in t['evidence']['tests']['commands']],
                                    'review_action': t['evidence']['review']['action_id']} for t in workflow['tasks']]}
                    memory = self.store.add_memory(workflow['project_id'], 'verification',
                        'Workflow verification ' + workflow_id, _json(summary), kind='verified',
                        source='workflow:' + workflow_id, source_hash=current, confidence=1.0, verified_at=time.time())
                    with self.store.connect() as db:
                        self._checkpoint(db, workflow_id, 'VERIFICATION_MEMORY_SAVED', {'memory_id': memory['id']})
                    self._set_status(workflow_id, 'COMPLETED')
                    break
                if task['status'] == 'BLOCKED':
                    self._set_status(workflow_id, 'BLOCKED', 'Task requires explicit failover or recovery: ' + task['title'])
                    break
                evidence = task['evidence']
                if task['status'] in ('PENDING', 'EXECUTING'):
                    self._task_evidence(task['id'], 'EXECUTING', evidence)
                    prompt = {'role': 'executor', 'objective': workflow['objective'], 'criteria': workflow['criteria'],
                              'task': {'title': task['title'], 'description': task['description']},
                              'previous_review': evidence.get('review'), 'test_failures': evidence.get('tests'),
                              'instruction': 'Implement within authorized scope. Never grant approvals or claim independent verification.'}
                    result = self._invoke(workflow, task, 'executor', task['executor'], registry, prompt, cancel_event)
                    result = self._handle_tools(workflow, task, task['executor'], 'executor', result, registry, prompt, cancel_event)
                    if not result:
                        break
                    if self.status(workflow_id)['status'] != 'RUNNING' or cancel_event.is_set():
                        break
                    if result.get('status') != 'completed':
                        evidence['execution'] = {'action_id': result['_action_id'], 'status': result.get('status')}
                        self._task_evidence(task['id'], 'BLOCKED', evidence, 'Provider did not complete execution')
                        self._set_status(workflow_id, 'BLOCKED', 'Provider failure; explicit failover or correction needed')
                        break
                    evidence['execution'] = {'action_id': result['_action_id'], 'snapshot_hash': result['_snapshot_hash'], 'provider': task['executor']}
                    self._task_evidence(task['id'], 'TESTING', evidence)
                    if any(t['id'] != task['id'] and t['status'] in ('PENDING', 'EXECUTING') for t in self.status(workflow_id)['tasks']):
                        continue
                workflow = self.status(workflow_id)
                if workflow['status'] != 'RUNNING' or cancel_event.is_set():
                    break
                reason = self._budget(workflow)
                if reason:
                    self._set_status(workflow_id, 'BUDGET_EXHAUSTED', reason)
                    break
                tests = self._tests(workflow, task)
                if tests is None:
                    break
                evidence['tests'] = tests
                if not tests['passed']:
                    if not self._correction(workflow, task, evidence, 'Trusted test command failed or modified source'):
                        break
                    continue
                if self.status(workflow_id)['status'] != 'RUNNING' or cancel_event.is_set():
                    break
                self._task_evidence(task['id'], 'REVIEWING', evidence)
                prompt = {'role': 'reviewer', 'objective': workflow['objective'], 'criteria': workflow['criteria'],
                          'task': {'title': task['title'], 'description': task['description']},
                          'snapshot_hash': tests['snapshot_hash'], 'test_evidence': tests,
                          'instruction': 'Independently inspect actual files/diff. Return JSON with decision approve or changes_requested, exact snapshot_hash, rationale, and criteria [{criterion,met,evidence}]. Do not modify files.'}
                result = self._invoke(self.status(workflow_id), task, 'reviewer', task['reviewer'], registry, prompt, cancel_event)
                result = self._handle_tools(self.status(workflow_id), task, task['reviewer'], 'reviewer', result, registry, prompt, cancel_event)
                if not result:
                    break
                if self.status(workflow_id)['status'] != 'RUNNING' or cancel_event.is_set():
                    break
                review = _decode_object(result.get('output', ''))
                review['provider'] = task['reviewer']
                review['action_id'] = result['_action_id']
                evidence['review'] = review
                criteria = {item.get('criterion'): item for item in review.get('criteria', []) if isinstance(item, dict)}
                accepted = (result.get('status') == 'completed' and review.get('decision') == 'approve'
                            and review.get('snapshot_hash') == tests['snapshot_hash'] == result['_snapshot_hash']
                            and all(criteria.get(c, {}).get('met') is True and isinstance(criteria[c].get('evidence'), str)
                                    and criteria[c]['evidence'].strip() for c in workflow['criteria']))
                if not accepted:
                    if not self._correction(workflow, task, evidence, 'Independent review did not approve the tested snapshot'):
                        break
                    continue
                self._task_evidence(task['id'], 'VERIFIED', evidence)
                with self.store.connect() as db:
                    self._checkpoint(db, workflow_id, 'TASK_VERIFIED', {'snapshot_hash': tests['snapshot_hash'], 'reviewer': task['reviewer']}, task['id'])
            return self.status(workflow_id)
        except Exception as error:
            status = 'RECOVERY_REQUIRED' if self.status(workflow_id)['pending_actions'] else 'BLOCKED'
            self._set_status(workflow_id, status, type(error).__name__ + ': ' + str(error)[:500])
            return self.status(workflow_id)
        finally:
            stop.set()
            thread.join(timeout=3)
            with self.store.connect() as db:
                db.execute('UPDATE w5_workflows SET lease_owner=NULL,lease_until=NULL WHERE id=? AND lease_owner=?', (workflow_id, owner))
