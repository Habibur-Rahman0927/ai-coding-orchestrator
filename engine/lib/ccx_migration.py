"""Explicit V3 migration and narrowly scoped legacy artifact archival.

The CLI supplies its existing filesystem, transaction, backup and locking API.
Legacy Python is parsed as data, never imported to discover profiles or variables.
"""
import ast
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile


STATE_NOTICE = ('Runtime state, session mappings, workflow history and logs are untouched. '
                'Only the integrity manifest is replaced; profile approvals are not granted.')
SESSION_NOTICE = ('New Claude sessions export ORCHESTRATOR_CLAUDE_SESSION_ID through the '
                  'SessionStart hook. Restart sessions started before migration. '
                  'User shell configuration is not edited.')


def reject(c, message, code=3):
    raise c.OrchestratorError(message, code)


def profiles_and_env(c, root):
    tree = ast.parse((root / '.claude/scripts/codex-session.py').read_text())
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name) and node.value.value.id == 'os'
                and node.value.attr == 'environ'):
            key = node.slice.value if isinstance(node.slice, ast.Index) else node.slice
            try:
                value = ast.literal_eval(key)
            except (ValueError, TypeError):
                continue
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*_CLAUDE_SESSION_ID', value):
                names.add(value)
    if len(names) != 1:
        reject(c, 'Cannot uniquely identify the V3 session environment variable')
    tree = ast.parse((root / '.claude/scripts/managed-exec.py').read_text())
    assignments = [node.value for node in tree.body if isinstance(node, ast.Assign)
                   and any(isinstance(t, ast.Name) and t.id == 'PROFILES' for t in node.targets)]
    if len(assignments) != 1:
        reject(c, 'Expected one literal V3 PROFILES dictionary')
    try:
        legacy = ast.literal_eval(assignments[0])
    except (ValueError, TypeError):
        reject(c, 'V3 PROFILES must be literal data')
    if not isinstance(legacy, dict):
        reject(c, 'V3 PROFILES must be a dictionary')
    converted = {}
    for name, spec in legacy.items():
        if not isinstance(name, str) or not isinstance(spec, (tuple, list)) or len(spec) != 3:
            reject(c, 'Invalid V3 profile')
        directory, command, timeout = spec
        if (not isinstance(directory, str) or not isinstance(command, list) or not command
                or not all(isinstance(arg, str) for arg in command)
                or type(timeout) is not int or timeout <= 0):
            reject(c, 'Invalid V3 profile: ' + name)
        if directory != '.':
            c.safe_target(root, directory)
        converted[name] = {'directory': directory, 'command': command, 'timeout': timeout}
    return next(iter(names)), converted


def instructions(c, root, version, rules_file):
    text = (root / 'CLAUDE.md').read_text()
    headings = list(re.finditer(r'^# Claude-Codex Orchestration V3\s*$', text, re.M))
    rules = list(re.finditer(r'^## 15\. (.+ Project Rules)[ \t]*\r?$', text, re.M))
    if len(headings) != 1 or len(rules) != 1 or headings[0].start() >= rules[0].start():
        reject(c, 'Unrecognised V3 CLAUDE.md boundaries')
    start, end = headings[0].start(), rules[0].start()
    sections = re.findall(r'^## (\d+)\.', text[start:end], re.M)
    if sections != [str(n) for n in range(1, 15)] or c.BLOCK_BEGIN in text:
        reject(c, 'Expected exactly V3 sections 1 through 14 before project rules')
    body = text[rules[0].end():]
    original_body = body
    if rules_file:
        path = Path(os.path.abspath(rules_file))
        c.assert_canonical_parent(path)
        body = '\n\n' + path.read_text()
    kept = text[:start] + '# ' + rules[0].group(1).strip() + body
    if c.BLOCK_BEGIN in body or c.BLOCK_END in body:
        reject(c, 'Project rules must not contain managed block markers')
    block = c.instruction_block(version, root, existing_text=kept)
    separator = '' if kept.endswith('\n\n') else '\n' if kept.endswith('\n') else '\n\n'
    new_text = kept + separator + block
    return new_text, text[start:end], {
        'heading': rules[0].group(1).strip(), 'line_count': len(original_body.strip('\r\n').splitlines()),
        'empty': not original_body.strip(), 'replacement': bool(rules_file),
        'original_body': original_body, 'body': body}


def validated_settings(c, path):
    value = c.load_settings(path)
    permissions, hooks = value.get('permissions', {}), value.get('hooks', {})
    if (not isinstance(permissions, dict) or not isinstance(permissions.get('allow', []), list)
            or not isinstance(hooks, dict) or not all(isinstance(v, list) for v in hooks.values())):
        reject(c, 'Invalid settings permissions/hooks structure')
    return value


