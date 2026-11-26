"""Scoped durable knowledge and incremental local retrieval. Python 3.8+."""
import ast
import contextlib
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import time
import uuid
import ccx_platform as native

SCOPES = {'global','project','workflow','session','error','verification','skills','temporary'}
KINDS = {'observed','user_instruction','hypothesis','verified'}
DENIED = {'.git','.ssh','.aws','.codex','.claude','node_modules','vendor','dist','build','__pycache__','.venv','venv','Library','AppData'}
SECRET_NAMES = ('*.pem','*.key','*.p12','*.pfx','id_rsa*','id_ed25519*','.env*','*credentials*','*secret*','auth.json','config.toml','*.sqlite*','*.db','*.log','*.jsonl')
from .security import SECRET_CONTENT as SECRET, read_regular_bytes

def ident(): return str(uuid.uuid4())
def digest(data): return hashlib.sha256(data).hexdigest()
def stamp(): return time.time()
def safe_text(text):
    if not isinstance(text,str) or '\x00' in text or SECRET.search(text):
        raise ValueError('Sensitive or invalid content refused')
    return text

def allowed(relative, exclusions=()):
    p=Path(relative)
    return (not p.is_absolute() and '..' not in p.parts and not any(x.casefold() in {part.casefold() for part in DENIED} for x in p.parts)
            and not any(fnmatch.fnmatch(x.lower(),pat) for x in p.parts for pat in SECRET_NAMES)
            and not any(fnmatch.fnmatch(p.as_posix(),pat) for pat in exclusions))

def file_path(root, relative):
    root=Path(root)
    if native.is_link(root): raise PermissionError('Project root replaced by a link/reparse point')
    native.validate_permissions(root,mask=0o002)
    rel=native.validate_relative(relative)
    if not allowed(rel): raise PermissionError('Excluded source')
    candidate=root
    for part in rel.parts:
        candidate=candidate/part
        if native.is_link(candidate): raise PermissionError('Link/reparse source refused')
        if candidate.exists():
            native.validate_permissions(candidate,mask=0o002)
            if candidate.is_file() and candidate.stat().st_nlink!=1: raise PermissionError('Hard-linked source refused')
    if root not in candidate.resolve().parents: raise PermissionError('Outside project')
    return candidate

def git_ignored(root,relative):
    result=subprocess.run(['git','-C',str(root),'check-ignore','--quiet','--no-index','--',str(relative)],capture_output=True,timeout=10)
    if result.returncode not in (0,1): raise PermissionError('Git exclusion policy unavailable')
    return result.returncode==0

def ignored_paths(root, names):
    """One fresh Git policy check per candidate batch; no cross-request cache."""
    if not names: return set()
    result=subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--stdin','-z'],
        input=b'\0'.join(os.fsencode(name) for name in names)+b'\0',capture_output=True,timeout=30)
    if result.returncode not in (0,1): raise PermissionError('Git exclusion policy unavailable')
    return {os.fsdecode(name) for name in result.stdout.split(b'\0') if name}


def read_source(root,relative,limit=256000):
    path=file_path(root,relative)
    return read_regular_bytes(path, limit)

