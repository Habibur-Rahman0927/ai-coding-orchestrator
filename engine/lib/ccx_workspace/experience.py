"""Local navigation preferences and execution proposals. Never grants or runs work."""
import re
import json
from .settings import setting, initialize

PROVIDERS = ('codex', 'claude', 'minimax')
PRESETS = {
    'question': {'label': 'Ask a question', 'policy': 'solo'},
    'quick_fix': {'label': 'Quick fix', 'policy': 'single_task'},
    'feature': {'label': 'Feature development', 'policy': 'standard'},
    'review': {'label': 'Review and test', 'policy': 'single_task'},
}


def preferences(store, body=None):
    default = {'project': '', 'favorites': [], 'recent': [], 'appearance': 'system', 'agents': {}}
    if body is None:
        return setting(store, 'experience', default)
    initialize(store)
    # Different tabs/controls may update independent preferences concurrently.
    # Merge while holding a SQLite write transaction, not from a stale snapshot.
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM dashboard_settings WHERE key='experience'").fetchone()
        value = _update_preferences(store, body, json.loads(row[0]) if row else default)
        db.execute('INSERT OR REPLACE INTO dashboard_settings(key,value) VALUES(?,?)',
                   ('experience', json.dumps(value)))
    return value


def _update_preferences(store, body, value):
    if not isinstance(body, dict) or set(body) - {'project', 'favorite', 'appearance', 'agent'}:
        raise ValueError('Unknown workspace preference')
    if not all(isinstance(v, str) and len(v) <= 200 for v in body.values()):
        raise ValueError('Workspace preferences must be short text values')
    value = dict(value, agents=dict(value.get('agents', {})))
    if 'project' in body:
        project = body['project']
        store.project(project)
        value['project'] = project
        value['recent'] = ([project] + [p for p in value.get('recent', []) if p != project])[:20]
    if 'favorite' in body:
        project = body['favorite']
        store.project(project)
        favorites = list(value.get('favorites', []))
        if project in favorites:
            favorites.remove(project)
        elif len(favorites) < 100:
            favorites.append(project)
        else:
            raise ValueError('Favorite project limit reached')
        value['favorites'] = favorites
    if 'appearance' in body:
        if body['appearance'] not in ('system', 'light', 'dark'):
            raise ValueError('Choose system, light or dark appearance')
        value['appearance'] = body['appearance']
    if 'agent' in body:
        if body['agent'] not in PROVIDERS or not value.get('project'):
            raise ValueError('Select a project and a supported provider first')
        value['agents'][value['project']] = body['agent']
    return value


def propose(store, registry, body):
    """Conservative deterministic routing, only from explicit controls/imperatives.

    Provider mentions in prose are not permission. Even a matched imperative only
    proposes a draft; the existing workflow/chat boundaries still authorize calls.
    """
    if not isinstance(body, dict) or set(body) - {'project_id', 'instruction', 'provider', 'partner', 'mode', 'preset', 'criteria'}:
        raise ValueError('Unknown task proposal field')
    project = body.get('project_id')
    if not isinstance(project, str):
        raise ValueError('Select a registered project')
    store.project(project)
    instruction = body.get('instruction', '')
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 16000:
        raise ValueError('Describe a task in at most 16000 characters')
    if re.fullmatch(r'\s*continue (?:the )?previous (?:task|work)\.?\s*', instruction, re.I):
        from .workflows import WorkflowEngine
        workflows = [w for w in WorkflowEngine(store).list() if w['project_id'] == project]
        unfinished = [w for w in workflows if w['status'] not in ('COMPLETED', 'CANCELLED')]
        if not workflows:
            raise ValueError('No previous workflow in this project. Describe a new task or choose a recent conversation.')
        chosen = (unfinished or workflows)[0]
        return {'kind': 'continue', 'workflow_id': chosen['id'], 'project_id': project,
                'strategy': 'Inspect previous work: '+chosen['objective'],
                'reason': 'Saved status: '+chosen['status']+'. Inspect effects and approvals before resuming. Completed work is not restarted.',
                'permissions_granted': False, 'execution_started': False}
    provider, partner = body.get('provider'), body.get('partner')
    if provider not in PROVIDERS or partner not in (None, '') + PROVIDERS:
        raise ValueError('Select supported providers')
    mode, preset = body.get('mode', 'solo'), body.get('preset', 'question')
    if mode not in ('solo', 'collaborate', 'auto') or preset not in PRESETS:
        raise ValueError('Choose an available mode and preset')
    requested = re.match(r'^\s*(?:use|ask)\s+(codex|claude|minimax)(?:\s+and\s+(codex|claude|minimax)\s+together\b|\s+to\s+)', instruction, re.I)
    mentioned = [p.lower() for p in requested.groups() if p] if requested else []
    selected = [provider] + ([partner] if partner else [])
    if any(p not in selected for p in mentioned):
        raise ValueError('Your instruction requests another provider. Select it explicitly and review the sharing and usage permissions.')
    collaboration = mode == 'collaborate' or (mode == 'auto' and preset != 'question')
    if mentioned and mentioned[0] != provider and not (collaboration and mentioned[0] == partner and re.match(r'^\s*ask\s+\w+\s+to\s+review\b', instruction, re.I)):
        raise ValueError('Select the requested implementation provider as your AI provider before continuing')
    if len(set(mentioned)) > 1 and not collaboration:
        raise ValueError('Choose Collaborate to draft a task with both requested providers')
    if collaboration and (not partner or partner == provider):
        raise ValueError('Choose a different collaboration partner for independent review')
    statuses = {p['id']: p for p in registry.status()}
    needed = selected if collaboration else [provider]
    for name in needed:
        if not statuses.get(name, {}).get('available'):
            raise ValueError(name + ' is unavailable. Open Providers to check its local setup; no work has started.')
    criteria = body.get('criteria', '')
    if not isinstance(criteria, str) or len(criteria) > 8000:
        raise ValueError('Verification criteria must be text of at most 8000 characters')
    if collaboration and not criteria.strip():
        raise ValueError('Describe what must pass before this task can be called complete')
    result = {'kind': 'workflow' if collaboration else 'chat', 'project_id': project,
              'instruction': instruction.strip(), 'provider': provider,
              'strategy': ('Implement with '+provider+'; test and review with '+partner) if collaboration else 'Read-only conversation with '+provider,
              'reason': ('Your chosen preset requires implementation and independent verification.' if collaboration else 'Questions use one selected provider; no workflow or file mutation is implied.'),
              'permissions_granted': False, 'execution_started': False,
              'authentication': 'Local availability is not verified authentication or quota',
              'preset': preset}
    if collaboration:
        from .onboarding import DEFAULTS
        defaults = dict(DEFAULTS, **setting(store, 'setup', {}).get('defaults', {}))
        result['workflow'] = {'project_id': project, 'objective': instruction.strip(),
                              'criteria': [c.strip() for c in criteria.splitlines() if c.strip()],
                              'providers': {'planner': provider, 'executor': provider, 'reviewer': partner},
                              'execution_policy': PRESETS[preset]['policy'] if preset != 'question' else 'single_task',
                              'budgets': {'max_cost': defaults['max_cost'], 'max_tokens': defaults['max_tokens'],
                                          'max_context_tokens': defaults['context_budget'], 'max_seconds': defaults['max_seconds']}}
    return result