def plan_migration(c, root, args):
    version = args.release or c.current_release()
    c.preflight(version)
    if c.release_metadata(version).get('status') != 'VERIFIED':
        reject(c, 'Target release is not VERIFIED')
    marker = c.safe_target(root, '.claude/orchestration.json')
    if marker.exists():
        reject(c, 'Project already has orchestration.json; migration refused')
    manifest_path = c.safe_target(c.state_dir(root), 'integrity/manifest.json')
    try:
        manifest = c.read_json(manifest_path, {})
    except ValueError:
        reject(c, 'Invalid V3 integrity manifest JSON', 6)
    required = set(c.USER_FILES) | {'.claude/settings.template.json',
                '.claude/scripts/codex-session.py', '.claude/hooks/completion-gate.py',
                '.claude/scripts/integrity-check.py', '.claude/scripts/managed-exec.py'}
    if (not isinstance(manifest, dict) or manifest.get('project') != str(root)
            or not isinstance(manifest.get('files'), dict) or not required <= set(manifest['files'])):
        reject(c, 'Missing or foreign V3 integrity manifest', 6)
    for rel in manifest['files']:
        path = c.safe_target(root, rel)
        if not path.is_file() or c.digest(path) != manifest['files'][rel]:
            reject(c, 'V3 integrity mismatch: ' + rel, 6)
    try:
        code, output = c.run_project_integrity(root)
    except (OSError, subprocess.SubprocessError) as error:
        reject(c, 'V3 integrity check could not complete: ' + str(error), 6)
    if code:
        reject(c, 'V3 integrity check failed:\n' + output, 6)
    payload = c.release_payload(version)
    old_scripts = {rel for rel in manifest['files']
                   if rel.startswith(('.claude/scripts/', '.claude/hooks/'))}
    touched = set(payload) | old_scripts | set(c.USER_FILES) | set(c.MANAGED_CONFIG)
    conflicts = []
    for rel in sorted(touched):
        path = c.safe_target(root, rel)
        if path.exists() and rel not in manifest['files']:
            conflicts.append(rel + ': UNMANAGED_FILE_AT_NEW_PATH')
    approvals = c.safe_target(c.state_dir(root), 'profile-approvals.json')
    if c.read_json(approvals, {}):
        reject(c, 'Existing profile approvals must be resolved before V3 migration')
    env, profiles = profiles_and_env(c, root)
    new_text, removed, rules = instructions(c, root, version, args.project_rules)
    settings = validated_settings(c, root / '.claude/settings.local.json')
    legacy_template = validated_settings(c, root / '.claude/settings.template.json')
    # Compare whole hook definitions, not command substrings; preserve all other data.
    permissions = settings.get('permissions', {})
    if 'allow' in permissions:
        permissions['allow'] = [entry for entry in permissions['allow']
                                if entry not in legacy_template.get('permissions', {}).get('allow', [])]
    for event, definitions in settings.get('hooks', {}).items():
        settings['hooks'][event] = [entry for entry in definitions
                                   if entry not in legacy_template.get('hooks', {}).get(event, [])]
    template = c.template_settings(version)
    added = c.merge_settings(settings, template)
    ignore_lines = (root / '.claude/.gitignore').read_text().splitlines(keepends=True)
    duplicates = set((c.release_dir(version) / 'templates/.gitignore').read_text().splitlines()) - {''}
    test_names = {'orchestration-test.txt', 'persistent-write-test.txt'}
    kept = [line for line in ignore_lines if line.rstrip('\r\n') not in duplicates
            and line.strip().lstrip('/') not in test_names]
    ignore = ''.join(kept).rstrip('\n') + '\n' + c.ignore_block(version)
    operations = [{'operation': 'replace' if rel in old_scripts else 'create', 'path': rel}
                  for rel in sorted(payload)]
    operations += [{'operation': 'remove', 'path': rel} for rel in sorted(old_scripts - set(payload))]
    operations += [{'operation': 'create' if rel in ('.claude/orchestration.json', '.claude/orchestration-profiles.json')
                    else 'rewrite', 'path': rel} for rel in sorted(set(c.USER_FILES) | set(c.MANAGED_CONFIG))]
    operations += [{'operation': 'rewrite', 'path': 'state/integrity/manifest.json'},
                   {'operation': 'register', 'path': 'engine/registry/projects.json'},
                   {'operation': 'backup', 'path': 'engine/backups/projects/' + c.project_id(root), 'kind': 'pre-migrate-v3'}]
    active = []
    for path in sorted((c.state_dir(root) / 'tasks').glob('*.json')):
        c.safe_target(c.state_dir(root), path.relative_to(c.state_dir(root)))
        workflow = c.read_json(path, {}) or {}
        if workflow.get('workflow_status') == 'RUNNING':
            active.append(workflow.get('workflow_id') or path.stem)
    report = {'project': str(root), 'from': '3', 'to': version, 'legacy_env_var': env,
              'v3_files': sorted(manifest['files']), 'profiles': profiles, 'profiles_approved': False,
              'project_rules': rules, 'active_workflows': active, 'conflicts': conflicts, 'operations': operations,
              'new_claude_md': new_text, 'removed_claude_md': removed,
              'new_settings': settings, 'added_settings': added, 'new_gitignore': ignore,
              'state_notice': STATE_NOTICE, 'session_notice': SESSION_NOTICE}
    return report, payload, old_scripts, template


