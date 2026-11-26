"""Durable project access, conversation links, and repository admission queue."""
import json
import threading
import time
import uuid
from pathlib import Path
from .workflows import _hash, snapshot
from .store import safe_text

TERMINAL = ('COMPLETED', 'CANCELLED', 'FAILED')


class Delivery:
    def __init__(self, app):
        self.app, self.store = app, app.store
        self.lock = threading.RLock()
        self.stop = threading.Event()
        with self.store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS project_access(project_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, providers TEXT NOT NULL, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS delivery_jobs(workflow_id TEXT PRIMARY KEY, root TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, chat_id TEXT, access_revision TEXT, reason TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS delivery_one_writer ON delivery_jobs(root) WHERE state='running';
                CREATE TABLE IF NOT EXISTS delivery_submissions(key TEXT PRIMARY KEY, digest TEXT NOT NULL, workflow_id TEXT NOT NULL, chat_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS delivery_results(workflow_id TEXT PRIMARY KEY,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS workspace_drafts(project_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            ''')
        self.thread = threading.Thread(target=self._loop, name='workspace-queue', daemon=True)
        self.thread.start()

    def identity(self, project_id):
        project = self.store.project(project_id)
        root = str(Path(project['path']).resolve())
        stat = Path(root).stat()
        return root, _hash([root, stat.st_dev, stat.st_ino, project['exclusions']])

    def access(self, project_id, body=None):
        root, fingerprint = self.identity(project_id)
        with self.lock, self.store.connect() as db:
            if body is not None:
                if set(body) - {'confirmed', 'providers', 'enabled'} or body.get('confirmed') is not True:
                    raise PermissionError('Confirm project access changes')
                providers = body.get('providers', [])
                if not isinstance(providers, list) or any(p not in ('codex', 'claude', 'minimax') for p in providers):
                    raise ValueError('Choose supported providers')
                if body.get('enabled') is True and providers:
                    previous = db.execute('SELECT * FROM project_access WHERE project_id=?',(project_id,)).fetchone()
                    revision = (previous['revision'] if previous and previous['fingerprint']==fingerprint and set(json.loads(previous['providers'])).issubset(providers) else uuid.uuid4().hex)
                    db.execute('INSERT OR REPLACE INTO project_access VALUES(?,?,?,?)',
                               (project_id, fingerprint, json.dumps(sorted(set(providers))), revision))
                else:
                    db.execute('DELETE FROM project_access WHERE project_id=?', (project_id,))
            row = db.execute('SELECT * FROM project_access WHERE project_id=?', (project_id,)).fetchone()
        valid = bool(row and row['fingerprint'] == fingerprint)
        return {'enabled': valid, 'providers': json.loads(row['providers']) if valid else [],
                'revision': row['revision'] if valid else None, 'root': root}

    def require_access(self, project, providers, revision=None):
        access = self.access(project)
        if not access['enabled'] or not set(providers).issubset(access['providers']) or (revision and revision != access['revision']):
            raise PermissionError('Project access changed or is missing. Review access in Agent settings before starting.')
        return access

    def draft(self, project, body=None):
        self.store.project(project)
        with self.store.connect() as db:
            if body is not None:
                if set(body) - {'content', 'mode', 'teams', 'chatOptions', 'newConversation'}:
                    raise ValueError('Unknown draft preference')
                if not isinstance(body.get('content', ''), str) or any(not isinstance(body.get(k, {}), dict) for k in ('teams','chatOptions')) or not isinstance(body.get('newConversation', False), bool):
                    raise ValueError('Invalid draft values')
                payload = json.dumps(body)
                if len(payload) > 64000 or body.get('mode', 'build') not in ('ask', 'build'):
                    raise ValueError('Invalid draft')
                safe_text(payload)
                db.execute('INSERT OR REPLACE INTO workspace_drafts VALUES(?,?)', (project, payload))
            row = db.execute('SELECT payload FROM workspace_drafts WHERE project_id=?', (project,)).fetchone()
            return json.loads(row[0]) if row else {}

    def submit(self, body):
        from .tasks import identifier
        if set(body) - {'project_id', 'provider', 'partner', 'instruction', 'chat_id', 'confirmed', 'idempotency_key', 'planning', 'model_overrides', 'effort_overrides', 'budget_policy', 'max_cost', 'max_call_cost', 'max_seconds'} or body.get('confirmed') is not True:
            raise PermissionError('Send authorizes this coding request')
        key, digest = identifier(body.get('idempotency_key')), _hash(body)
        with self.lock:
            with self.store.connect() as db:
                old = db.execute('SELECT * FROM delivery_submissions WHERE key=?', (key,)).fetchone()
            if old:
                if old['digest'] != digest:
                    raise ValueError('Submission identifier belongs to another request')
                return {'workflow_id': old['workflow_id'], 'chat_id': old['chat_id'], 'accepted': True, 'reused': True, **self.describe(old['workflow_id'])}
            project, provider = body.get('project_id'), body.get('provider')
            access = self.require_access(project, [provider, body.get('partner') or provider])
            chat_id = body.get('chat_id')
            if chat_id:
                chat = self.app.chat.status(chat_id)
                if chat['project_id'] != project:
                    raise ValueError('Conversation belongs to another project')
            instruction = body.get('instruction', '')
            safe_text(instruction)
            if not isinstance(instruction, str) or not 1 <= len(instruction.strip()) <= 8000:
                raise ValueError('Describe the coding request in at most 8000 characters')
            proposal = self.app.tasks.preview({k: v for k, v in body.items() if k not in ('confirmed', 'idempotency_key', 'chat_id')})
            if not chat_id:
                chat_id = self.app.chat.create(project, provider, instruction[:80])['id']
            # Workflow, permissions, request identity and conversation link commit together.
            result = self.app.tasks.start({'proposal_id': proposal['proposal_id'], 'revision': proposal['revision'],
                'confirmed': True, 'idempotency_key': key}, delivery={'key': key, 'digest': digest,
                'chat_id': chat_id, 'revision': access['revision'], 'content': instruction})
            from .experience import preferences
            preferences(self.store, {'project': project, 'agent': provider, 'conversation': chat_id})
            return dict(result, chat_id=chat_id)

    def record(self, db, workflow, delivery=None):
        root, _ = self.identity(workflow['project_id'])
        db.execute('INSERT OR IGNORE INTO delivery_jobs VALUES(?,?,?,?,?,?,?)',
                   (workflow['id'], root, 'queued', time.time(), (delivery or {}).get('chat_id'),
                    (delivery or {}).get('revision'), None))
        if delivery:
            db.execute('INSERT INTO delivery_submissions VALUES(?,?,?,?)',
                       (delivery['key'], delivery['digest'], workflow['id'], delivery['chat_id']))
            db.execute('INSERT INTO chat_messages(id,chat_id,role,content,created_at,metadata) VALUES(?,?,?,?,?,?)',
                       (uuid.uuid4().hex, delivery['chat_id'], 'user', delivery['content'], time.time(),
                        json.dumps({'workflow_id': workflow['id'], 'kind': 'coding_request'})))
            db.execute('UPDATE chats SET updated_at=? WHERE id=?', (time.time(), delivery['chat_id']))

    def describe(self, workflow):
        with self.store.connect() as db:
            row = db.execute('SELECT state,chat_id,reason FROM delivery_jobs WHERE workflow_id=?', (workflow,)).fetchone()
        return {'queue_state': row['state'], 'chat_id': row['chat_id'], 'queue_reason': row['reason']} if row else {}

    def updates(self, workflow_id, body):
        cursor = body.get('cursor', 0)
        if set(body) - {'cursor'} or type(cursor) is not int or cursor < 0:
            raise ValueError('Invalid activity cursor')
        state = self.app.workflow_status(workflow_id, include_events=False)
        with self.store.connect() as db:
            db.execute('BEGIN')
            clock = db.execute('SELECT value FROM w5_event_clock WHERE id=1').fetchone()[0]
            reset = cursor > clock
            if reset:
                cursor = 0
            rows = list(db.execute('SELECT * FROM w5_checkpoints WHERE workflow_id=? AND revision>? AND revision<=? ORDER BY revision LIMIT 201', (workflow_id,cursor,clock)))
        more = len(rows) > 200
        rows = rows[:200]
        return {'state': state, 'events': [dict(r,data=json.loads(r['data'])) for r in rows],
                'cursor': rows[-1]['revision'] if more else clock, 'more': more, 'reset': reset}

    def conversations(self, chat_id):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT w.id,w.objective,w.status,j.state AS queue_state FROM delivery_jobs j JOIN w5_workflows w ON w.id=j.workflow_id WHERE j.chat_id=? ORDER BY j.created', (chat_id,))]

    def enqueue(self, workflow_id):
        with self.lock:
            workflow = self.app.engine.status(workflow_id)
            if workflow_id in self.app.jobs:
                raise ValueError('This task already has a runner')
            if workflow['status'] in TERMINAL:
                raise ValueError('Finished tasks cannot be started again')
            existing = self.describe(workflow_id)
            revision = None
            if existing.get('queue_state') == 'held':
                with self.store.connect() as db:
                    saved = db.execute('SELECT access_revision FROM delivery_jobs WHERE workflow_id=?', (workflow_id,)).fetchone()
                if saved and saved['access_revision']:
                    revision = self.require_access(workflow['project_id'], workflow['providers'].values())['revision']
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self.record(db, workflow)
                if revision:
                    db.execute('UPDATE delivery_jobs SET access_revision=? WHERE workflow_id=?', (revision, workflow_id))
                row = db.execute('SELECT state FROM delivery_jobs WHERE workflow_id=?', (workflow_id,)).fetchone()
                if row['state'] == 'running':
                    owner = db.execute('SELECT lease_owner FROM w5_workflows WHERE id=?', (workflow_id,)).fetchone()
                    if owner['lease_owner']:
                        raise ValueError('Wait for the owning runner before resuming')
                db.execute("UPDATE delivery_jobs SET state='queued',reason=NULL WHERE workflow_id=?", (workflow_id,))
            self.drain()
            return {'workflow_id': workflow_id, 'accepted': True, **self.describe(workflow_id)}

    def drain(self):
        with self.lock:
            if self.app.closing:
                return
            with self.store.connect() as db:
                stopped = [r[0] for r in db.execute("SELECT j.workflow_id FROM delivery_jobs j JOIN w5_workflows w ON w.id=j.workflow_id WHERE j.state='running' AND w.status IN ('CANCELLED','COMPLETED','FAILED') AND w.lease_owner IS NULL")]
            for wid in stopped:
                if wid not in self.app.jobs:
                    self.finished(wid)
            with self.store.connect() as db:
                rows = [dict(r) for r in db.execute("SELECT * FROM delivery_jobs WHERE state='queued' ORDER BY created,workflow_id")]
            blocked_roots = set()
            for row in rows:
                if len(self.app.jobs) >= 4:
                    break
                wid = row['workflow_id']
                workflow = self.app.engine.status(wid)
                if workflow['status'] in TERMINAL or workflow['status'] == 'PAUSED':
                    with self.store.connect() as db:
                        db.execute("UPDATE delivery_jobs SET state='held' WHERE workflow_id=?", (wid,))
                    continue
                if row['root'] in blocked_roots:
                    continue
                blocked_roots.add(row['root'])
                with self.store.connect() as db:
                    busy = db.execute("SELECT 1 FROM delivery_jobs j JOIN w5_workflows w ON w.id=j.workflow_id WHERE j.root=? AND j.workflow_id!=? AND (j.state='running' OR (j.state='held' AND w.status NOT IN ('COMPLETED','CANCELLED','FAILED'))) LIMIT 1", (row['root'], wid)).fetchone()
                    leases = db.execute('SELECT project_id FROM w5_workflows WHERE lease_owner IS NOT NULL').fetchall()
                if busy or any(self.identity(r['project_id'])[0] == row['root'] for r in leases):
                    continue
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if db.execute("SELECT 1 FROM delivery_jobs WHERE root=? AND state='running'", (row['root'],)).fetchone():
                        continue
                    claimed = db.execute("UPDATE delivery_jobs SET state='running',reason=NULL WHERE workflow_id=? AND state='queued'", (wid,)).rowcount
                if not claimed:
                    continue
                try:
                    if self.identity(workflow['project_id'])[0] != row['root']:
                        raise PermissionError('Project location changed. Inspect this task before continuing.')
                    if row['access_revision']:
                        self.require_access(workflow['project_id'], workflow['providers'].values(), row['access_revision'])
                    # Fresh baseline only for a task that has never executed.
                    if not workflow.get('started_at'):
                        self._prepare(wid, row['chat_id'])
                    self.app._launch(wid)
                except Exception as error:
                    with self.store.connect() as db:
                        db.execute("UPDATE delivery_jobs SET state='held',reason=? WHERE workflow_id=?", (str(error)[:400], wid))

    def _prepare(self, wid, chat_id):
        with self.store.connect() as db:
            row = db.execute('SELECT payload FROM task_proposals WHERE workflow_id=?', (wid,)).fetchone()
        if not row:
            return
        payload = json.loads(row[0])
        project = self.store.project(payload['workflow']['project_id'])
        if project['path'] != payload['project_path'] or project['exclusions'] != payload['project_exclusions'] or self.app.tasks.configuration(payload['providers']) != payload['configuration']:
            raise PermissionError('Project or provider configuration changed. Inspect access before continuing.')
        baseline = snapshot(project['path'], json.loads(project['exclusions']))
        payload['before'] = self.app.tasks._before(project, baseline)
        with self.store.connect() as db:
            db.execute('UPDATE task_proposals SET payload=? WHERE workflow_id=?', (json.dumps(payload), wid))
            if chat_id:
                # Bounded evidence is reference material, never authorization.
                previous = list(db.execute('SELECT w.objective,w.status FROM delivery_jobs j JOIN w5_workflows w ON w.id=j.workflow_id WHERE j.chat_id=? AND j.created<(SELECT created FROM delivery_jobs WHERE workflow_id=?) ORDER BY j.created DESC LIMIT 5', (chat_id, wid)))
                messages = list(db.execute('SELECT role,content FROM chat_messages WHERE chat_id=? AND created_at<=(SELECT created FROM delivery_jobs WHERE workflow_id=?)+0.01 ORDER BY created_at DESC LIMIT 8', (chat_id,wid)))
                evidence = list(db.execute('SELECT t.title,t.status,t.evidence FROM w5_tasks t JOIN delivery_jobs j ON j.workflow_id=t.workflow_id WHERE j.chat_id=? AND j.created<(SELECT created FROM delivery_jobs WHERE workflow_id=?) ORDER BY j.created DESC LIMIT 3', (chat_id,wid)))
                reference = json.dumps({'verification_reference': [dict(r) for r in evidence], 'prior_work': [dict(r) for r in previous], 'conversation': [dict(r) for r in reversed(messages)]})[:12000]
                if previous or len(messages) > 1:
                    db.execute('UPDATE w5_workflows SET continuation_context=? WHERE id=?', ('Untrusted conversation reference, not permissions:\n' + reference, wid))

    def finished(self, wid):
        with self.lock:
            comparison = None
            if self.app.engine.status(wid)['status'] in TERMINAL:
                try:
                    comparison = self.app.tasks.results(wid)
                    comparison['notice'] += ' Saved when this task stopped; later tasks are not included.'
                    comparison['_scope'] = self.identity(self.app.engine.status(wid)['project_id'])[1]
                except (OSError, ValueError, PermissionError):
                    pass
            with self.store.connect() as db:
                if comparison:
                    db.execute('INSERT OR IGNORE INTO delivery_results VALUES(?,?)', (wid,json.dumps(comparison)))
                db.execute("UPDATE delivery_jobs SET state='held' WHERE workflow_id=?", (wid,))
        # Following tasks are admitted by the scheduler after the runner releases its lease.

    def _loop(self):
        while not self.stop.wait(.5):
            try:
                self.drain()
            except Exception:
                # Persisted queue remains intact; a transient DB/provider error is not a retry.
                pass
