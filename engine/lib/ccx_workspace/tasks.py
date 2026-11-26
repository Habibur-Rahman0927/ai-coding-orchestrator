"""Small task UX coordinator. Proposals are local; only explicit starts grant authority."""
import difflib
import hashlib
import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path
from .experience import propose, preferences
from .settings import setting, provider_config
from .store import read_source, safe_text, allowed
from .security import sensitive_content
from .workflows import snapshot, _hash


class TaskError(ValueError):
    """A fixed, user-actionable task validation message, safe to display."""


class TaskPermissionError(PermissionError):
    """An explicit consent requirement, safe to display."""


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,100}', value):
        raise TaskError('A valid submission identifier is required')
    return value


class Tasks:
    def __init__(self, dashboard):
        self.app = dashboard
        self.store, self.engine = dashboard.store, dashboard.engine
        with self.store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS task_proposals(
                id TEXT PRIMARY KEY, revision TEXT NOT NULL, payload TEXT NOT NULL,
                expires REAL NOT NULL, workflow_id TEXT, submission_key TEXT UNIQUE, launch_error TEXT);
                CREATE TABLE IF NOT EXISTS task_conversations(
                key TEXT PRIMARY KEY, digest TEXT NOT NULL, chat_id TEXT NOT NULL);''')

    def available(self, providers):
        for name in set(providers):
            entry = next((p for p in self.app.registry.status() if p['id'] == name), {})
            if not entry.get('available'):
                raise TaskError('Connect ' + name + ' first. No work has started.')

    def configuration(self, names):
        config = provider_config(self.store)
        return _hash({name: {'config': config.get(name, {}),
                            'capabilities': self.app.registry.get(name).status().get('capabilities', {})}
                      for name in names})

    def suggestions(self, project):
        saved = setting(self.store, 'task_preferences', {}).get(project['id'], {})
        if saved.get('commands'):
            return saved['commands']
        root, exclusions = project['path'], json.loads(project['exclusions'])
        try:
            from .store import allowed
            if allowed('package.json', exclusions):
                package = json.loads(read_source(Path(root), 'package.json', limit=65536))
                if isinstance(package.get('scripts', {}).get('test'), str):
                    return [{'name': 'tests', 'argv': ['npm', 'test'], 'cwd': '.', 'timeout': 120}]
        except (OSError, ValueError, PermissionError):
            pass
        return []

    def preview(self, body):
        permitted = {'project_id', 'provider', 'partner', 'instruction', 'criteria', 'commands',
                     'max_cost', 'max_call_cost', 'max_tokens', 'planning'}
        if set(body) - permitted:
            raise TaskError('Unknown task field')
        project = self.store.project(body.get('project_id'))
        provider = body.get('provider')
        partner = body.get('partner') or provider
        instruction = body.get('instruction', '')
        criteria = body.get('criteria') or instruction
        if not isinstance(criteria, str) or not criteria.strip():
            raise TaskError('Describe the requested outcome')
        plan = propose(self.store, self.app.registry, {
            'project_id': project['id'], 'provider': provider, 'partner': partner,
            'instruction': instruction, 'criteria': criteria, 'mode': 'build',
            'preset': 'feature' if body.get('planning') is True else 'quick_fix'})
        if plan['kind'] != 'workflow':
            raise TaskError('Open the saved task from recent work to continue it.')
        saved = setting(self.store, 'task_preferences', {}).get(project['id'], {})
        commands = body.get('commands', self.suggestions(project))
        if not isinstance(commands, list) or len(commands) > 10:
            raise TaskError('Choose at most ten test commands')
        normalized = []
        for command in commands:
            if not isinstance(command, dict) or set(command) - {'name', 'argv', 'cwd', 'timeout'}:
                raise TaskError('Test commands need a name, exact argument list, directory and timeout')
            normalized.append(self.engine._approval_scope('command', command))
        if len({c['name'] for c in normalized}) != len(normalized):
            raise TaskError('Test command names must be unique')
        max_cost = body.get('max_cost', saved.get('max_cost', plan['workflow']['budgets']['max_cost']))
        per_call = body.get('max_call_cost', saved.get('max_call_cost', 0))
        tokens = body.get('max_tokens', saved.get('max_tokens', plan['workflow']['budgets']['max_tokens']))
        for value in (max_cost, per_call):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 10000:
                raise TaskError('Usage reservations must be numbers between zero and 10000')
        if type(tokens) != int or not 128 <= tokens <= 1000000:
            raise TaskError('Token limit must be between 128 and 1000000')
        blockers = []
        if not normalized:
            blockers.append('Choose an exact test command before starting. No tests are run during preview.')
        if max_cost <= 0 or per_call <= 0 or per_call > max_cost:
            blockers.append('Set positive total and per-call usage reservations. Per-call must not exceed total.')
        plan['workflow']['budgets'].update(max_cost=max_cost, max_tokens=tokens)
        names = sorted({provider, partner})
        approvals = []
        for name in names:
            approvals.append({'kind': 'sharing', 'scope': {'provider': name}})
            if not blockers or (max_cost > 0 and 0 < per_call <= max_cost):
                approvals.append({'kind': 'cost', 'scope': {'provider': name, 'max_cost': max_cost, 'max_call_cost': per_call}})
            caps = self.app.registry.get(name).status().get('capabilities', {})
            if caps.get('native_agent_authorization_required'):
                approvals.append({'kind': 'native_agent_access', 'scope': {'provider': name}})
            if name == provider and caps.get('native_tools'):
                approvals.append({'kind': 'native_agent_write', 'scope': {'provider': name}})
        approvals.append({'kind': 'operations', 'scope': {'operations': ['patch']}})
        approvals.extend({'kind': 'command', 'scope': c} for c in normalized)
        for approval in approvals:
            self.engine._approval_scope(approval['kind'], approval['scope'])
        baseline = snapshot(project['path'], json.loads(project['exclusions']))
        payload = {'workflow': plan['workflow'], 'approvals': approvals, 'commands': normalized,
                   'blockers': blockers, 'project_path': project['path'], 'project_exclusions': project['exclusions'],
                   'baseline': baseline, 'configuration': self.configuration(names),
                   'providers': names, 'max_call_cost': per_call}
        safe_text(json.dumps(payload))
        revision, proposal_id, expires = _hash(payload), uuid.uuid4().hex, time.time() + 900
        with self.store.connect() as db:
            db.execute('DELETE FROM task_proposals WHERE workflow_id IS NULL AND expires < ?', (time.time()-86400,))
            db.execute('INSERT INTO task_proposals(id,revision,payload,expires) VALUES(?,?,?,?)',
                       (proposal_id, revision, json.dumps(payload), expires))
        return {'proposal_id': proposal_id, 'revision': revision, 'expires_at': expires,
                'workflow': plan['workflow'], 'approvals': approvals, 'commands': normalized,
                'max_call_cost': per_call, 'blockers': blockers, 'project_path': project['path'],
                'review': 'Separate ' + partner + ' review session',
                'notice': 'These permissions apply only to this task. Native CLI access may exceed filtered context. Usage reservations are not a guaranteed provider bill cap.'}

    def _before(self, project, baseline):
        """Bounded local comparison evidence, never sent to a model by this coordinator."""
        texts, used = {}, 0
        for record in baseline['files']:
            if len(record) < 3 or record[1] != 'file':
                continue
            try:
                data = read_source(Path(project['path']), record[0], limit=65536)
                if used + len(data) > 1048576:
                    continue
                if hashlib.sha256(data).hexdigest() != record[2]:
                    raise TaskError('Project changed during approval. Review the task again.')
                value = data.decode('utf-8')
                if '\0' in value or sensitive_content(value):
                    continue
                texts[record[0]] = value
                used += len(data)
            except TaskError:
                raise
            except (OSError, UnicodeError, ValueError, PermissionError):
                continue
        result = subprocess.run(['git', '-C', project['path'], 'status', '--porcelain', '-z', '--untracked-files=all'],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15)
        dirty = []
        entries = result.stdout.decode('utf-8', errors='replace').split('\0')
        skip = False
        allowed_names = {record[0] for record in baseline['files']}
        for entry in entries:
            if skip:
                skip = False
                continue
            if entry and entry[3:] in allowed_names:
                dirty.append(entry[3:])
            if entry[:1] in ('R', 'C'):
                skip = True
        return {'files': baseline['files'], 'texts': texts, 'preexisting': dirty}

    def start(self, body):
        if set(body) != {'proposal_id', 'revision', 'confirmed', 'idempotency_key'} or body['confirmed'] is not True:
            raise TaskPermissionError('Review the task and explicitly approve it first')
        key = identifier(body['idempotency_key'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM task_proposals WHERE id=?', (body['proposal_id'],)).fetchone()
            if not row or row['revision'] != body['revision']:
                raise TaskError('Task proposal changed. Review it again.')
            if row['workflow_id']:
                return {'workflow_id': row['workflow_id'], 'reused': True,
                        'notice': 'Previously accepted. Inspect saved state; no automatic restart.'}
            if db.execute('SELECT id FROM task_proposals WHERE submission_key=?', (key,)).fetchone():
                raise TaskError('Submission identifier already belongs to another task')
            if row['expires'] < time.time():
                raise TaskError('Task proposal expired. Review it again.')
            payload = json.loads(row['payload'])
            if payload['blockers']:
                raise TaskError('Finish the highlighted setup in the task card')
            workflow = payload['workflow']
            project = self.store.project(workflow['project_id'])
            self.available(payload['providers'])
            if (project['path'] != payload['project_path'] or project['exclusions'] != payload['project_exclusions']
                    or self.configuration(payload['providers']) != payload['configuration']
                    or snapshot(project['path'], json.loads(project['exclusions']))['hash'] != payload['baseline']['hash']):
                raise TaskError('Project or provider configuration changed. Review the task again.')
            before = self._before(project, payload['baseline'])
            value = self.engine.create(**workflow, transaction=db)
            for approval in payload['approvals']:
                self.engine.approve(value['id'], approval['kind'], approval['scope'], transaction=db)
            payload['before'] = before
            db.execute('UPDATE task_proposals SET workflow_id=?,submission_key=?,payload=? WHERE id=?',
                       (value['id'], key, json.dumps(payload), body['proposal_id']))
        # Commit permission and identity before launch. A crash here is inspectable, not auto-retried.
        try:
            result = self.app.run(value['id'])
        except Exception:
            with self.store.connect() as db:
                db.execute('UPDATE task_proposals SET launch_error=? WHERE id=?',
                           ('Task saved but runner did not start. Inspect it before explicitly starting again.', body['proposal_id']))
            result = {'workflow_id': value['id'], 'accepted': False,
                      'notice': 'Task saved but runner did not start. Inspect recent work.'}
        # Preferences contain suggestions, not approvals. Merge under a write transaction.
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT value FROM dashboard_settings WHERE key='task_preferences'").fetchone()
            saved = json.loads(row[0]) if row else {}
            saved[workflow['project_id']] = {'commands': payload['commands'], 'max_cost': workflow['budgets']['max_cost'],
                                           'max_call_cost': payload['max_call_cost'], 'max_tokens': workflow['budgets']['max_tokens']}
            db.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)', ('task_preferences', json.dumps(saved)))
        return result

    def message(self, body):
        allowed = {'project_id', 'provider', 'content', 'chat_id', 'confirmed', 'idempotency_key', 'max_output_tokens', 'model', 'effort'}
        if set(body) - allowed or body.get('confirmed') is not True:
            raise TaskPermissionError('Send explicitly authorizes this message and provider usage')
        key = identifier(body.get('idempotency_key'))
        project, provider, content = body.get('project_id'), body.get('provider'), body.get('content')
        self.store.project(project)
        if provider not in ('codex', 'claude', 'minimax'):
            raise TaskError('Choose a supported agent')
        safe_text(content)
        if not isinstance(content, str) or not content.strip() or len(content) > 16000:
            raise TaskError('Write a message of at most 16000 characters')
        maximum = body.get('max_output_tokens', 1024)
        if type(maximum) != int or not 16 <= maximum <= 2048:
            raise TaskError('Invalid response limit')
        from .providers import validate_chat_options
        try:
            options = validate_chat_options(provider, body.get('model'), body.get('effort'))
        except ValueError as error:
            raise TaskError(str(error))
        digest = _hash(body)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM task_conversations WHERE key=?', (key,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise TaskError('Submission identifier already used for another message')
                chat_id = old['chat_id']
            else:
                self.available([provider])
                chat_id = body.get('chat_id')
                if chat_id:
                    chat = db.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
                    if not chat or chat['project_id'] != project or chat['provider'] != provider:
                        raise TaskError('Conversation belongs to a different project or agent')
                else:
                    chat_id = str(uuid.uuid4())
                    db.execute('INSERT INTO chats(id,project_id,provider,title,status,updated_at) VALUES(?,?,?,?,?,?)',
                               (chat_id, project, provider, content.strip()[:80], 'IDLE', time.time()))
                db.execute('INSERT INTO task_conversations VALUES(?,?,?)', (key, digest, chat_id))
        result = self.app.chat.send(chat_id, {'content': content, 'confirmed': True,
                                            'max_output_tokens': maximum, 'timeout': 120, **options}, submission_key=key)
        preferences(self.store, {'project': project, 'agent': provider, 'conversation': chat_id})
        return dict(result, chat_id=chat_id)

    def submission(self, key):
        key = identifier(key)
        with self.store.connect() as db:
            row = db.execute('SELECT chat_id FROM task_conversations WHERE key=?', (key,)).fetchone()
            if row:
                submitted = db.execute('SELECT key FROM chat_submissions WHERE key=?', (key,)).fetchone()
                return {'chat_id': row['chat_id'], 'submitted': bool(submitted)}
            row = db.execute('SELECT workflow_id FROM task_proposals WHERE submission_key=?', (key,)).fetchone()
            return {'workflow_id': row['workflow_id']} if row else {'submitted': False}

    def results(self, workflow_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload,launch_error FROM task_proposals WHERE workflow_id=?', (workflow_id,)).fetchone()
        if not row:
            return {'notice': 'No task baseline recorded for this older workflow.', 'files': [], 'diff': ''}
        payload = json.loads(row['payload'])
        project = self.store.project(payload['workflow']['project_id'])
        before = payload.get('before', {})
        current = snapshot(project['path'], json.loads(project['exclusions']))
        old = {r[0]: tuple(r[1:]) for r in before.get('files', [])}
        new = {r[0]: tuple(r[1:]) for r in current['files']}
        exclusions = json.loads(project['exclusions'])
        changed = sorted(name for name in set(old) | set(new) if allowed(name, exclusions) and old.get(name) != new.get(name))
        diffs = []
        for name in changed[:100]:
            initial = before.get('texts', {}).get(name)
            if name not in old:
                initial = ''
            if initial is None:
                continue
            try:
                final = read_source(Path(project['path']), name, limit=65536).decode('utf-8') if name in new and new[name][0] == 'file' else ''
                if '\0' in final or sensitive_content(final):
                    continue
                lines = difflib.unified_diff(initial.splitlines(keepends=True), final.splitlines(keepends=True),
                                             fromfile='before/'+name, tofile='after/'+name)
                diffs.append(''.join(line if line.endswith('\n') else line+'\n\\ No newline at end of file\n'
                                     for line in lines))
            except (OSError, UnicodeError, ValueError, PermissionError):
                continue
        return {'files': changed, 'preexisting': [name for name in before.get('preexisting', []) if allowed(name, exclusions)], 'diff': ''.join(diffs)[:65536],
                'launch_error': row['launch_error'], 'notice': 'Changes since approved start, not proof of agent authorship. External edits may be included. Diffs are bounded; sensitive/binary/oversized files are omitted.'}