def report_path(c, args, root):
    if not args.report:
        return None
    path = Path(os.path.abspath(args.report))
    c.assert_canonical_parent(path)
    for protected in (root, c.STATE_ROOT, c.GLOBAL):
        if path == protected or protected in path.parents:
            reject(c, 'Report must be outside the project, state and engine directories', 5)
    return path


def emit(c, report, destination):
    text = json.dumps(report, indent=2) + '\n'
    if destination:
        c.write_json(destination, report)
    print(text, end='')


def migrate(c, args):
    root = c.resolve_project(args)
    destination = report_path(c, args, root)
    if args.apply and not args.yes:
        reject(c, 'CONFIRMATION_REQUIRED: add --yes', 4)
    if c.safe_target(root, '.claude/orchestration.json').exists():
        reject(c, 'Project already has orchestration.json; migration refused')
    # V3 already has state. Check it before ProjectLocks can create anything.
    c.safe_target(c.STATE_ROOT, c.project_id(root) + '/integrity/manifest.json')
    if not (c.state_dir(root) / 'integrity/manifest.json').is_file():
        reject(c, 'V3 integrity manifest missing', 6)
    with c.ProjectLocks(root, cleanup_created=True):
        report, payload, old_scripts, template = plan_migration(c, root, args)
        if report['active_workflows'] or report['conflicts']:
            emit(c, report, None)
            return 7 if report['active_workflows'] else 3
        if not args.apply:
            emit(c, report, destination)
            return 0
        version = report['to']
        for rel in ('backups/projects/' + c.project_id(root), 'registry/projects.json', 'registry/projects.lock'):
            c.safe_target(c.GLOBAL, rel)
        backup, record = c.create_backup(root, 'pre-migrate-v3', '3',
                                         extra_files=old_scripts | set(payload), scope_version=version)

        def action(tx):
            for rel, source in payload.items():
                tx.write(c.safe_target(root, rel), source.read_bytes(), 0o700)
            for rel in old_scripts - set(payload):
                tx.remove(c.safe_target(root, rel))
            c.fault('migrate:after-scripts')
            for rel, value in (('.claude/settings.local.json', report['new_settings']),
                               ('.claude/settings.template.json', template),
                               ('.claude/orchestration-profiles.json', {'schema': 1, 'profiles': report['profiles']})):
                tx.write(c.safe_target(root, rel), json.dumps(value, indent=2) + '\n')
            c.fault('migrate:after-settings')
            for rel, value in (('CLAUDE.md', report['new_claude_md']), ('.claude/.gitignore', report['new_gitignore'])):
                path = c.safe_target(root, rel)
                tx.write(path, value, stat.S_IMODE(path.stat().st_mode))
            c.fault('migrate:after-instructions')
            config = {'schema': 2, 'version': version, 'project': str(root), 'project_id': c.project_id(root),
                      'installed_at': c.now(), 'updated_at': c.now(), 'install_backup': str(backup),
                      'managed_files': {r: c.digest(p) for r, p in payload.items()},
                      'added_settings': report['added_settings'],
                      'instruction_block_sha256': c.sha256_bytes((c.BLOCK_BEGIN + report['new_claude_md'].split(c.BLOCK_BEGIN, 1)[1]).encode())}
            tx.write(c.safe_target(root, '.claude/orchestration.json'), json.dumps(config, indent=2) + '\n')
            manifest = c.build_manifest(root, list(payload) + list(c.MANAGED_CONFIG))
            tx.write(c.safe_target(c.state_dir(root), 'integrity/manifest.json'), json.dumps(manifest, indent=2) + '\n')
            code, output = c.run_project_integrity(root)
            if code:
                reject(c, 'Post-migration integrity check failed:\n' + output, 6)
            record.update(to_version=version, completed_at=c.now(), post_files={
                rel: c.digest(root / rel) if (root / rel).is_file() else None for rel in record['files']})
            tx.write(backup / 'backup.json', json.dumps(record, indent=2) + '\n')
            report['backup'] = str(backup)
            report['completed_at'] = record['completed_at']
            if destination:
                tx.write(destination, json.dumps(report, indent=2) + '\n')
            c.fault('migrate:before-register')
            tx.ensure_dir(c.REGISTRY.parent)
            tx.remember(c.REGISTRY)
            c.register(root, version)
        c.run_transaction(action)
        print(json.dumps(report, indent=2))
    return 0


