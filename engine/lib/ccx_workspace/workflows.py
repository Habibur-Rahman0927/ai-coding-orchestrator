"""Durable provider-neutral workflows; model output never grants authority.

Approval entry points belong to the authenticated operator API, not ScopedTools.
A completed task requires engine-observed tests and independent review of the
same filesystem snapshot. Unknown in-flight outcomes require human recovery.
"""
import hashlib
from contextlib import nullcontext
import json
import os
from pathlib import Path
import sqlite3
import re
import math
import ccx_platform as native
from .store import allowed, file_path, read_source, safe_text
from .security import sensitive_content
import subprocess
import threading
import time
import uuid

def provider_identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', value) is not None
DEFAULT_BUDGETS = {'max_tasks': 24, 'max_depth': 4, 'max_retries': 2,
                   'max_concurrency': 1, 'max_tokens': 50000, 'max_seconds': 1800,
                   'max_cost': 0.0, 'call_timeout': 180, 'max_tool_calls': 32,
                   'max_output_tokens': 4096, 'max_provider_calls': 64,
                   'max_context_tokens': 2000, 'max_continuations': 2,
                   'max_request_tokens': 32768, 'context_reserve_tokens': 128}
TERMINAL = {'COMPLETED', 'CANCELLED', 'FAILED'}


