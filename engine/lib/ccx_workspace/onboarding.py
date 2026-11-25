"""Persisted setup, bounded project preview and redacted local health checks."""
import json
from pathlib import Path
import subprocess
import time
from .settings import setting, save_setting
from .store import allowed, file_path, read_source

DEFAULTS = {'planner': 'codex', 'executor': 'codex', 'reviewer': 'codex',
            'fallback_provider': None, 'context_budget': 2000, 'max_cost': 0,
            'max_tokens': 50000, 'max_seconds': 1800, 'approval_policy': 'ask'}


def setup_state(store, registry):
    from .credentials import CredentialManager
    state = setting(store, 'setup', {'completed': False, 'step': 1, 'defaults': DEFAULTS})
    return dict(state, environment=store.machine(), machine=store.machine(),
                credential_facilities=CredentialManager(store).facilities(),
                providers=registry.status(), storage={'database': str(store.path), 'local_only': True})


def save_setup(store, body):
    if set(body) - {'step', 'completed', 'defaults'}:
        raise ValueError('Unknown setup field')
    state = setting(store, 'setup', {'completed': False, 'step': 1, 'defaults': dict(DEFAULTS)})
    if 'step' in body:
        if type(body['step']) != int or not 1 <= body['step'] <= 6:
            raise ValueError('Invalid setup step')
        state['step'] = body['step']
    if 'completed' in body:
        if type(body['completed']) != bool:
            raise ValueError('Invalid setup completion')
        state['completed'] = body['completed']
    if 'defaults' in body:
        from .workflows import provider_identifier
        values = body['defaults']
        if not isinstance(values, dict) or set(values) - set(DEFAULTS):
            raise ValueError('Unknown default setting')
        defaults = dict(state['defaults'], **values)
        for role in ('planner', 'executor', 'reviewer', 'fallback_provider'):
            if role == 'fallback_provider' and defaults[role] in (None, ''):
                defaults[role] = None
            elif not provider_identifier(defaults[role]):
                raise ValueError('Invalid default provider')
        for field, minimum, maximum in (('context_budget',128,32000),('max_tokens',128,1000000),('max_seconds',1,86400)):
            if type(defaults[field]) != int or not minimum <= defaults[field] <= maximum:
                raise ValueError('Invalid default budget')
        import math
        cost = defaults['max_cost']
        if isinstance(cost,bool) or not isinstance(cost,(float,int)) or not math.isfinite(cost) or not 0 <= cost <= 10000:
            raise ValueError('Invalid default cost')
        if defaults['approval_policy'] not in ('ask','reuse_scoped'):
            raise ValueError('Unknown approval policy')
        state['defaults'] = defaults
    save_setting(store, 'setup', state)
    return state


def preview(path, exclusions=()):
    import ccx_platform as native
    original = Path(path).absolute()
    if any(native.is_link(p) for p in (original,) + tuple(original.parents)):
        raise PermissionError('Select a real project directory without links')
    root = original.resolve(strict=True)
    native.validate_owner(root)
    if root == Path.home().resolve():
        raise PermissionError('A home directory cannot be registered as a project')
    result = subprocess.run(['git','-C',str(root),'rev-parse','--show-toplevel'], capture_output=True, timeout=10, text=True)
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise ValueError('Select a Git repository root')
    # Limit listing output as well as returned preview; no contents are indexed.
    with subprocess.Popen(['git','-C',str(root),'ls-files','-z','--cached','--others','--exclude-standard'], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
        raw = proc.stdout.read(4*1024*1024+1)
        if len(raw) > 4*1024*1024:
            proc.kill()
            raise ValueError('Project file listing exceeds preview limit')
        proc.wait(timeout=10)
    names = sorted(set(raw.decode('utf-8','replace').split('\0'))- {''})
    included, excluded = [], 0
    for name in names[:50000]:
        if not allowed(name,exclusions):
            excluded += 1
            continue
        try:
            p = file_path(root,name)
            if not p.is_file() or p.stat().st_nlink != 1:
                excluded += 1
                continue
        except (ValueError,OSError):
            excluded += 1
            continue
        included.append(name)
    technologies = [label for marker,label in [('pyproject.toml','Python'),('requirements.txt','Python'),
        ('package.json','JavaScript/TypeScript'),('Cargo.toml','Rust'),('go.mod','Go'),('composer.json','PHP')]
        if marker in included]
    return {'path':str(root),'file_count':len(included),'excluded_count':excluded,
            'sample':included[:30],'technologies':sorted(set(technologies)),
            'instructions':[x for x in included if Path(x).name in ('AGENTS.md','CLAUDE.md','README.md')][:20],
            'exclusions':list(exclusions),'indexed':False,'truncated':len(names)>50000}


def doctor(store, registry, engine):
    from .credentials import CredentialManager
    with store.connect() as db:
        integrity = db.execute('PRAGMA quick_check').fetchone()[0]
        documents = db.execute('SELECT COUNT(*) FROM documents').fetchone()[0]
    flows = engine.list()
    interrupted = [f['id'] for f in flows if f['status'] in ('RECOVERY_REQUIRED','BLOCKED','RUNNING')]
    return {'version':'5.0.0-dev','database_integrity':'ok' if integrity=='ok' else 'failed',
            'storage_permissions':'validated','providers':registry.status(),
            'credential_facilities':CredentialManager(store).facilities(),
            'project_count':len(store.projects()),'indexed_document_count':documents,
            'workflows_needing_inspection':interrupted,
            'recommendations':(['Inspect interrupted workflows before retrying; no automatic replay.'] if interrupted else []),
            'platform':store.machine(), 'generated_at':time.time(),
            'updates':'Not checked: no configured update feed or network request',
            'redacted':True}
