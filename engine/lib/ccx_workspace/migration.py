"""Explicit, read-only V4 import bound to one registered project's state identity."""
import json
import os
from pathlib import Path
import uuid
import ccx_platform as native
from .store import digest, safe_text, read_source

FIELDS = ('codex_session_id','claude_session_id','session_id','workflow_id','model','effort',
          'service_tier','workflow_status','active','title','status')


def import_v4(store, project_id, directory):
    project = store.project(project_id)
    expected = digest(str(Path(project['path']).resolve()).encode())[:16]
    root = Path(directory).absolute()
    for item in (root,) + tuple(root.parents):
        if native.is_link(item):
            raise PermissionError('Legacy source contains a link/reparse point')
    if not root.is_dir() or root.name != expected:
        raise ValueError('Select the V4 project-state directory named ' + expected)
    native.validate_permissions(root)
    manifest = root / 'integrity/manifest.json'
    if manifest.exists() or native.is_link(manifest):
        binding = json.loads(read_source(root, 'integrity/manifest.json').decode('utf-8'))
        if not isinstance(binding, dict) or binding.get('project') != project['path']:
            raise ValueError('Legacy integrity manifest belongs to another project')
    tasks = root / 'tasks'
    if native.is_link(tasks):
        raise PermissionError('Legacy task directory is a link/reparse point')
    paths = sorted(root.glob('*.json')) + sorted(tasks.glob('*.json'))
    if len(paths) > 2000:
        raise ValueError('Legacy import exceeds bounded record count')
    existing = {r['source'] for r in store.memories(project_id) if (r.get('source') or '').startswith('v4:')}
    planned, skipped = [], 0
    # Validate the entire selected source before importing any record. Existing
    # mapping files omit a project field, so the hashed state-directory identity
    # is mandatory; records/manifests that carry a project must agree as well.
    for path in paths:
        if native.is_link(path) or native.is_link(path.parent):
            raise PermissionError('Unsafe legacy record')
        try:
            uuid.UUID(path.stem)
        except ValueError:
            skipped += 1
            continue
        if path.stat().st_size > 256000:
            skipped += 1
            continue
        raw = read_source(root, path.relative_to(root))
        key = 'v4:' + project_id + ':' + path.relative_to(root).as_posix() + ':' + digest(raw)
        if key in existing:
            skipped += 1
            continue
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeError, ValueError):
            skipped += 1
            continue
        if not isinstance(value, dict):
            skipped += 1
            continue
        if 'project' in value and value['project'] != project['path']:
            raise ValueError('Legacy record belongs to another project')
        selected = {key: value[key] for key in FIELDS if key in value}
        if not selected:
            skipped += 1
            continue
        for name in ('codex_session_id','claude_session_id','session_id','workflow_id'):
            if name in selected:
                selected[name] = str(uuid.UUID(str(selected[name])))
        body = json.dumps(selected, ensure_ascii=True)
        safe_text(body)
        scope = 'workflow' if path.parent == tasks else 'session'
        planned.append((scope, 'Imported V4 record ' + path.stem, body, key))
    imported = 0
    for scope, title, body, key in planned:
        store.add_memory(project_id, scope, title, body, kind='observed', source=key, confidence=1.0)
        imported += 1
    return {'imported': imported, 'skipped': skipped, 'project_id': project_id,
            'source_modified': False, 'provider_ids_interchangeable': False}