def classify_failure(result):
    """A category is a recovery hint, never proof that retrying has no effects."""
    known = {'authentication', 'usage_limit', 'network', 'context_limit', 'permission_denied',
             'timeout', 'cancelled', 'incomplete', 'invalid_response', 'configuration', 'provider_error', 'unknown'}
    category = result.get('error_kind') or result.get('error_category')
    if category in known:
        return category
    status = result.get('status')
    if status in ('timeout', 'cancelled', 'incomplete'):
        return status
    error = str(result.get('error') or '').lower()[:1000]
    for words, label in ((('401', 'authentication', 'not logged', 'invalid api key'), 'authentication'),
                         (('429', 'quota', 'usage limit', 'rate limit'), 'usage_limit'),
                         (('context length', 'context limit', 'too many tokens'), 'context_limit'),
                         (('permission denied', 'forbidden', '403'), 'permission_denied'),
                         (('network', 'connection', 'transport'), 'network')):
        if any(word in error for word in words):
            return label
    return 'unknown'


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

    Requires a registered Git root. Tracked files participate in verification even
    when ignored by Git; application exclusions still apply. Links and oversized
    or multiply-linked files are refused rather than followed.
    """
    original=Path(project).absolute()
    if any(native.is_link(p) for p in (original,)+tuple(original.parents)):
        raise PermissionError('Snapshot root contains a link/reparse point')
    root = original.resolve(strict=True)
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
            data=read_source(root,name,limit=4*1024*1024)
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
                CREATE TABLE IF NOT EXISTS w5_dependencies (
                    task_id TEXT NOT NULL, depends_on TEXT NOT NULL,
                    PRIMARY KEY(task_id,depends_on));
                CREATE TABLE IF NOT EXISTS w5_requests (
                    id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL, kind TEXT NOT NULL,
                    scope TEXT NOT NULL, reason TEXT NOT NULL, created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING');
            ''')
            if 'consumed' not in {r['name'] for r in db.execute('PRAGMA table_info(w5_actions)')}:
                db.execute('ALTER TABLE w5_actions ADD COLUMN consumed INTEGER NOT NULL DEFAULT 0')
            if 'context_mode' not in {r['name'] for r in db.execute('PRAGMA table_info(w5_workflows)')}:
                db.execute("ALTER TABLE w5_workflows ADD COLUMN context_mode TEXT NOT NULL DEFAULT 'retrieved'")
            for column,default in (('model_overrides','{}'),('execution_policy','standard')):
                if column not in {r['name'] for r in db.execute('PRAGMA table_info(w5_workflows)')}:
                    db.execute("ALTER TABLE w5_workflows ADD COLUMN "+column+" TEXT NOT NULL DEFAULT '"+default+"'")
            columns={r['name'] for r in db.execute('PRAGMA table_info(w5_workflows)')}
            for column in ('lease_pid','lease_start_ticks'):
                if column not in columns:
                    db.execute('ALTER TABLE w5_workflows ADD COLUMN '+column+' INTEGER')

    @staticmethod
    def _process_birth(pid):
        """Keep only a birth identifier, never a process command or environment."""
        info=native.process_info(pid)
        if info is None or info.get('state')=='Z': return None
        birth=info.get('start_ticks')
        if type(birth)!=int or birth<0: raise ValueError('Process birth identity unavailable')
        return birth

    def _reconcile_ownership(self, db, project_id=None):
        query='SELECT id,status,lease_pid,lease_start_ticks,lease_until FROM w5_workflows WHERE lease_owner IS NOT NULL'
        rows=list(db.execute(query+(' AND project_id=?' if project_id else ''),(project_id,) if project_id else ()))
        reconciled=[];now=time.time()
        for row in rows:
            known_dead=False;known_live=False
            if row['lease_pid'] is not None and row['lease_start_ticks'] is not None:
                try:
                    birth=self._process_birth(row['lease_pid'])
                    known_dead=birth is None or birth!=row['lease_start_ticks']
                    known_live=not known_dead
                except (OSError,ValueError,NotImplementedError):
                    pass
            # A live matching owner may be a separate CLI runner. Do not steal
            # it because a heartbeat was delayed or the dashboard restarted.
            if known_live or (not known_dead and row['lease_until'] and row['lease_until']>now):
                continue
            unknown=db.execute("SELECT 1 FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN') LIMIT 1",(row['id'],)).fetchone()
            state=row['status']
            if state not in TERMINAL:
                state='RECOVERY_REQUIRED' if unknown else 'PAUSED'
            db.execute("UPDATE w5_workflows SET lease_owner=NULL,lease_until=NULL,lease_pid=NULL,lease_start_ticks=NULL,status=?,reason=?,updated_at=? WHERE id=?",
                       (state,'Execution owner exited or could not be established after lease expiry; inspect persisted evidence before resuming',now,row['id']))
            if unknown:
                db.execute("UPDATE w5_actions SET state='UNCERTAIN' WHERE workflow_id=? AND state='RUNNING'",(row['id'],))
            self._checkpoint(db,row['id'],'EXECUTION_OWNER_RECONCILED',
                             {'known_dead_or_reused':known_dead,'identity_unavailable':not known_dead,'unknown_outcome':bool(unknown),'status':state})
            reconciled.append({'workflow_id':row['id'],'status':state,'unknown_outcome':bool(unknown)})
        return reconciled

    def reconcile_ownership(self, project_id=None):
        """Reconcile persisted leases without killing a PID or replaying work."""
        if project_id is not None:self.store.project(project_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return {'reconciled':self._reconcile_ownership(db,project_id)}

    def _snapshot(self, workflow):
        project = self.store.project(workflow['project_id'])
        return snapshot(project['path'], exclusions=_load(project.get('exclusions'), []))

    def _checkpoint(self, db, workflow_id, event, data=None, task_id=None, action_id=None):
        db.execute('INSERT INTO w5_checkpoints(workflow_id,task_id,action_id,event,data,created_at) VALUES(?,?,?,?,?,?)',
                   (workflow_id, task_id, action_id, event, _json(data or {}), time.time()))

    def create(self, project_id, objective, criteria, providers=None, budgets=None, context_mode='retrieved', model_overrides=None, execution_policy='standard', transaction=None):
        self.store.project(project_id)
        if not isinstance(objective, str) or not objective.strip():
            raise ValueError('Objective is required')
        if not isinstance(criteria, list) or not criteria or not all(isinstance(c, str) and c.strip() for c in criteria):
            raise ValueError('Explicit nonempty acceptance criteria are required')
        safe_text(objective)
        for criterion in criteria:
            safe_text(criterion)
        if context_mode not in ('retrieved','full_index'):
            raise ValueError('Unknown context mode')
        if execution_policy not in ('standard','single_task'):
            raise ValueError('Execution policy must be standard or single_task (skip planning only)')
        overrides=dict(model_overrides or {})
        if set(overrides)-{'planner','executor','reviewer'}:
            raise ValueError('Unknown override role')
        from .providers import validate_model
        for value in overrides.values(): validate_model(value)
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
            if key not in ('max_cost',) and (not isinstance(value, int) or (value == 0 and key not in ('max_depth', 'max_retries', 'max_continuations'))):
                raise ValueError('Count/time budgets must be positive integers')
        if limits['max_depth'] > 8 or limits['max_retries'] > 5 or limits['max_tasks'] > 1000 or limits['max_concurrency'] > 16 or limits['max_output_tokens'] > 32768 or limits['call_timeout'] > 3600:
            raise ValueError('Budget exceeds engine safety maximum')
        if not 64 <= limits['max_context_tokens'] <= 32000 or limits['max_provider_calls'] > 1000 or limits['max_continuations'] > 5:
            raise ValueError('Context/call/continuation budget outside safety bounds')
        if not 256 <= limits['max_request_tokens'] <= 1000000 or limits['context_reserve_tokens'] > 32000:
            raise ValueError('Request context/reserve budget outside safety bounds')
        identifier, now = _id(), time.time()
        with (nullcontext(transaction) if transaction is not None else self.store.connect()) as db:
            db.execute('INSERT INTO w5_workflows(id,project_id,objective,criteria,providers,budgets,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (identifier, project_id, objective.strip(), _json(criteria), _json(roles), _json(limits), 'READY', now, now))
            db.execute('UPDATE w5_workflows SET context_mode=? WHERE id=?',(context_mode,identifier))
            db.execute('UPDATE w5_workflows SET model_overrides=?,execution_policy=? WHERE id=?',(_json(overrides),execution_policy,identifier))
            self._checkpoint(db, identifier, 'WORKFLOW_CREATED', {'criteria': criteria, 'providers': roles, 'budgets': limits})
            if transaction is not None:
                return self._workflow(db, identifier)
        return self.status(identifier)

    def _workflow(self, db, workflow_id):
        row = db.execute('SELECT * FROM w5_workflows WHERE id=?', (workflow_id,)).fetchone()
        if not row:
            raise KeyError('Unknown workflow')
        value = dict(row)
        for key in ('criteria', 'providers', 'budgets', 'model_overrides'):
            value[key] = _load(value[key])
        value['budgets'] = dict(DEFAULT_BUDGETS, **value['budgets'])
        return value

    def _task(self, db, task_id):
        row = db.execute('SELECT * FROM w5_tasks WHERE id=?', (task_id,)).fetchone()
        if not row:
            raise KeyError('Unknown task')
        value = dict(row)
        value['evidence'] = _load(value['evidence'], {})
        value['depends_on'] = [r[0] for r in db.execute('SELECT depends_on FROM w5_dependencies WHERE task_id=? ORDER BY depends_on', (task_id,))]
        return value

    def _new_task(self, db, workflow, title, description='', parent_id=None, executor=None, reviewer=None):
        if not isinstance(title, str) or not title.strip():
            raise ValueError('Task title required')
        safe_text(title)
        safe_text(description)
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
                   (identifier, workflow['id'], parent_id, title.strip(), description, executor, reviewer, 'PENDING', depth, now, now))
        self._checkpoint(db, workflow['id'], 'TASK_CREATED', {'title': title, 'executor': executor, 'reviewer': reviewer}, identifier)
        return self._task(db, identifier)

    def create_task(self, workflow_id, title, description='', parent_id=None, executor=None, reviewer=None, depends_on=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL or workflow.get('lease_owner'):
                raise ValueError('Cannot alter a running or terminal workflow plan')
            task = self._new_task(db, workflow, title, description, parent_id, executor, reviewer)
            dependencies = list(depends_on or [])
            if len(dependencies) > 1000 or any(not isinstance(v, str) for v in dependencies):
                raise ValueError('Invalid task dependencies')
            for dependency in set(dependencies):
                prior = self._task(db, dependency)
                if prior['workflow_id'] != workflow_id:
                    raise ValueError('Dependency outside workflow')
                db.execute('INSERT INTO w5_dependencies VALUES(?,?)', (task['id'], dependency))
            return self._task(db, task['id'])

    def delegate(self, task_id, to_provider, from_provider=None):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            task = self._task(db, task_id)
            workflow = self._workflow(db, task['workflow_id'])
            source = from_provider or task['executor']
            if source != task['executor'] or not provider_identifier(to_provider) or source == to_provider:
                raise ValueError('Delegation must name the current executor and a different known provider')
            if task['status'] not in ('PENDING', 'BLOCKED') or workflow.get('lease_owner'):
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
            if not workflow.get('lease_owner'):
                db.execute("UPDATE w5_workflows SET status='READY',reason=?,updated_at=? WHERE id=?",
                    ('User-approved provider failover; destination approvals checked before dispatch', time.time(), task['workflow_id']))
        return result

    def transition_role(self, workflow_id, role, to_provider, actor='user'):
        """Authorized planner/reviewer handoff without resetting executor sessions."""
        if actor != 'user' or role not in ('planner', 'reviewer') or not provider_identifier(to_provider):
            raise PermissionError('A user-authorized planner/reviewer transition is required')
        if not self._approved(workflow_id, 'failover', role=role, to_provider=to_provider):
            raise PermissionError('Explicit role failover approval required')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL or workflow.get('lease_owner'):
                raise ValueError('Wait for the active runner before role handoff')
            if db.execute("SELECT 1 FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN')", (workflow_id,)).fetchone():
                raise PermissionError('Unknown outcomes must be reconciled before handoff')
            previous = workflow['providers'][role]
            if previous == to_provider:
                return self.status(workflow_id)
            workflow['providers'][role] = to_provider
            db.execute("UPDATE w5_workflows SET providers=?,status='READY',reason=NULL,updated_at=? WHERE id=?",
                       (_json(workflow['providers']), time.time(), workflow_id))
            if role == 'reviewer':
                db.execute("UPDATE w5_tasks SET reviewer=?,status=CASE WHEN status='REVIEWING' THEN 'TESTING' ELSE status END WHERE workflow_id=? AND status!='VERIFIED'",
                           (to_provider, workflow_id))
            handoff = {'role': role, 'from': previous, 'to': to_provider,
                       'objective': workflow['objective'], 'criteria': workflow['criteria'],
                       'pending_tasks': [dict(r) for r in db.execute("SELECT id,title,status FROM w5_tasks WHERE workflow_id=? AND status!='VERIFIED'", (workflow_id,))]}
            self._checkpoint(db, workflow_id, 'ROLE_HANDOFF', handoff)
        return self.status(workflow_id)

    def task_status(self, workflow_id, task_id):
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            task = self._task(db, task_id)
            if task['workflow_id'] != workflow_id:
                raise PermissionError('Task outside selected workflow')
            return task

    def action_results(self, workflow_id):
        """Return visible result fields only; never replay opaque reasoning/history."""
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            records = []
            for row in db.execute('SELECT id,task_id,role,provider,state,response,started_at,finished_at FROM w5_actions WHERE workflow_id=? ORDER BY started_at', (workflow_id,)):
                value = dict(row)
                response = _load(value.pop('response'), {})
                value['result'] = {k: response[k] for k in ('status', 'output', 'usage', 'error_kind', 'usage_accounting', 'tokens_accounted') if k in response}
                records.append(value)
            return records

    def context_report(self, workflow_id):
        with self.store.connect() as db:
            self._workflow(db, workflow_id)
            result=[]
            for row in db.execute("SELECT id,role,provider,request,response FROM w5_actions WHERE workflow_id=? AND role IN ('planner','executor','reviewer') ORDER BY started_at",(workflow_id,)):
                request=_load(row['request'],{});response=_load(row['response'],{})
                try: prompt=_load(request.get('prompt'),{})
                except (ValueError,TypeError): prompt={}
                result.append({'action_id':row['id'],'role':row['role'],'provider':row['provider'],
                               'context':prompt.get('context'), 'reported_usage':response.get('usage'),
                               'accounting':response.get('usage_accounting')})
            return result

    def verify_task(self, workflow_id, task_id):
        """Inspect current evidence freshness without granting completion."""
        task=self.task_status(workflow_id,task_id)
        workflow=self.status(workflow_id)
        recorded=task['evidence'].get('review',{}).get('snapshot_hash')
        try:current=self._snapshot(workflow)['hash']
        except (OSError,ValueError,RuntimeError):current=None
        historical=task['status']=='VERIFIED'
        return {'task_id':task['id'],'verified':bool(historical and recorded and current==recorded),
                'recorded_verified':historical,'recorded_snapshot':recorded,'current_snapshot':current,
                'evidence':task['evidence'],'mutated':False,
                'basis':'Current filtered project snapshot matches the engine-tested and reviewed snapshot'}

    def request_approval(self, workflow_id, kind, scope, reason):
        """Untrusted request inbox; inserting a request grants no capability."""
        from .store import safe_text
        if kind not in {'sharing','cost','native_agent_access','native_agent_write','command','recovery','failover','operations'} or not isinstance(scope, dict):
            raise ValueError('Invalid approval request')
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000 or len(_json(scope)) > 8000:
            raise ValueError('Bounded approval reason/scope required')
        if sensitive_content(scope):
            raise ValueError('Recognizable sensitive approval scope refused; use secure credential references')
        safe_text(reason); safe_text(_json(scope))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._workflow(db, workflow_id)
            active=db.execute('SELECT id FROM w5_approvals WHERE workflow_id=? AND kind=? AND scope_hash=? AND revoked=0',(workflow_id,kind,_hash(scope))).fetchone()
            if active:return {'id':active[0],'status':'ALREADY_APPROVED','grants_permission':False}
            prior = db.execute("SELECT id FROM w5_requests WHERE workflow_id=? AND kind=? AND scope=? AND status='PENDING'", (workflow_id, kind, _json(scope))).fetchone()
            if prior:
                return {'id': prior[0], 'status': 'PENDING', 'grants_permission': False}
            if db.execute("SELECT COUNT(*) FROM w5_requests WHERE workflow_id=? AND status='PENDING'",(workflow_id,)).fetchone()[0]>=100:
                raise ValueError('Pending approval request limit reached')
            identifier = _id()
            db.execute('INSERT INTO w5_requests(id,workflow_id,kind,scope,reason,created_at) VALUES(?,?,?,?,?,?)',
                       (identifier, workflow_id, kind, _json(scope), reason, time.time()))
            self._checkpoint(db, workflow_id, 'APPROVAL_REQUESTED', {'request_id': identifier, 'kind': kind})
        return {'id': identifier, 'status': 'PENDING', 'grants_permission': False}

    def resolve_request(self, workflow_id, request_id, decision='approve', actor='user'):
        if actor!='user' or decision not in ('approve','deny'):
            raise PermissionError('Only the authenticated user may approve or deny a request')
        target='APPROVED' if decision=='approve' else 'DENIED'
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            self._workflow(db,workflow_id)
            request=db.execute('SELECT * FROM w5_requests WHERE id=? AND workflow_id=?',(request_id,workflow_id)).fetchone()
            if not request:raise KeyError('Request outside selected workflow')
            if request['status']!='PENDING':
                if request['status']!=target:raise ValueError('Request already resolved; use revoke to change an approval')
                return {'id':request_id,'status':target,'reused':True}
            approval_id=None
            if decision=='approve':
                scope=self._approval_scope(request['kind'],_load(request['scope']))
                existing=db.execute('SELECT id FROM w5_approvals WHERE workflow_id=? AND kind=? AND scope_hash=? AND revoked=0',
                                    (workflow_id,request['kind'],_hash(scope))).fetchone()
                approval_id=existing[0] if existing else _id()
                if not existing:
                    db.execute('INSERT INTO w5_approvals(id,workflow_id,kind,scope,scope_hash,actor,created_at) VALUES(?,?,?,?,?,?,?)',
                               (approval_id,workflow_id,request['kind'],_json(scope),_hash(scope),actor,time.time()))
                    self._checkpoint(db,workflow_id,'USER_APPROVAL',{'id':approval_id,'kind':request['kind'],'scope_hash':_hash(scope)})
            db.execute('UPDATE w5_requests SET status=? WHERE id=?',(target,request_id))
            self._checkpoint(db,workflow_id,'APPROVAL_REQUEST_RESOLVED',{'request_id':request_id,'status':target,'approval_id':approval_id})
            return {'id':request_id,'status':target,'approval_id':approval_id,
                    'note':'Request resolution does not revoke other existing approvals'}

    def submit_review(self, workflow_id, task_id, review):
        from .store import safe_text
        self.task_status(workflow_id, task_id)
        if not isinstance(review, str) or not review.strip() or len(review) > 8000:
            raise ValueError('Bounded review text required')
        safe_text(review)
        with self.store.connect() as db:
            self._checkpoint(db, workflow_id, 'ADVISORY_REVIEW_SUBMITTED', {'text': review, 'verified': False}, task_id)
        return {'recorded': True, 'verified': False, 'note': 'External review is advisory; trusted test/reviewer gates remain required'}

    def request_correction(self, workflow_id, task_id, reason):
        from .store import safe_text
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError('Bounded correction reason required')
        safe_text(reason)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            task = self._task(db, task_id)
            if task['workflow_id'] != workflow_id:
                raise PermissionError('Task outside selected workflow')
            if workflow['status'] in TERMINAL or workflow.get('lease_owner'):
                raise ValueError('Cannot change a running or terminal workflow')
            if db.execute("SELECT 1 FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN')", (workflow_id,)).fetchone():
                raise PermissionError('Reconcile unknown outcomes before correction')
            if task['attempts'] >= workflow['budgets']['max_retries']:
                raise ValueError('Correction budget exhausted')
            db.execute("UPDATE w5_tasks SET status='PENDING',attempts=attempts+1,error=?,updated_at=? WHERE id=?", (reason, time.time(), task_id))
            db.execute("UPDATE w5_actions SET consumed=1 WHERE workflow_id=? AND task_id=? AND state='COMPLETED'",(workflow_id,task_id))
            db.execute("UPDATE w5_workflows SET status='READY',reason=NULL WHERE id=?", (workflow_id,))
            self._checkpoint(db, workflow_id, 'CORRECTION_REQUESTED', {'reason': reason}, task_id)
        return self.task_status(workflow_id, task_id)

    def _approval_scope(self, kind, scope):
        allowed = {'sharing', 'cost', 'native_agent_access', 'native_agent_write', 'command', 'recovery', 'failover', 'operations'}
        if kind not in allowed or not isinstance(scope, dict):
            raise ValueError('Invalid approval kind or scope')
        if sensitive_content(scope):
            raise ValueError('Recognizable sensitive approval scope refused; use secure credential references')
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
        return scope

    def approve(self, workflow_id, kind, scope, actor='user', transaction=None):
        """Trusted operator endpoint. This method is deliberately not a model tool."""
        if actor != 'user':
            raise PermissionError('Only an authenticated user may grant approval')
        scope=self._approval_scope(kind,scope)
        with (nullcontext(transaction) if transaction is not None else self.store.connect()) as db:
            if transaction is None:
                db.execute('BEGIN IMMEDIATE')
            self._workflow(db, workflow_id)
            existing = db.execute('SELECT id FROM w5_approvals WHERE workflow_id=? AND kind=? AND scope_hash=? AND revoked=0',
                                  (workflow_id, kind, _hash(scope))).fetchone()
            if existing:
                return {'id': existing[0], 'kind': kind, 'scope': scope, 'actor': actor, 'reused': True}
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
            project_id=self._workflow(db,workflow_id)['project_id']
        self.reconcile_ownership(project_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL:
                raise ValueError('Terminal workflow cannot be resumed')
            if workflow.get('lease_owner'):
                raise ValueError('Wait for the active worker to finish before resuming')
            cancelled = []
            for action in db.execute("SELECT * FROM w5_actions WHERE workflow_id=? AND state='COMPLETED' AND consumed=0", (workflow_id,)):
                response = _load(action['response'], {})
                if isinstance(response, dict) and response.get('status') == 'cancelled':
                    cancelled.append(action)
            if cancelled:
                try:
                    current_hash = self._snapshot(workflow)['hash']
                except (OSError, ValueError, RuntimeError):
                    current_hash = None
                read_only = {'list_directory', 'read_file', 'search', 'git_diff'}
                for action in cancelled:
                    request = _load(action['request'], {})
                    operations = request.get('allowed_operations') if isinstance(request, dict) else None
                    safe_to_repeat = (action['role'] in ('planner', 'reviewer')
                        and isinstance(operations, list) and all(op in read_only for op in operations)
                        and current_hash is not None
                        and action['before_hash'] == action['after_hash'] == current_hash)
                    if safe_to_repeat:
                        # Explicit Resume may repeat a cancelled scoped read-only
                        # call, never replay its cancelled response as useful work.
                        # Retain history/session IDs and account the original call.
                        db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (action['id'],))
                        self._checkpoint(db, workflow_id, 'READ_ONLY_CANCELLED_ACTION_CONSUMED',
                            {'role': action['role']}, action['task_id'], action['id'])
                    else:
                        # Executor/native-access cancellation can hide effects
                        # outside the filtered snapshot. Require reconciliation.
                        db.execute("UPDATE w5_actions SET state='UNCERTAIN' WHERE id=?", (action['id'],))
                        self._checkpoint(db, workflow_id, 'CANCELLED_ACTION_REQUIRES_RECOVERY',
                            {'role': action['role']}, action['task_id'], action['id'])
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
            workflow['approval_requests'] = [dict(r, scope=_load(r['scope'])) for r in db.execute("SELECT * FROM w5_requests WHERE workflow_id=? AND status='PENDING' ORDER BY created_at", (workflow_id,))]
            workflow['provider_calls'] = db.execute("SELECT COUNT(*) FROM w5_actions WHERE workflow_id=? AND role IN ('planner','executor','reviewer')", (workflow_id,)).fetchone()[0]
            workflow['sessions'] = [dict(r) for r in db.execute('SELECT task_id,provider,role,session_id FROM w5_sessions WHERE workflow_id=?', (workflow_id,))]
            workflow['health'] = ('heartbeat_late' if workflow.get('lease_owner') and (not workflow['lease_until'] or workflow['lease_until']<=time.time())
                                  else 'active' if workflow.get('lease_owner')
                                  else 'recovery_required' if workflow['pending_actions'] else 'idle')
            if workflow['health']=='heartbeat_late':
                workflow['health_detail']='Heartbeat is late. Pause or stop the owning runner and inspect persisted evidence; the engine does not steal ownership from a live process.'
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

    def _provider_budget(self, workflow):
        with self.store.connect() as db:
            used = db.execute("SELECT COUNT(*) FROM w5_actions WHERE workflow_id=? AND role IN ('planner','executor','reviewer')", (workflow['id'],)).fetchone()[0]
        if used >= workflow['budgets']['max_provider_calls']:
            return 'Provider-call budget exhausted'
        return self._budget(workflow)

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
            if row and row['session_id']:
                self._check_chat_session(db,provider,row['session_id'])
            return dict(row) if row else {'session_id': None, 'history': '[]'}

    def _check_chat_session(self, db, provider, session_id):
        if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chats'").fetchone():
            if db.execute('SELECT 1 FROM chats WHERE provider=? AND session_id=?',(provider,session_id)).fetchone():
                raise PermissionError('Provider session belongs to a separate chat conversation')

    def _invoke(self, workflow, task, role, provider, registry, prompt, cancel_event):
        if cancel_event.is_set() or self.status(workflow['id'])['status'] != 'RUNNING':
            return None
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
        budget_error = self._provider_budget(workflow)
        if budget_error:
            self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', budget_error)
            return None
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
        context_options={'budget':min(workflow['budgets']['max_context_tokens'], remaining // 2),
                         'critical':[workflow['objective']] + workflow['criteria']}
        context = (self.store.full_context(workflow['project_id'],**context_options) if workflow.get('context_mode')=='full_index'
                   else self.store.context(workflow['project_id'],query,role='correction' if role=='executor' and task and task['attempts'] else role,**context_options))
        prompt = dict(prompt, context={'content': context['content'], 'references': context['references'],
                                      'estimated_tokens': context['estimated_tokens'], 'id': context['id'],
                                      'excluded':context['excluded'],'budget':context['budget'],'bytes':context['bytes']})
        request = {'project': project, 'prompt': _json(prompt), 'role': role, 'session_id': session['session_id'],
                   'timeout': min(workflow['budgets']['call_timeout'], max(1, workflow['budgets']['max_seconds'] - int(time.time() - workflow['started_at']))),
                   'allowed_operations': operations, 'history': _load(session['history'], []),
                   'max_output_tokens': min(workflow['budgets']['max_output_tokens'], workflow['budgets']['max_tokens'] - workflow['tokens_used'])}
        if workflow.get('model_overrides',{}).get(role):
            request['model']=workflow['model_overrides'][role]
        estimate_input = max(1, (len(request['prompt'].encode('utf-8')) + len(_json(request['history']).encode('utf-8')) + 3) // 4)
        if estimate_input >= remaining:
            self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Prompt/transcript exceeds remaining estimated token budget')
            return None
        request['max_output_tokens'] = min(request['max_output_tokens'], remaining - estimate_input)
        # This configured envelope is a local estimate, not a guessed model
        # window. Opaque native history/system overhead remains unobservable.
        request_limit=workflow['budgets']['max_request_tokens']
        reserve=workflow['budgets']['context_reserve_tokens']
        output_room=request_limit-estimate_input-reserve
        if output_room < request['max_output_tokens']:
            self._set_status(workflow['id'], 'BUDGET_EXHAUSTED', 'Estimated request plus output reserve exceeds configured request context budget; split the task or explicitly adjust the budget')
            return None
        reservation = 0 if getattr(registry, 'offline', False) else self._approved(workflow['id'], 'cost', provider=provider)[-1]['scope']['max_call_cost']
        journal_request = dict(request, cost_reservation=reservation)
        journal_request['context_package_id'] = context['id']
        journal_request['context_accounting']={'estimated_input_tokens':estimate_input,
            'prompt_bytes':len(request['prompt'].encode()),'observable_history_bytes':len(_json(request['history']).encode()),
            'output_reserved_tokens':request['max_output_tokens'],'safety_reserve_tokens':reserve,
            'request_budget_tokens':request_limit,'native_history_occupancy':'unknown',
            'measurement':'local UTF-8 bytes/4 estimate; adapter/native overhead not exactly observable'}
        contracts=[{'kind':a['kind'],'scope':a['scope']} for a in self.approvals(workflow['id']) if not a['revoked']]
        journal_request['execution_contract_hash']=_hash({'approvals':sorted(contracts,key=_json),
            'policy':workflow.get('execution_policy'),'output_limit':workflow['budgets']['max_output_tokens'],
            'dispatched_output_limit':request['max_output_tokens'],
            'retry_limit':workflow['budgets']['max_retries'],'call_timeout':workflow['budgets']['call_timeout']})
        journal_request['provider_model'] = request.get('model') or registry.get(provider).status().get('model')
        journal_request['offline_mock'] = bool(getattr(registry,'offline',False))
        action_id = _id()
        with self.store.connect() as db:
            db.execute('INSERT INTO w5_actions(id,workflow_id,task_id,role,provider,state,request,before_hash,started_at) VALUES(?,?,?,?,?,?,?,?,?)',
                       (action_id, workflow['id'], task_id, role, provider, 'RUNNING', _json(journal_request), initial['hash'], time.time()))
            db.execute('UPDATE w5_workflows SET cost_used=cost_used+? WHERE id=?', (reservation, workflow['id']))
            self._checkpoint(db, workflow['id'], 'ACTION_STARTED', {'role': role, 'provider': provider}, task_id, action_id)
        request['cancel_event'] = cancel_event
        event_count = [0]
        visible_text = ['']
        def visible_event(event):
            if event_count[0] >= 64 or not isinstance(event,dict) or sensitive_content(event):
                return
            from .store import safe_text
            kind=event.get('type')
            if kind not in ('text','usage','tool_call','completed','cancelled','timeout','error','session'):
                return
            value={'type':kind,'provider':provider,'role':role}
            if kind=='text':
                fragment = str(event.get('text',''))[:2000]
                try:
                    # Check exactly the concatenation that telemetry exposes,
                    # independently of adapter result validation.
                    safe_text(visible_text[0] + fragment)
                    value['text'] = fragment
                    visible_text[0] += fragment
                except ValueError:
                    value['text']='[Recognizable sensitive output withheld]'
            if kind=='tool_call': value['operation']=(event.get('tool_call') or {}).get('name')
            if kind=='usage': value['usage']={k:v for k,v in (event.get('usage') or {}).items() if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)}
            with self.store.connect() as db:
                self._checkpoint(db,workflow['id'],'PROVIDER_EVENT',value,task_id,action_id)
            event_count[0]+=1
        request['event_callback'] = visible_event
        try:
            result = registry.invoke(provider, request)
            if not isinstance(result, dict):
                raise ValueError('Provider returned an invalid result')
            if sensitive_content(result):
                raise ValueError('Recognizable sensitive provider output refused')
            if session['session_id'] and result.get('session_id') and result['session_id'] != session['session_id']:
                raise ValueError('Provider changed the exact persistent session ID')
            if result.get('session_id'):
                with self.store.connect() as db:
                    self._check_chat_session(db,provider,result['session_id'])
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
            if not isinstance(usage,dict): raise ValueError('Invalid provider usage')
            measured_parts=[]
            estimated_parts=[estimate_input,max(1,(len(str(result.get('output','')).encode())+3)//4)]
            for key,alias in (('input_tokens','prompt_tokens'),('output_tokens','completion_tokens')):
                value=usage.get(key,usage.get(alias))
                if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0):
                    raise ValueError('Invalid provider token usage')
                measured_parts.append(int(value) if value is not None else None)
            used=sum(estimated_parts[i] if value is None else value for i,value in enumerate(measured_parts))
            accounting=('reported' if all(v is not None for v in measured_parts) else
                        'estimated_utf8_bytes_div4' if all(v is None for v in measured_parts) else 'mixed_reported_and_estimated')
            reported_cost = max(0.0, float(usage.get('cost', 0.0)))
            if not math.isfinite(reported_cost):
                raise ValueError('Invalid provider cost usage')
            cost = max(0.0, reported_cost - reservation)
            stored = {key: value for key, value in result.items() if key not in ('events',)}
            if result.get('status') not in ('completed', 'tool_calls'):
                result['error_kind'] = stored['error_kind'] = classify_failure(result)
            # Provider approval requests are ordinary output, never capability grants.
            stored['usage_accounting'] = accounting
            stored['cost_accounting'] = 'reported_or_reserved_maximum' if reservation else 'offline_mock'
            stored['cost_reserved'] = reservation
            stored['tokens_accounted'] = used
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if result.get('session_id'):
                    self._check_chat_session(db,provider,result['session_id'])
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
                if result.get('error_kind'):
                    self._checkpoint(db, workflow['id'], 'PROVIDER_FAILURE_CLASSIFIED', {'category': result['error_kind'], 'provider': provider, 'role': role}, task_id, action_id)
            if role != 'executor' and initial['hash'] != final['hash']:
                self._set_status(workflow['id'], 'FAILED', 'Read-only provider modified the project')
                return None
            result['_action_id'] = action_id
            result['_snapshot_hash'] = final['hash']
            return result
        except Exception as error:
            with self.store.connect() as db:
                db.execute("UPDATE w5_actions SET state='UNCERTAIN',response=?,finished_at=? WHERE id=?",
                           (_json({'error': type(error).__name__}), time.time(), action_id))
                self._checkpoint(db, workflow['id'], 'ACTION_OUTCOME_UNCERTAIN', {'error': type(error).__name__}, task_id, action_id)
            self._set_status(workflow['id'], 'RECOVERY_REQUIRED', 'Provider action outcome uncertain; explicit recovery approval required')
            return None

    def _commands(self, workflow_id):
        commands = {}
        for approval in self._approved(workflow_id, 'command'):
            commands[approval['scope']['name']] = approval['scope']
        return commands

    def _tools(self, project, operations, commands, exclusions=(), cancel_event=None):
        from .tools import ScopedTools
        return ScopedTools(project, allowed_operations=operations,
                           approved_commands=commands, exclusions=exclusions, cancel_event=cancel_event)

    def _tests(self, workflow, task, cancel_event=None):
        commands = self._commands(workflow['id'])
        if not commands:
            self._set_status(workflow['id'], 'APPROVAL_REQUIRED', 'At least one exact test command needs user approval')
            return None
        project = self.store.project(workflow['project_id'])['path']
        before = self._snapshot(workflow)
        results = []
        for name, spec in commands.items():
            if (cancel_event is not None and cancel_event.is_set()) or self.status(workflow['id'])['status'] != 'RUNNING':
                return None
            # Command permissions are exact argv; provider claims never supply this evidence.
            approved_scope_hash = _hash(spec)
            remaining = max(1, workflow['budgets']['max_seconds'] - int(time.time() - workflow['started_at']))
            spec = dict(spec, timeout=min(spec['timeout'], workflow['budgets']['call_timeout'], remaining))
            tools = self._tools(project, ['run_command'], {name: spec},
                                exclusions=_load(self.store.project(workflow['project_id']).get('exclusions'), []), cancel_event=cancel_event)
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
        self.store.add_memory(workflow['project_id'],'error','Workflow correction '+task['title'][:200],
            _json({'workflow_id':workflow['id'],'task_id':task['id'],'reason':reason,
                   'attempt':task['attempts'],'resolved':False,
                   'error_signature':_hash(' '.join(reason.split())),
                   'observed_snapshot_hash':evidence.get('tests',{}).get('snapshot_hash') or evidence.get('execution',{}).get('snapshot_hash')}),kind='observed',
            source='engine-correction:'+workflow['id'],confidence=1.0,expires_at=time.time()+30*86400)
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
                                exclusions=_load(self.store.project(workflow['project_id']).get('exclusions'), []), cancel_event=cancel_event)
            session = self._session(workflow['id'], task['id'] if task else None, provider, role)
            history = _load(session['history'], [])
            message = result.get('message') or {'role': 'assistant', 'content': result.get('output') or None,
                'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': _json(c['arguments'])}} for c in calls]}
            if not history or history[-1] != message:
                history.append(message)
            for call in calls:
                if cancel_event.is_set() or self.status(workflow['id'])['status'] != 'RUNNING':
                    return None
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
            if cancel_event.is_set() or workflow['status'] != 'RUNNING':
                return None
            result = self._invoke(workflow, task, role, provider, registry, prompt, cancel_event)
        return result

    def _response(self, workflow, task, role, provider, registry, prompt, cancel_event):
        """Bounded continuation of known incomplete output; never retry unknown effects."""
        fingerprints = set()
        task_id = task['id'] if task else None
        while True:
            result = self._invoke(self.status(workflow['id']), task, role, provider, registry, prompt, cancel_event)
            result = self._handle_tools(self.status(workflow['id']), task, provider, role, result, registry, prompt, cancel_event)
            if not result or cancel_event.is_set() or self.status(workflow['id'])['status'] != 'RUNNING':
                return None
            incomplete = result.get('status') == 'incomplete' or classify_failure(result) == 'incomplete'
            if result.get('status') == 'completed' and role in ('planner', 'reviewer'):
                try:
                    structured=_decode_object(result.get('output', ''))
                    if role=='planner':
                        items=structured.get('tasks')
                        if not isinstance(items,list) or not items or any(not isinstance(item,dict) or not isinstance(item.get('title'),str) or not item['title'].strip() for item in items):
                            incomplete=True
                    elif structured.get('decision') not in ('approve','changes_requested') or not isinstance(structured.get('criteria'),list):
                        incomplete=True
                except (ValueError, TypeError):
                    incomplete = True
            if result.get('status') == 'completed' and not incomplete:
                return result
            category = 'invalid_response' if incomplete and result.get('status') == 'completed' else classify_failure(result)
            with self.store.connect() as db:
                prior = [r for r in db.execute("SELECT data FROM w5_checkpoints WHERE workflow_id=? AND task_id IS ? AND event='PROVIDER_CONTINUATION'", (workflow['id'], task_id))
                         if _load(r['data']).get('role') == role]
                fingerprint = _hash([result.get('output'), result.get('_snapshot_hash')])
                repeated = fingerprint in fingerprints or any(_load(r['data']).get('fingerprint') == fingerprint for r in prior)
                if incomplete and len(prior) < workflow['budgets']['max_continuations'] and not repeated:
                    db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (result['_action_id'],))
                    self._checkpoint(db, workflow['id'], 'PROVIDER_CONTINUATION', {'role': role, 'category': category, 'fingerprint': fingerprint}, task_id, result['_action_id'])
                    continue_allowed = True
                else:
                    continue_allowed = False
                    if category in ('network', 'timeout', 'unknown'):
                        db.execute("UPDATE w5_actions SET state='UNCERTAIN' WHERE id=?", (result['_action_id'],))
                    else:
                        db.execute('UPDATE w5_actions SET consumed=1 WHERE id=?', (result['_action_id'],))
                    self._checkpoint(db, workflow['id'], 'PROVIDER_BLOCKED', {'provider': provider, 'role': role, 'category': category, 'no_progress': repeated}, task_id, result['_action_id'])
            if continue_allowed:
                fingerprints.add(fingerprint)
                prompt = dict(prompt, continuation='Continue the existing task without repeating completed changes. Return the requested complete response; preserve prior tool results and acceptance criteria.')
                continue
            if category in ('usage_limit','authentication') and role in ('planner','reviewer'):
                destination=self._authorized_handoff(workflow,task,role,provider,registry)
                if destination:
                    provider=destination
                    if task and role=='reviewer': task['reviewer']=destination
                    workflow=self.status(workflow['id'])
                    prompt=dict(prompt,handoff='Continue the pending role using the persisted task/test evidence. Existing executor work and sessions are preserved.')
                    continue
            if task and role == 'executor':
                self._task_evidence(task_id, 'BLOCKED', task['evidence'], 'Provider failure: ' + category)
            status = 'RECOVERY_REQUIRED' if category in ('network', 'timeout', 'unknown') else 'BLOCKED'
            self._set_status(workflow['id'], status, 'Provider ' + category + ('; no progress detected' if repeated else '; inspect connection or approve a safe handoff'))
            return None

    def _authorized_handoff(self, workflow, task, role, provider, registry):
        """Use only previously granted destination/cost scopes; never invent fallback."""
        with self.store.connect() as db:
            transitions=db.execute("SELECT COUNT(*) FROM w5_checkpoints WHERE workflow_id=? AND event='AUTOMATIC_ROLE_HANDOFF'",(workflow['id'],)).fetchone()[0]
        if transitions>=workflow['budgets']['max_depth']: return None
        for approval in reversed(self._approved(workflow['id'],'failover',role=role)):
            target=approval['scope'].get('to_provider')
            if not provider_identifier(target) or target==provider: continue
            try:
                if registry.get(target).status().get('available') is False or self._gate(self.status(workflow['id']),target,role,registry): continue
            except (ValueError,KeyError,RuntimeError): continue
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current=self._workflow(db,workflow['id'])
                if current['status']!='RUNNING':return None
                still=db.execute('SELECT revoked FROM w5_approvals WHERE id=?',(approval['id'],)).fetchone()
                if not still or still[0]:continue
                current['providers'][role]=target
                db.execute('UPDATE w5_workflows SET providers=?,updated_at=? WHERE id=?',(_json(current['providers']),time.time(),workflow['id']))
                if role=='reviewer':
                    db.execute("UPDATE w5_tasks SET reviewer=? WHERE workflow_id=? AND status!='VERIFIED'",(target,workflow['id']))
                self._checkpoint(db,workflow['id'],'AUTOMATIC_ROLE_HANDOFF',
                    {'role':role,'from':provider,'to':target,'approval_id':approval['id'],
                     'preserved_executor_sessions':True,'task_id':task['id'] if task else None})
            return target
        return None

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
        from ccx_install import workspace_runtime
        with workspace_runtime():
            return self._run(workflow_id,registry)

    def _run(self, workflow_id, registry):
        owner, stop, cancel_event = _id(), threading.Event(), threading.Event()
        owner_pid=os.getpid()
        try:owner_birth=self._process_birth(owner_pid)
        except (OSError,ValueError,NotImplementedError):owner_birth=None
        with self.store.connect() as db:
            project_id=self._workflow(db,workflow_id)['project_id']
        self.reconcile_ownership(project_id)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            workflow = self._workflow(db, workflow_id)
            if workflow['status'] in TERMINAL or workflow['status'] in ('PAUSED', 'RECOVERY_REQUIRED', 'BLOCKED', 'BUDGET_EXHAUSTED'):
                return self.status(workflow_id)
            active_project = db.execute('SELECT id FROM w5_workflows WHERE project_id=? AND id!=? AND lease_owner IS NOT NULL',
                                        (workflow['project_id'], workflow_id)).fetchone()
            unknown_project=db.execute("SELECT a.id FROM w5_actions a JOIN w5_workflows w ON w.id=a.workflow_id WHERE w.project_id=? AND w.id!=? AND w.status NOT IN ('CANCELLED','COMPLETED','FAILED') AND a.state IN ('RUNNING','UNCERTAIN') LIMIT 1",
                                       (workflow['project_id'],workflow_id)).fetchone()
            if active_project or workflow['lease_owner'] or unknown_project:
                return dict(self.status(workflow_id), busy=True)
            uncertain = db.execute("SELECT id FROM w5_actions WHERE workflow_id=? AND state IN ('RUNNING','UNCERTAIN') LIMIT 1", (workflow_id,)).fetchone()
            if uncertain:
                db.execute("UPDATE w5_workflows SET status='RECOVERY_REQUIRED',reason='Unfinished action requires recovery approval' WHERE id=?", (workflow_id,))
                return dict(workflow, status='RECOVERY_REQUIRED')
            db.execute("UPDATE w5_workflows SET status='RUNNING',reason=NULL,lease_owner=?,lease_until=?,lease_pid=?,lease_start_ticks=?,started_at=COALESCE(started_at,?),updated_at=? WHERE id=?",
                       (owner, time.time()+60, owner_pid, owner_birth, time.time(), time.time(), workflow_id))
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
            indexed = self.store.index(workflow['project_id'])
            with self.store.connect() as db:
                self._checkpoint(db, workflow_id, 'CONTEXT_INDEX_REFRESHED', indexed)
            if not workflow['tasks'] and workflow.get('execution_policy')=='single_task':
                with self.store.connect() as db:
                    self._new_task(db,workflow,workflow['objective'])
                    self._checkpoint(db,workflow_id,'SINGLE_TASK_POLICY',{'planning_skipped':True,'independent_review_required':True})
                workflow=self.status(workflow_id)
            if not workflow['tasks']:
                prompt = {'role': 'planner', 'objective': workflow['objective'], 'criteria': workflow['criteria'],
                          'instruction': 'Return JSON {"tasks":[{"title":"...","description":"..."}]}. No approvals or commands may be granted.',
                          'max_tasks': workflow['budgets']['max_tasks']}
                result = self._response(workflow, None, 'planner', workflow['providers']['planner'], registry, prompt, cancel_event)
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
                task_map = {t['id']: t for t in workflow['tasks']}
                eligible = [t for t in unfinished if t['status'] not in ('PENDING', 'EXECUTING') or all(
                    task_map[d]['status'] in ('TESTING', 'REVIEWING', 'VERIFIED') and task_map[d]['evidence'].get('execution')
                    for d in t.get('depends_on', []))]
                if unfinished and not eligible:
                    self._set_status(workflow_id, 'BLOCKED', 'Task dependencies require completion or recovery')
                    break
                unfinished = eligible
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
                               'correction_rounds':sum(t['attempts'] for t in workflow['tasks']),
                               'prior_corrections_resolved':True,
                               'criteria': workflow['criteria'], 'tasks': [
                                   {'id': t['id'], 'reviewer': t['reviewer'],
                                    'test_exit_codes': [c['exit_code'] for c in t['evidence']['tests']['commands']],
                                    'review_action': t['evidence']['review']['action_id']} for t in workflow['tasks']]}
                    prior=[m for m in self.store.memories(workflow['project_id']) if m['scope']=='verification'
                           and m['source']=='workflow:'+workflow_id and m['source_hash']==current and m['body']==_json(summary)]
                    memory = prior[0] if prior else self.store.add_memory(workflow['project_id'], 'verification',
                        'Workflow verification ' + workflow_id, _json(summary), kind='verified',
                        source='workflow:' + workflow_id, source_hash=current, confidence=1.0, verified_at=time.time())
                    with self.store.connect() as db:
                        self._checkpoint(db, workflow_id, 'VERIFICATION_MEMORY_SAVED', {'memory_id': memory['id']})
                    # A verified receipt supersedes the unresolved observation;
                    # it does not turn a model's diagnosis into a verified cause.
                    for record in self.store.memories(workflow['project_id']):
                        if record['scope']!='error' or record['source']!='engine-correction:'+workflow_id:
                            continue
                        observation=_load(record['body'],{})
                        if not isinstance(observation,dict) or observation.get('workflow_id')!=workflow_id:
                            continue
                        resolved=dict(observation,resolved=True,verification_memory_id=memory['id'],
                            verification_snapshot=current,
                            resolution_basis='Engine completion gates passed; original finding remains an observation, not a proven root cause')
                        self.store.add_memory(workflow['project_id'],'error',record['title'],_json(resolved),
                            kind='verified',source='workflow:'+workflow_id,source_hash=current,
                            confidence=1.0,verified_at=time.time(),supersedes=record['id'])
                    self.store.index(workflow['project_id'])
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
                    result = self._response(workflow, task, 'executor', task['executor'], registry, prompt, cancel_event)
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
                    self.store.index(workflow['project_id'])
                    if any(t['id'] != task['id'] and t['status'] in ('PENDING', 'EXECUTING') for t in self.status(workflow_id)['tasks']):
                        continue
                workflow = self.status(workflow_id)
                if workflow['status'] != 'RUNNING' or cancel_event.is_set():
                    break
                reason = self._budget(workflow)
                if reason:
                    self._set_status(workflow_id, 'BUDGET_EXHAUSTED', reason)
                    break
                tests = self._tests(workflow, task, cancel_event=cancel_event)
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
                result = self._response(self.status(workflow_id), task, 'reviewer', task['reviewer'], registry, prompt, cancel_event)
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
            from .store import safe_text
            try: detail=safe_text(str(error)[:500])
            except ValueError: detail='Sensitive error details withheld'
            self._set_status(workflow_id, status, type(error).__name__ + ': ' + detail)
            return self.status(workflow_id)
        finally:
            stop.set()
            thread.join(timeout=3)
            with self.store.connect() as db:
                db.execute('UPDATE w5_workflows SET lease_owner=NULL,lease_until=NULL,lease_pid=NULL,lease_start_ticks=NULL WHERE id=? AND lease_owner=?', (workflow_id, owner))