def archive(c, args):
    root = c.resolve_project(args)
    config = c.require_managed_install(root)
    c.preflight(config.get('version'))
    destination = Path(os.path.abspath(args.to))
    c.assert_canonical_parent(destination)
    for protected in (root, c.STATE_ROOT):
        if destination == protected or protected in destination.parents:
            reject(c, 'Archive destination must be outside the project and runtime state', 5)
    if args.apply and not args.yes:
        reject(c, 'CONFIRMATION_REQUIRED: add --yes', 4)
    for rel in ('.claude/scripts', '.claude/hooks', '.claude/scripts/integrity-check.py'):
        c.safe_target(root, rel)
    with c.ProjectLocks(root, cleanup_created=True):
        code, output = c.run_project_integrity(root)
        if code:
            reject(c, 'Project integrity failed:\n' + output, 6)
        tracked_result = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True)
        tracked = set(tracked_result.stdout.decode().split('\0'))
        candidates = set()
        base = c.safe_target(root, '.claude/backups')
        if base.exists():
            candidates.update(p for p in base.rglob('*') if not p.is_dir() or p.is_symlink())
        for folder in ('.claude', '.claude/scripts', '.claude/hooks'):
            candidates.update((root / folder).glob('*.backup'))
        for name in ('orchestration-test.txt', 'persistent-write-test.txt'):
            path = root / '.claude' / name
            if path.exists() or path.is_symlink():
                candidates.add(path)
        for folder in ('.claude/scripts', '.claude/hooks'):
            for directory in (root / folder).rglob('__pycache__'):
                c.safe_target(root, directory.relative_to(root))
                candidates.update(p for p in directory.rglob('*') if not p.is_dir() or p.is_symlink())
        entries, skipped = [], []
        managed = set(c.read_json(c.state_dir(root) / 'integrity/manifest.json', {}).get('files', {}))
        for path in sorted(candidates):
            rel = path.relative_to(root).as_posix()
            c.safe_target(root, rel)
            if not path.is_file():
                reject(c, 'Non-regular archive candidate: ' + rel, 5)
            if rel in tracked or rel in managed:
                skipped.append(rel)
                continue
            operation = 'delete' if '__pycache__' in path.parts and path.suffix == '.pyc' else 'archive'
            entries.append({'path': rel, 'operation': operation, 'sha256': c.digest(path),
                            'mode': stat.S_IMODE(path.stat().st_mode)})
        report = {'project': str(root), 'destination': str(destination), 'files': entries, 'kept_tracked_or_managed': skipped}
        if not args.apply:
            print(json.dumps(report, indent=2))
            return 0
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = Path(tempfile.mkdtemp(prefix=c.project_id(root) + '-' + c.now().replace(':', '-') + '-', dir=destination))
        manifest = {'files': {}, 'modes': {}}
        parents = set()
        for entry in entries:
            rel = entry['path']
            source = c.safe_target(root, rel)
            if c.digest(source) != entry['sha256']:
                reject(c, 'Archive source changed: ' + rel, 6)
            if entry['operation'] == 'archive':
                dest = c.safe_target(directory, rel)
                dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                c.atomic_write(dest, source.read_bytes(), entry['mode'])
                manifest['files'][rel] = entry['sha256']
                manifest['modes'][rel] = entry['mode']
            parents.update(p for p in source.parents if root / '.claude' in p.parents)
        c.write_json(directory / 'checksums.json', manifest)
        if c.read_json(directory / 'checksums.json') != manifest:
            reject(c, 'Archive manifest verification failed', 6)
        for rel, expected in manifest['files'].items():
            if c.digest(c.safe_target(directory, rel)) != expected:
                reject(c, 'Archive copy verification failed: ' + rel, 6)

        def remove(tx):
            for entry in entries:
                path = c.safe_target(root, entry['path'])
                if c.digest(path) != entry['sha256']:
                    reject(c, 'Archive source changed: ' + entry['path'], 6)
                tx.remove(path)
        c.run_transaction(remove)
        for parent in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            try:
                parent.rmdir()
            except OSError:
                pass
        report['archive'] = str(directory)
        print(json.dumps(report, indent=2))
    return 0