class Store:
    def __init__(self,path):
        self.path=Path(path).absolute()
        for p in (self.path,)+tuple(self.path.parents):
            if native.is_link(p): raise PermissionError('Database path contains link/reparse point')
        native.secure_mkdir(self.path.parent,parents=True,exist_ok=True)
        native.validate_permissions(self.path.parent)
        if self.path.exists(): native.validate_permissions(self.path)
        with self.connect() as db:
            # Reject future/incomplete version metadata before any schema writes.
            # A failed initialization must roll back its DDL along with its data.
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_versions'").fetchone():
                version=db.execute("SELECT version FROM schema_versions WHERE component='knowledge'").fetchone()
                if version is None or version[0]!=1: raise ValueError('Unsupported knowledge database version')
            db.executescript('''
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS schema_versions(component TEXT PRIMARY KEY,version INTEGER NOT NULL);
            INSERT OR IGNORE INTO schema_versions VALUES('knowledge',1);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,created_at REAL NOT NULL,exclusions TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY,project_id TEXT,scope TEXT NOT NULL,kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,source TEXT,source_hash TEXT,created_at REAL NOT NULL,verified_at REAL,confidence REAL,expires_at REAL,supersedes TEXT,version INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS memory_scope ON memory(project_id,scope);
            CREATE TABLE IF NOT EXISTS documents(project_id TEXT NOT NULL,path TEXT NOT NULL,hash TEXT NOT NULL,signature TEXT NOT NULL,body TEXT NOT NULL,symbols TEXT NOT NULL,dependencies TEXT NOT NULL,indexed_at REAL NOT NULL,PRIMARY KEY(project_id,path));
            CREATE TABLE IF NOT EXISTS knowledge_audit(id INTEGER PRIMARY KEY,event TEXT NOT NULL,project_id TEXT,details TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS context_packages(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,query TEXT NOT NULL,content TEXT NOT NULL,metrics TEXT NOT NULL,created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS knowledge_index_state(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS machine_snapshot(id INTEGER PRIMARY KEY CHECK(id=1),content TEXT NOT NULL,collected_at REAL NOT NULL);
            ''')
            version=db.execute("SELECT version FROM schema_versions WHERE component='knowledge'").fetchone()[0]
            if version != 1: raise ValueError('Unsupported knowledge database version')
            try:
                had_search=bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='document_search'").fetchone())
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS document_search USING fts5(project_id UNINDEXED,path UNINDEXED,body)')
                dirty=db.execute("SELECT value FROM knowledge_index_state WHERE key='fts_dirty'").fetchone()
                if not had_search or (dirty and dirty[0]):
                    db.execute('DELETE FROM document_search')
                    db.execute('INSERT INTO document_search(project_id,path,body) SELECT project_id,path,body FROM documents')
                    db.execute("INSERT OR REPLACE INTO knowledge_index_state VALUES('fts_dirty',0)")
                self.fts=True
            except sqlite3.OperationalError as error:
                if str(error).strip().lower()!='no such module: fts5': raise
                self.fts=False
        native.secure_mode(self.path,0o600)

    @contextlib.contextmanager
    def connect(self):
        for p in (self.path,)+tuple(self.path.parents):
            if native.is_link(p): raise PermissionError('Database path replaced by link/reparse point')
        native.validate_permissions(self.path.parent)
        for p in (self.path,Path(str(self.path)+'-journal'),Path(str(self.path)+'-wal'),Path(str(self.path)+'-shm')):
            if native.is_link(p): raise PermissionError('Unsafe SQLite sidecar path')
            if p.exists():
                try:
                    native.validate_permissions(p)
                    info = p.lstat()
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise PermissionError('Unsafe SQLite file')
                except FileNotFoundError:
                    # SQLite removes transient sidecars when another connection commits.
                    # The database itself must never disappear during validation.
                    if p == self.path:
                        raise
        db=sqlite3.connect(str(self.path),timeout=15)
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally: db.close()

    def audit(self,event,project_id=None,details=None):
        with self.connect() as db:
            db.execute('INSERT INTO knowledge_audit(event,project_id,details,created_at) VALUES(?,?,?,?)',
                       (event,project_id,json.dumps(details or {}),stamp()))

    def register(self,path,exclusions=()):
        if not isinstance(exclusions,(list,tuple)) or len(exclusions)>100 or any(not isinstance(x,str) or len(x)>256 for x in exclusions):
            raise ValueError('Exclusions must be a bounded list of path patterns')
        original=Path(path).absolute()
        if native.is_link(original): raise PermissionError('Project root is a link/reparse point')
        root=original.resolve()
        native.validate_owner(root)
        result=subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'],capture_output=True,text=True,timeout=10)
        if result.returncode or Path(result.stdout.strip()).resolve()!=root:
            raise ValueError('Register an explicit Git repository root')
        if root == Path.home().resolve(): raise ValueError('A whole home directory cannot be registered')
        pid=digest(str(root).encode())[:16]
        with self.connect() as db:
            db.execute('INSERT INTO projects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET exclusions=excluded.exclusions',(pid,str(root),stamp(),json.dumps(list(exclusions))))
        self.audit('project_registered',pid)
        return self.project(pid)

    def project(self,pid):
        with self.connect() as db: row=db.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
        if row is None: raise KeyError('Unregistered project')
        return dict(row)

    def projects(self):
        with self.connect() as db: return [dict(r) for r in db.execute('SELECT * FROM projects ORDER BY path')]

    def add_memory(self,project_id,scope,title,body,kind='hypothesis',source=None,source_hash=None,confidence=.5,expires_at=None,supersedes=None,verified_at=None):
        if scope not in SCOPES or kind not in KINDS: raise ValueError('Invalid memory scope or evidence kind')
        if scope=='global' and project_id is not None: raise ValueError('Global scope requires no project')
        if scope!='global': self.project(project_id)
        if kind=='verified' and (not source or not verified_at): raise ValueError('Verified memory requires evidence and verification time')
        safe_text(title);safe_text(body)
        if len(title)>1000: raise ValueError('Memory title too large')
        if source is not None:
            safe_text(source)
            if len(source)>4000: raise ValueError('Memory source too large')
        if source_hash is not None and (not isinstance(source_hash,str) or not re.fullmatch(r'[0-9a-f]{64}',source_hash)):
            raise ValueError('Invalid memory source hash')
        if len(body.encode())>256000: raise ValueError('Memory too large')
        if not 0<=confidence<=1: raise ValueError('Invalid confidence')
        mid=ident()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if supersedes:
                prior=db.execute('SELECT project_id,scope FROM memory WHERE id=?',(supersedes,)).fetchone()
                if not prior or prior['project_id']!=project_id or prior['scope']!=scope: raise ValueError('Supersession outside scope')
            # Exact identity includes evidence and lifecycle fields. Never merge
            # hypotheses with verified facts, renew expiry, or revive history.
            prior=db.execute("""SELECT id FROM memory m WHERE project_id IS ? AND scope=? AND kind=?
                AND title=? AND body=? AND source IS ? AND source_hash IS ? AND confidence IS ?
                AND expires_at IS ? AND supersedes IS ? AND verified_at IS ?
                AND (expires_at IS NULL OR expires_at>?)
                AND NOT EXISTS(SELECT 1 FROM memory n WHERE n.supersedes=m.id)
                ORDER BY created_at,id LIMIT 1""",
                (project_id,scope,kind,title,body,source,source_hash,confidence,expires_at,supersedes,verified_at,stamp())).fetchone()
            if prior:
                return {'id':prior['id'],'project_id':project_id,'scope':scope,'kind':kind,'reused':True}
            db.execute('INSERT INTO memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(mid,project_id,scope,kind,title,body,source,source_hash,stamp(),verified_at,confidence,expires_at,supersedes,1))
        self.audit('memory_added',project_id,{'id':mid,'scope':scope,'kind':kind})
        return {'id':mid,'project_id':project_id,'scope':scope,'kind':kind}

    def memories(self,project_id):
        if project_id is not None: self.project(project_id)
        with self.connect() as db:
            rows=db.execute('SELECT * FROM memory m WHERE project_id IS ? AND (expires_at IS NULL OR expires_at>?) AND NOT EXISTS(SELECT 1 FROM memory n WHERE n.supersedes=m.id) ORDER BY created_at DESC',(project_id,stamp())).fetchall()
        return [dict(r) for r in rows]

    def delete_memory(self,mid,project_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record=db.execute('SELECT supersedes,scope FROM memory WHERE id=? AND project_id IS ?',(mid,project_id)).fetchone()
            if record is None: raise KeyError('Memory not in selected scope')
            # Deleting a replacement must not silently reactivate its predecessor.
            # Retain that historical record while permanently excluding it from
            # current retrieval, including databases created before this policy.
            if record['supersedes']:
                db.execute('UPDATE memory SET expires_at=MIN(COALESCE(expires_at,0),0) WHERE id=? AND project_id IS ? AND scope=?',
                           (record['supersedes'],project_id,record['scope']))
            db.execute('DELETE FROM memory WHERE id=? AND project_id IS ?',(mid,project_id))
        self.audit('memory_deleted',project_id,{'id':mid})
        return {'deleted':mid}

    def export_memory(self,project_id): return {'project_id':project_id,'records':self.memories(project_id)}

    def index(self,pid):
        project=self.project(pid);root=Path(project['path']);exclusions=json.loads(project['exclusions'])
        result=subprocess.run(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'],capture_output=True,timeout=30)
        if result.returncode: raise ValueError('Git discovery failed')
        names=sorted(set(os.fsdecode(p) for p in result.stdout.split(b'\0') if p))
        if len(names)>50000: raise ValueError('Project discovery exceeds bounded file count')
        ignore_result=subprocess.run(['git','-C',str(root),'check-ignore','--no-index','--stdin','-z'],
            input=b'\0'.join(os.fsencode(name) for name in names)+(b'\0' if names else b''),capture_output=True,timeout=30)
        if ignore_result.returncode not in (0,1): raise PermissionError('Git exclusion policy unavailable')
        ignored={os.fsdecode(name) for name in ignore_result.stdout.split(b'\0') if name}
        started=time.monotonic();updated=unchanged=excluded=0;seen=set();total=0
        with self.connect() as db:
            if not self.fts:
                db.execute("INSERT OR REPLACE INTO knowledge_index_state VALUES('fts_dirty',1)")
            for name in names:
                if name in ignored or not allowed(name,exclusions): excluded+=1;continue
                try:
                    path=file_path(root,name)
                    if not path.is_file(): continue
                    st=path.stat()
                    if st.st_size>256000: excluded+=1;continue
                    signature=json.dumps([st.st_size,st.st_mtime_ns,st.st_ctime_ns,st.st_ino])
                    old=db.execute('SELECT signature,hash FROM documents WHERE project_id=? AND path=?',(pid,name)).fetchone()
                    seen.add(name)
                    if old and old[0]==signature: unchanged+=1;continue
                    if total+st.st_size>64*1024*1024: raise RuntimeError('Index byte budget exceeded')
                    raw=read_source(root,name);total+=len(raw)
                    if b'\0' in raw: raise UnicodeError()
                    body=raw.decode('utf-8');safe_text(body)
                except (OSError,UnicodeError,ValueError): excluded+=1;seen.discard(name);continue
                content_hash=digest(raw)
                if old and old['hash']==content_hash:
                    db.execute('UPDATE documents SET signature=? WHERE project_id=? AND path=?',(signature,pid,name))
                    unchanged+=1
                    continue
                symbols=[];dependencies=[]
                if path.suffix=='.py':
                    try:
                        tree=ast.parse(body)
                        for n in ast.walk(tree):
                            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)): symbols.append({'name':n.name,'line':n.lineno})
                            if isinstance(n,ast.Import): dependencies.extend(a.name for a in n.names)
                            if isinstance(n,ast.ImportFrom) and n.module: dependencies.append(n.module)
                    except SyntaxError: pass
                db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?,?,?,?,?)',(pid,name,content_hash,signature,body,json.dumps(symbols),json.dumps(sorted(set(dependencies))),stamp()))
                if self.fts:
                    db.execute('DELETE FROM document_search WHERE project_id=? AND path=?',(pid,name))
                    db.execute('INSERT INTO document_search VALUES(?,?,?)',(pid,name,body))
                updated+=1
            existing=[r[0] for r in db.execute('SELECT path FROM documents WHERE project_id=?',(pid,))]
            deleted=0
            for name in existing:
                if name not in seen:
                    db.execute('DELETE FROM documents WHERE project_id=? AND path=?',(pid,name))
                    if self.fts: db.execute('DELETE FROM document_search WHERE project_id=? AND path=?',(pid,name))
                    deleted+=1
        result={'project_id':pid,'updated':updated,'unchanged':unchanged,'deleted':deleted,'excluded':excluded,'bytes_read':total,'duration_ms':round((time.monotonic()-started)*1000,3)}
        self.audit('project_indexed',pid,result)
        return result

    def search(self,pid,query,scope=None,limit=10):
        project=self.project(pid);safe_text(query)
        if not 1<=int(limit)<=100: raise ValueError('Invalid search limit')
        terms=list(dict.fromkeys(re.findall(r'\w+',query.lower())))[:16];results=[]
        for record in self.memories(pid):
            if scope and record['scope']!=scope: continue
            matched=[t for t in terms if t in (record['title']+' '+record['body']).lower()]
            if matched or not terms:
                record.update(score=len(matched),record_type='memory',stale=False,
                              retrieval_reason={'matched_terms':matched,'method':'memory_keywords'})
                if record['source'] and record['source_hash']:
                    try: record['stale']=self._source_stale(pid,record['source'],record['source_hash'])
                    except (OSError,ValueError): record['stale']=True
                results.append(record)
        if scope is None:
            with self.connect() as db:
                candidates={}
                if self.fts and terms:
                    match=' OR '.join('"'+t+'"' for t in terms)
                    rows=db.execute('SELECT d.* FROM document_search JOIN documents d ON document_search.project_id=d.project_id AND document_search.path=d.path WHERE d.project_id=? AND document_search MATCH ? ORDER BY bm25(document_search),d.path LIMIT 100',(pid,match)).fetchall()
                    candidates.update((r['path'],dict(r)) for r in rows)
                # Paths and parsed symbols are evidence too. Rank before bounding
                # candidates, including SQLite builds without optional FTS5.
                fields="lower(path || ' ' || symbols || ' ' || dependencies" + (" || ' ' || body)" if not self.fts else ")")
                score=' + '.join('(instr('+fields+',?)>0)' for _ in terms) or '1'
                rows=db.execute('SELECT *,('+score+') AS metadata_score FROM documents WHERE project_id=? ORDER BY metadata_score DESC,path LIMIT 100',tuple(terms)+(pid,)).fetchall()
                candidates.update((r['path'],dict(r)) for r in rows if r['metadata_score'] or not terms)
            root=Path(project['path']);exclusions=json.loads(project['exclusions'])
            permitted=[r for r in candidates.values() if allowed(r['path'],exclusions)]
            ignored=ignored_paths(root,[r['path'] for r in permitted])
            for item in permitted:
                if item['path'] in ignored: continue
                body=item['body'].lower();name=item['path'].lower()
                matched=[t for t in terms if t in body or t in name]
                symbols=[x['name'].lower() for x in json.loads(item['symbols'])]
                symbol_hits=[x for x in symbols if x in terms]
                exact_path=bool(re.search(r'(?<![\w./-])'+re.escape(name)+r'(?![\w./-])',query.lower()))
                if terms and not matched and not symbol_hits: continue
                score=len(matched)+12*len(symbol_hits)+(20 if exact_path else 0)
                try: stale=digest(read_source(root,item['path']))!=item['hash']
                except (OSError,ValueError): stale=True
                item.update(score=score,record_type='file',source=item['path'],source_hash=item['hash'],stale=stale,
                            retrieval_reason={'matched_terms':matched,'symbols':symbol_hits,'exact_path':exact_path,'method':'fts_and_metadata' if self.fts else 'keyword_and_metadata'})
                results.append(item)
        return sorted(results,key=lambda r:(-r['score'],str(r.get('source') or r.get('id'))))[:int(limit)]

    def _source_stale(self,pid,source,source_hash):
        project=self.project(pid)
        if not source.startswith('workflow:'):
            if not allowed(source,json.loads(project['exclusions'])) or git_ignored(Path(project['path']),source): return True
            return digest(read_source(Path(project['path']),source))!=source_hash
        try:
            workflow_id=str(uuid.UUID(source.split(':',1)[1]))
            with self.connect() as db:
                workflow=db.execute('SELECT project_id,status FROM w5_workflows WHERE id=?',(workflow_id,)).fetchone()
                if not workflow or workflow['project_id']!=pid or workflow['status']!='COMPLETED': return True
                tasks=db.execute('SELECT id,status,evidence FROM w5_tasks WHERE workflow_id=?',(workflow_id,)).fetchall()
                if not tasks: return True
                for task in tasks:
                    evidence=json.loads(task['evidence']);review=evidence.get('review',{});tests=evidence.get('tests',{})
                    if task['status']!='VERIFIED' or review.get('decision')!='approve' or review.get('snapshot_hash')!=source_hash:
                        return True
                    if not tests.get('passed') or tests.get('snapshot_hash')!=source_hash or tests.get('after_hash')!=source_hash:
                        return True
                    commands=tests.get('commands',[])
                    if not commands or any(c.get('exit_code')!=0 for c in commands): return True
                    action=db.execute('SELECT role,workflow_id,task_id,after_hash FROM w5_actions WHERE id=?',(review.get('action_id'),)).fetchone()
                    if not action or action['role']!='reviewer' or action['workflow_id']!=workflow_id or action['task_id']!=task['id'] or action['after_hash']!=source_hash:
                        return True
            from .workflows import snapshot
            return snapshot(Path(project['path']),json.loads(project['exclusions']))['hash']!=source_hash
        except (sqlite3.Error,ValueError,TypeError,KeyError,OSError):
            return True

    def context(self,pid,query,budget=2000,critical=None,role=None):
        if not 64<=int(budget)<=1000000: raise ValueError('Invalid context budget')
        if role not in (None,'planner','executor','reviewer','correction'): raise ValueError('Invalid context role')
        critical=list(dict.fromkeys(critical or []));prefix='\n'.join(safe_text(x) for x in critical)
        capacity=int(budget)*4
        if len(prefix.encode())>capacity: raise ValueError('Critical requirements exceed context budget; increase budget explicitly')
        chunks=[prefix] if prefix else [];seen=set();refs=[];excluded=[]
        candidates=self.search(pid,query,limit=100)
        # Root instructions are untrusted references, not permission grants. Keep
        # them visible even when their prose does not match the task's keywords.
        project=self.project(pid);root=Path(project['path']);exclusions=json.loads(project['exclusions'])
        for name in reversed(('AGENTS.md','CLAUDE.md')):
            if not allowed(name,exclusions) or git_ignored(root,name): continue
            with self.connect() as db:
                row=db.execute('SELECT * FROM documents WHERE project_id=? AND path=?',(pid,name)).fetchone()
            if row and not any(r.get('source')==name for r in candidates):
                try:
                    body=read_source(root,name).decode('utf-8');safe_text(body)
                    stale=digest(body.encode())!=row['hash']
                except (OSError,ValueError,UnicodeError): stale=True
                candidates.insert(0,dict(row,source=name,source_hash=row['hash'],stale=stale))
        # Explicit user instructions and root rules must not lose constraints to
        # relevance ranking, excerpting, or optional-reference budget pressure.
        for record in self.memories(pid):
            if record['kind']!='user_instruction' or any(r.get('id')==record['id'] for r in candidates): continue
            stale=False
            if record['source'] and record['source_hash']:
                try: stale=self._source_stale(pid,record['source'],record['source_hash'])
                except (OSError,ValueError): stale=True
            candidates.append(dict(record,stale=stale))
        def required(record):
            return record.get('source') in ('AGENTS.md','CLAUDE.md') or record.get('kind')=='user_instruction'
        def role_priority(record):
            source=str(record.get('source') or '').lower()
            if role=='planner': return int(record.get('scope')=='project' or any(x in source for x in ('architecture','readme','decision')))
            if role=='reviewer': return int(record.get('scope')=='verification' or source.startswith(('test/','tests/')) or '/test_' in source or source.startswith('test_'))
            if role=='correction': return int(record.get('scope')=='error')
            if role=='executor': return int(record.get('record_type')=='file' and not source.endswith(('.md','.rst','.txt')))
            return 0
        candidates.sort(key=lambda record:(not required(record),-role_priority(record),-record.get('score',0)))
        for r in candidates:
            if r['stale']: excluded.append({'source':r.get('source'),'reason':'stale'});continue
            body=r['body'];lines=body.splitlines();terms=list(dict.fromkeys(re.findall(r'\w+',query.lower())))[:16]
            # Separate windows for separated query symbols, retaining original
            # line references. Do not summarize or truncate mandatory rules.
            windows=[]
            for term in terms:
                hits=[i for i,line in enumerate(lines) if term in line.lower()]
                if hits:
                    start=max(0,hits[0]-2);end=min(len(lines),start+24)
                    if not any(left<=hits[0]<right for left,right in windows): windows.append((start,end))
            if not windows: windows=[(0,min(24,len(lines)))]
            windows.sort();merged=[]
            for start,end in windows:
                if merged and start<=merged[-1][1]: merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
                else: merged.append((start,end))
            if required(r): merged=[(0,len(lines))]
            for start,end in merged:
                snippet=body if required(r) else '\n'.join(lines[start:end])
                fingerprint=digest(snippet.encode())
                if fingerprint in seen: excluded.append({'source':r.get('source'),'reason':'duplicate'});continue
                label=r.get('source') or r.get('title') or r.get('id')
                entry='\n[Untrusted reference: %s; line %d; kind %s]\n%s'%(label,start+1,r.get('kind','observed'),snippet)
                if len(('\n'.join(chunks+[entry])).encode())>capacity:
                    if required(r): raise ValueError('Required project instructions exceed context budget; increase budget or split the task explicitly')
                    excluded.append({'source':label,'reason':'budget'});continue
                seen.add(fingerprint)
                chunks.append(entry);refs.append({'source':label,'hash':r.get('source_hash'),'line':start+1,
                    'end_line':end,'reason':r.get('retrieval_reason',{'method':'required_instruction'})})
        content='\n'.join(chunks);size=len(content.encode());cid=ident()
        # Conservative payload bound is in bytes; token estimate is never provider usage.
        result={'id':cid,'project_id':pid,'content':content,'references':refs,'excluded':excluded,'bytes':size,'estimated_tokens':math.ceil(size/4),'token_measurement':'estimate_utf8_bytes_div_4','budget':int(budget),'critical':critical,'role':role,
                'compression':{'exact_duplicate_exclusions':sum(x['reason']=='duplicate' for x in excluded),'method':'exact snippet deduplication; no model summaries'},
                'selection':'required instructions first, then role priority and lexical relevance; fresh source hashes checked'}
        with self.connect() as db:
            prior=db.execute('SELECT id,metrics FROM context_packages WHERE project_id=? AND query=? AND content=? ORDER BY created_at DESC LIMIT 1',(pid,query,content)).fetchone()
            metadata={k:v for k,v in result.items() if k not in ('content','id')}
            if prior:
                old=json.loads(prior['metrics']);old.pop('id',None)
                if old==metadata:
                    result['id']=prior['id']
                    return result
            db.execute('INSERT INTO context_packages VALUES(?,?,?,?,?,?)',(cid,pid,query,content,json.dumps(metadata),stamp()))
            db.execute('DELETE FROM context_packages WHERE project_id=? AND id NOT IN (SELECT id FROM context_packages WHERE project_id=? ORDER BY created_at DESC LIMIT 20)',(pid,pid))
        return result

    def full_context(self,pid,budget=2000,critical=None):
        """Explicit benchmark control: repeat the entire permitted indexed corpus.

        Fail rather than silently truncate an oversized baseline. Normal workflows
        use retrieval. This method performs no provider calls or sharing grants.
        """
        if not 64<=int(budget)<=32000: raise ValueError('Invalid full-context budget')
        project=self.project(pid);root=Path(project['path']);exclusions=json.loads(project['exclusions'])
        chunks=[safe_text(x) for x in (critical or [])];refs=[];excluded=[]
        with self.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT path,hash,body FROM documents WHERE project_id=? ORDER BY path',(pid,))]
        for row in rows:
            name=row['path']
            if not allowed(name,exclusions) or git_ignored(root,name): continue
            try:
                raw=read_source(root,name);safe_text(raw.decode('utf-8'))
            except (OSError,ValueError,UnicodeError):
                excluded.append({'source':name,'reason':'unsafe'});continue
            if digest(raw)!=row['hash']:
                excluded.append({'source':name,'reason':'stale'});continue
            chunks.append('\n[Untrusted reference: %s]\n%s'%(name,row['body']))
            refs.append({'source':name,'hash':row['hash'],'line':1})
            if len('\n'.join(chunks).encode())>int(budget)*4:
                raise ValueError('Full indexed context exceeds explicit context budget')
        content='\n'.join(chunks);size=len(content.encode())
        if size>int(budget)*4: raise ValueError('Critical requirements exceed context budget')
        result={'id':ident(),'project_id':pid,'content':content,'references':refs,'excluded':excluded,
                'bytes':size,'estimated_tokens':math.ceil(size/4),'token_measurement':'estimate_utf8_bytes_div_4',
                'budget':int(budget),'critical':list(critical or []),'mode':'full_index'}
        with self.connect() as db:
            db.execute('INSERT INTO context_packages VALUES(?,?,?,?,?,?)',(result['id'],pid,'[explicit full-index benchmark]',content,json.dumps({k:v for k,v in result.items() if k!='content'}),stamp()))
            db.execute('DELETE FROM context_packages WHERE project_id=? AND id NOT IN (SELECT id FROM context_packages WHERE project_id=? ORDER BY created_at DESC LIMIT 20)',(pid,pid))
        return result

    def machine(self,refresh=False):
        with self.connect() as db:
            row=db.execute('SELECT * FROM machine_snapshot WHERE id=1').fetchone()
            if row and not refresh: return json.loads(row['content'])
            value={'os':platform.system(),'architecture':platform.machine(),'python':platform.python_version(),'disk_free_bytes':shutil.disk_usage(self.path.parent).free,'tools':{n:bool(shutil.which(n)) for n in ('git','docker','node','npm','pnpm','yarn','php','composer','go','make','pwsh','codex','claude')},'collected_at':stamp(),'sharing':'local_only'}
            if hasattr(os,'sysconf'):
                try: value['memory_bytes']=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
                except (OSError,ValueError): pass
            db.execute('INSERT OR REPLACE INTO machine_snapshot VALUES(1,?,?)',(json.dumps(value),stamp()))
        return value

    def backup(self,destination):
        dest=Path(destination).absolute()
        if dest.exists(): raise FileExistsError('Backup destination already exists')
        for p in (dest,)+tuple(dest.parents):
            if native.is_link(p): raise PermissionError('Unsafe backup path')
        native.secure_mkdir(dest.parent,parents=True,exist_ok=True)
        native.validate_permissions(dest.parent)
        fd=os.open(str(dest),os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        os.close(fd)
        try:
            native.secure_mode(dest,0o600)
            with self.connect() as source:
                target=sqlite3.connect(str(dest))
                try: source.backup(target)
                finally: target.close()
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
        return {'backup':str(dest),'sha256':digest(dest.read_bytes())}
