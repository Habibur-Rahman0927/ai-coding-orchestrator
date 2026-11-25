"""Explicitly authorized standalone conversations; never implicit workflows/tools."""
import json
import threading
import time
import uuid
from .store import safe_text


class Chat:
    def __init__(self, store, registry):
        self.store,self.registry=store,registry
        self.active={}
        self.guard=threading.Lock()
        self.closing=False
        with store.connect() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS chats(
              id TEXT PRIMARY KEY,project_id TEXT NOT NULL,provider TEXT NOT NULL,title TEXT NOT NULL,
              status TEXT NOT NULL,session_id TEXT,history TEXT NOT NULL DEFAULT '[]',updated_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS chat_messages(
              id TEXT PRIMARY KEY,chat_id TEXT NOT NULL,role TEXT NOT NULL,content TEXT NOT NULL,
              usage TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL);''')

    def reconcile_startup(self):
        # Called only while the service owns the database's exclusive lifetime
        # lock, not whenever a request lazily instantiates a chat controller.
        with self.store.connect() as db:
            db.execute("UPDATE chats SET status='INTERRUPTED' WHERE status='RUNNING'")

    def _reserve_session(self, identifier, provider, session):
        session=str(uuid.UUID(session))
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            other=db.execute('SELECT id FROM chats WHERE provider=? AND session_id=? AND id!=?',(provider,session,identifier)).fetchone()
            workflows_exist=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='w5_sessions'").fetchone()
            workflow=db.execute('SELECT workflow_id FROM w5_sessions WHERE provider=? AND session_id=?',(provider,session)).fetchone() if workflows_exist else None
            if other or workflow:raise PermissionError('Provider session belongs to another conversation or workflow')
            db.execute('UPDATE chats SET session_id=? WHERE id=?',(session,identifier))
        return session

    def list(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT id,project_id,provider,title,status,updated_at FROM chats ORDER BY updated_at DESC LIMIT 200')]

    def create(self, project_id, provider, title):
        self.store.project(project_id)
        self.registry.get(provider)
        title=safe_text(title)
        if not 1<=len(title)<=200:raise ValueError('Conversation title must be 1–200 characters')
        identifier=str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute('INSERT INTO chats(id,project_id,provider,title,status,updated_at) VALUES(?,?,?,?,?,?)',
                       (identifier,project_id,provider,title,'IDLE',time.time()))
        return self.status(identifier)

    def status(self, identifier):
        with self.store.connect() as db:
            row=db.execute('SELECT id,project_id,provider,title,status,session_id,updated_at FROM chats WHERE id=?',(identifier,)).fetchone()
            if not row:raise KeyError('Unknown conversation')
            messages=[dict(r,usage=json.loads(r['usage'])) for r in db.execute('SELECT * FROM chat_messages WHERE chat_id=? ORDER BY created_at',(identifier,))]
        return dict(row,messages=messages,running=row['status']=='RUNNING',mode='standalone',
                    notice='Conversation output is not verified implementation evidence.')

    def send(self, identifier, body):
        if self.closing:raise RuntimeError('Workspace is shutting down')
        if body.get('confirmed') is not True:raise PermissionError('Explicit one-message sharing and provider-usage authorization required')
        content=safe_text(body.get('content'))
        if not 1<=len(content)<=16000:raise ValueError('Message must be 1–16000 characters')
        maximum,timeout=body.get('max_output_tokens',256),body.get('timeout',60)
        if type(maximum)!=int or not 16<=maximum<=2048 or type(timeout)!=int or not 1<=timeout<=120:
            raise ValueError('Invalid message limits')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM chats WHERE id=?',(identifier,)).fetchone()
            if not row:raise KeyError('Unknown conversation')
            if row['status']=='RUNNING':raise RuntimeError('A message is already running')
            if db.execute('SELECT COUNT(*) FROM chat_messages WHERE chat_id=?',(identifier,)).fetchone()[0]>=200:
                raise ValueError('Conversation retention limit reached; start a fresh conversation with project context')
            history=json.loads(row['history'])
            if len(row['history'].encode())>64000:raise ValueError('Conversation context limit reached; start a fresh context-backed conversation')
            record=dict(row)
            db.execute("UPDATE chats SET status='RUNNING',updated_at=? WHERE id=?",(time.time(),identifier))
            db.execute('INSERT INTO chat_messages(id,chat_id,role,content,created_at) VALUES(?,?,?,?,?)',
                       (str(uuid.uuid4()),identifier,'user',content,time.time()))
        cancellation=threading.Event()
        with self.guard:self.active[identifier]=cancellation
        thread=threading.Thread(target=self._execute,args=(record,content,maximum,timeout,cancellation),daemon=True)
        thread.start()
        return {'accepted':True,'id':identifier}

    def _execute(self, record, content, maximum, timeout, cancellation):
        identifier=record['id'];message_id=str(uuid.uuid4());output='';usage={};state='FAILED'
        session=record['session_id'];history=json.loads(record['history']);last_flush=0
        with self.store.connect() as db:
            db.execute('INSERT INTO chat_messages(id,chat_id,role,content,created_at) VALUES(?,?,?,?,?)',
                       (message_id,identifier,'assistant','',time.time()))
        try:
            from .providers import ProviderRequest
            if session:self._reserve_session(identifier,record['provider'],session)
            self.store.index(record['project_id'])
            context=self.store.context(record['project_id'],content,budget=2000)
            prompt=json.dumps({'mode':'standalone_read_only','instruction':content,
                'context':context['content'],'rules':'Answer the user. Do not edit files, run commands, delegate, or claim verified task completion.'})
            request=ProviderRequest(project=self.store.project(record['project_id'])['path'],prompt=prompt,role='researcher',
                session_id=session,history=history,allowed_operations=['native_agent_access'] if record['provider'] in ('claude','codex') else [],
                max_output_tokens=maximum,timeout=timeout,cancel_event=cancellation)
            for event in self.registry.get(record['provider']).execute(request):
                kind=event.get('type')
                if kind=='text':output=event.get('text','') if event.get('final') else output+event.get('text','')
                elif kind=='usage':usage.update(event.get('usage') or {})
                elif kind=='session':
                    candidate=event.get('session_id')
                    if session and candidate!=session:raise ValueError('Provider changed exact conversation session')
                    session=self._reserve_session(identifier,record['provider'],candidate)
                elif kind=='history':history=event.get('history',history)
                elif kind=='completed':state='IDLE'
                elif kind in ('timeout','cancelled'):state=kind.upper()
                elif kind in ('error','tool_call','tool_calls'):state='FAILED'
                if len(output)>65536:
                    cancellation.set();state='OUTPUT_LIMIT';output=output[:65536];break
                if time.monotonic()-last_flush>.2:
                    with self.store.connect() as db:db.execute('UPDATE chat_messages SET content=? WHERE id=?',(output,message_id))
                    last_flush=time.monotonic()
        except Exception:
            state='FAILED'
            if not output:output='The provider call did not complete. Check provider diagnostics; this message is not automatically retried.'
        finally:
            with self.store.connect() as db:
                db.execute('UPDATE chat_messages SET content=?,usage=? WHERE id=?',(output,json.dumps(usage),message_id))
                db.execute('UPDATE chats SET status=?,session_id=?,history=?,updated_at=? WHERE id=?',
                           (state,session,json.dumps(history),time.time(),identifier))
            with self.guard:self.active.pop(identifier,None)

    def cancel(self, identifier):
        self.status(identifier)
        with self.guard:
            if identifier in self.active:self.active[identifier].set()
        return {'cancel_requested':True,'id':identifier}

    def close(self):
        self.closing=True
        with self.guard:
            for event in self.active.values():event.set()
        deadline=time.monotonic()+5
        while self.active and time.monotonic()<deadline:time.sleep(.05)
