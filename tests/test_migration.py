#!/usr/bin/env python3
"""V3 migration, transaction recovery, and explicit legacy archival regressions."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/legacy-v3'
RELEASE = os.environ.get('ORCH_TEST_RELEASE', '4.1.0' if sys.platform.startswith('linux') else '4.3.0')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot(root, exclude=()):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), stat.S_IMODE(p.stat().st_mode))
            for p in root.rglob('*') if p.is_file() and p.relative_to(root).as_posix() not in exclude}


class Migration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-migration-')
        self.tmp = Path(self.temp.name).resolve()
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", TMPDIR=str(self.tmp))
        self.env.pop('ORCHESTRATOR_FAULT', None)
        self.engine = self.tmp / 'engine'
        self.bin = self.tmp / 'bin'
        self.run_command(['/bin/sh', ROOT / 'install.sh', '--prefix', self.engine, '--bin-dir', self.bin])
        self.project = self.tmp / 'PROJECT'
        shutil.copytree(FIXTURE, self.project)
        self.run_command(['git', 'init', '-q', self.project])
        (self.project / 'AGENTS.md').write_text('Application instructions\n')
        skills = self.project / '.agents/skills/x'
        skills.mkdir(parents=True)
        (skills / 'SKILL.md').write_text('Application skill\n')
        (self.project / 'app.txt').write_text('Unrelated application data\n')
        self.template = json.loads((self.project / '.claude/settings.template.json').read_text())
        settings = json.loads(json.dumps(self.template))
        settings['permissions']['allow'].append('Bash(make test)')
        settings['permissions']['deny'] = ['Bash(rm *)']
        settings['permissions']['ask'] = ['Bash(curl *)']
        self.user_hook = {'hooks': [{'type': 'command', 'command': 'echo user-hook'}]}
        settings['hooks']['SessionStart'].append(self.user_hook)
        settings['other'] = {'keep': True}
        (self.project / '.claude/settings.local.json').write_text(json.dumps(settings))
        with (self.project / '.claude/.gitignore').open('a') as stream:
            stream.write('keep-local.txt\n')
        self.pid = hashlib.sha256(str(self.project).encode()).hexdigest()[:16]
        self.state = self.home / '.local/state/claude-codex' / self.pid
        (self.state / 'integrity').mkdir(parents=True)
        for rel, content in {'session.json': '{"mapping":"keep"}', 'tasks/done.json': '{"active": false}',
                             'tasks/history/archive.json': '{"history":"keep"}', 'logs/session.log': 'keep',
                             'managed-executions/finished.json': '{"status":"SUCCESS"}'}.items():
            path = self.state / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        # Include an obsolete managed V3 script to exercise deletion and restoration.
        (self.project / '.claude/scripts/legacy-extra.py').write_text('# obsolete managed script\n')
        self.seal_v3()
        self.cli('adopt')
        self.original_project = snapshot(self.project)
        self.original_state = snapshot(self.state)
        self.registered_at = self.registry()['registered_at']

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, expected=0, env=None, cwd=None):
        result = subprocess.run([str(x) for x in command], env=env or self.env, cwd=cwd,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def cli(self, *args, expected=0, env=None):
        return self.run_command([sys.executable, self.engine / 'orchestrator.py'] + list(args),
                                expected, env, self.project)

    def seal_v3(self):
        files = ['CLAUDE.md', '.claude/settings.local.json', '.claude/settings.template.json', '.claude/.gitignore']
        files += [p.relative_to(self.project).as_posix() for folder in ('scripts', 'hooks')
                  for p in (self.project / '.claude' / folder).glob('*.py')]
        for rel in files:
            (self.project / rel).chmod(0o600)
        (self.state / 'integrity/manifest.json').write_text(json.dumps({
            'project': str(self.project), 'files': {r: digest(self.project / r) for r in files}}, indent=2))
        (self.state / 'integrity/manifest.json').chmod(0o600)

    def registry(self):
        return json.loads((self.engine / 'registry/projects.json').read_text())['projects'][self.pid]

    def migrate(self, *args, **kwargs):
        flags = [] if RELEASE == '4.1.0' else ['--release', RELEASE, '--allow-unverified']
        return self.cli('migrate-v3', *flags, *args, **kwargs)

    @unittest.skipIf(sys.platform.startswith('linux'), 'requires a real non-Linux host')
    def test_non_linux_default_refuses_and_candidate_migrates(self):
        before = snapshot(self.tmp)
        paths = sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob('*'))
        for mode in (['--check'], ['--dry-run'], ['--apply', '--yes']):
            result = self.cli('migrate-v3', *mode, '--report', self.tmp / 'refused.json', expected=3)
            self.assertIn('payload requires Linux', result.stderr)
            self.assertIn('--release 4.3.0 --allow-unverified', result.stderr)
            self.assertEqual(snapshot(self.tmp), before)
            self.assertEqual(sorted(str(p.relative_to(self.tmp)) for p in self.tmp.rglob('*')), paths)
        self.cli('migrate-v3', '--release', '4.3.0', '--apply', '--yes', expected=3)
        self.assertEqual(snapshot(self.tmp), before)
        self.cli('migrate-v3', '--release', '4.3.0', '--allow-unverified', '--apply', '--yes')
        self.assertEqual(self.registry()['version'], '4.3.0')
        report = json.loads(self.cli('verify').stdout)
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(report['runtime_compatible'])

    def test_check_dry_run_and_confirmation(self):
        before = snapshot(self.tmp)
        check = json.loads(self.migrate('--check').stdout)
        self.assertEqual(check['legacy_env_var'], 'LEGACY_CLAUDE_SESSION_ID')
        self.assertFalse(check['project_rules']['empty'])
        self.assertIn('frontend-build', check['profiles'])
        self.assertFalse(check['profiles_approved'])
        self.assertEqual(check['conflicts'], [])
        self.assertEqual(check['active_workflows'], [])
        dry = json.loads(self.migrate('--dry-run').stdout)
        self.assertIn('## 14.', dry['removed_claude_md'])
        self.assertNotIn('## 15.', dry['removed_claude_md'])
        self.assertIn('# Example Project Rules', dry['new_claude_md'])
        self.migrate('--apply', expected=4)
        self.assertEqual(before, snapshot(self.tmp))
        report = self.tmp / 'report.json'
        self.migrate('--dry-run', '--report', report)
        self.assertEqual(json.loads(report.read_text()), dry)

    def test_success_and_runtime_preservation(self):
        report = json.loads(self.migrate('--apply', '--yes').stdout)
        for folder in ('scripts', 'hooks'):
            for source in (ROOT / 'engine/releases' / RELEASE / folder).glob('*.py'):
                self.assertEqual(source.read_bytes(), (self.project / '.claude' / folder / source.name).read_bytes())
        self.assertFalse((self.project / '.claude/scripts/legacy-extra.py').exists())
        for rel in ('AGENTS.md', '.agents/skills/x/SKILL.md', 'app.txt'):
            self.assertEqual(self.original_project[rel], snapshot(self.project)[rel])
        self.assertEqual({k: v for k, v in self.original_state.items() if k != 'integrity/manifest.json'},
                         snapshot(self.state, ('integrity/manifest.json',)))
        config = json.loads((self.project / '.claude/orchestration.json').read_text())
        self.assertEqual(config['version'], RELEASE)
        self.assertEqual(self.registry()['version'], RELEASE)
        self.assertEqual(self.registry()['registered_at'], self.registered_at)
        settings = json.loads((self.project / '.claude/settings.local.json').read_text())
        new_template = json.loads((ROOT / 'engine/releases' / RELEASE / 'templates/settings.template.json').read_text())
        self.assertEqual(settings['permissions']['allow'], ['Bash(make test)'] + new_template['permissions']['allow'])
        self.assertEqual(settings['permissions']['deny'], ['Bash(rm *)'])
        self.assertEqual(settings['permissions']['ask'], ['Bash(curl *)'])
        self.assertEqual(settings['other'], {'keep': True})
        self.assertEqual(settings['hooks']['SessionStart'], [self.user_hook] + new_template['hooks']['SessionStart'])
        self.assertEqual(config['added_settings']['allow'], new_template['permissions']['allow'])
        text = (self.project / 'CLAUDE.md').read_text()
        self.assertTrue(text.startswith('@AGENTS.md\n\n# Example Project Rules'))
        self.assertIn('Preserve API compatibility.', text)
        self.assertEqual(text.count('@AGENTS.md'), 1)
        self.assertEqual(text.count('<!-- BEGIN CLAUDE-CODEX ORCHESTRATION'), 1)
        self.assertNotIn('Orchestration V3', text)
        ignore = (self.project / '.claude/.gitignore').read_text()
        self.assertIn('keep-local.txt', ignore)
        self.assertNotIn('orchestration-test.txt', ignore)
        self.assertEqual(ignore.count('/backups/'), 1)
        self.cli('verify')
        profiles = self.run_command([sys.executable, self.project / '.claude/scripts/managed-exec.py', '--list'])
        rows = [json.loads(line) for line in profiles.stdout.splitlines()]
        self.assertEqual(set(report['profiles']), {r['profile'] for r in rows})
        self.assertTrue(all(not r['approved'] for r in rows))
        self.assertEqual(report['profiles']['frontend-build'], {'directory': 'frontend', 'command': ['npm', 'run', 'build'], 'timeout': 1200})
        record = json.loads((Path(report['backup']) / 'backup.json').read_text())
        self.assertEqual(record['kind'], 'pre-migrate-v3')
        self.assertEqual(record['version_before'], '3')
        self.assertIn('completed_at', record)
        self.assertIn('integrity/manifest.json', record['state'])
        self.migrate('--apply', '--yes', expected=3)

    def test_empty_rules_replacement(self):
        path = self.project / 'CLAUDE.md'
        path.write_text(path.read_text().split('## 15.')[0] + '## 15. Example Project Rules\n\n')
        self.seal_v3()
        replacement = self.tmp / 'rules.md'
        replacement.write_text('Custom replacement rules.\n')
        report = json.loads(self.migrate('--dry-run', '--project-rules', replacement).stdout)
        self.assertTrue(report['project_rules']['empty'])
        self.assertIn('Custom replacement rules.', report['new_claude_md'])
        self.migrate('--apply', '--yes', '--project-rules', replacement)
        self.assertIn('Custom replacement rules.', (self.project / 'CLAUDE.md').read_text())

    def test_integrity_failure(self):
        (self.project / '.claude/scripts/codex-session.py').write_text('tampered')
        before = snapshot(self.tmp)
        self.migrate('--apply', '--yes', expected=6)
        self.assertEqual(before, snapshot(self.tmp))

    def test_project_checker_failure_and_invalid_settings(self):
        checker = self.project / '.claude/scripts/integrity-check.py'
        original = checker.read_bytes()
        checker.write_text('raise SystemExit(1)\n')
        self.seal_v3()
        before = snapshot(self.tmp)
        self.migrate('--dry-run', expected=6)
        self.assertEqual(before, snapshot(self.tmp))
        checker.write_bytes(original)
        (self.project / '.claude/settings.local.json').write_text('{invalid')
        self.seal_v3()
        before = snapshot(self.tmp)
        self.migrate('--apply', '--yes', expected=3)
        self.assertEqual(before, snapshot(self.tmp))

    def test_unverified_release_and_cli_integrity(self):
        meta = self.engine / 'releases' / RELEASE / 'release.json'
        original = meta.read_bytes()
        value = json.loads(original)
        value['status'] = 'TESTING'
        meta.write_text(json.dumps(value))
        before = snapshot(self.tmp)
        self.cli('migrate-v3', '--release', RELEASE, '--apply', '--yes', expected=3)
        self.assertEqual(before, snapshot(self.tmp))
        meta.write_bytes(original)
        cli = self.engine / 'orchestrator.py'
        cli.write_bytes(cli.read_bytes() + b'\n# changed\n')
        before = snapshot(self.tmp)
        self.migrate('--apply', '--yes', expected=6)
        self.assertEqual(before, snapshot(self.tmp))

    def test_symlink_touched_path_refused(self):
        path = self.project / 'CLAUDE.md'
        external = self.tmp / 'external.md'
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        before = external.read_bytes()
        self.migrate('--apply', '--yes', expected=5)
        self.assertEqual(external.read_bytes(), before)
        self.assertTrue(path.is_symlink())

    def test_replace_rules_and_apply_report(self):
        replacement = self.tmp / 'rules.md'
        replacement.write_text('Replacement policy.\n')
        report_file = self.tmp / 'migration.json'
        self.migrate('--apply', '--yes', '--project-rules', replacement, '--report', report_file)
        report = json.loads(report_file.read_text())
        self.assertIn('Preserve API compatibility.', report['project_rules']['original_body'])
        self.assertNotIn('Preserve API compatibility.', report['new_claude_md'])
        self.assertIn('Replacement policy.', report['new_claude_md'])
        self.assertTrue(Path(report['backup']).is_dir())

    def test_active_workflow(self):
        (self.state / 'tasks/running.json').write_text('{"active": true, "workflow_status": "RUNNING", "workflow_id": "running"}')
        before = snapshot(self.tmp)
        self.migrate('--check', expected=7)
        self.migrate('--apply', '--yes', expected=7)
        self.assertEqual(before, snapshot(self.tmp))

    def test_lock_busy(self):
        for name in ('management.lock', 'project-execution.lock'):
            with (self.state / name).open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                before = snapshot(self.tmp)
                self.migrate('--apply', '--yes', expected=75)
                self.assertEqual(before, snapshot(self.tmp))
            (self.state / name).unlink()

    def test_fault_recovery(self):
        for point in ('after-scripts', 'after-settings', 'after-instructions', 'before-register'):
            before_registry = (self.engine / 'registry/projects.json').read_bytes()
            self.migrate('--apply', '--yes', env=dict(self.env, ORCHESTRATOR_FAULT='migrate:' + point), expected=1)
            self.assertEqual(self.original_project, snapshot(self.project))
            self.assertEqual(self.original_state, snapshot(self.state))
            self.assertEqual(before_registry, (self.engine / 'registry/projects.json').read_bytes())

    def test_rollback_restores_v3(self):
        self.migrate('--apply', '--yes')
        self.cli('rollback', '--check')
        self.cli('rollback', '--dry-run')
        self.cli('rollback', '--apply', '--yes')
        self.assertEqual(self.original_project, snapshot(self.project))
        self.assertEqual(self.original_state, snapshot(self.state))
        self.assertEqual(self.registry()['version'], '3')
        self.assertFalse((self.project / '.claude/orchestration.json').exists())
        self.cli('verify')

    def test_rollback_fault_restores_v4(self):
        self.migrate('--apply', '--yes')
        project, state = snapshot(self.project), snapshot(self.state)
        self.cli('rollback', '--apply', '--yes',
                 env=dict(self.env, ORCHESTRATOR_FAULT='rollback:after-restore'), expected=1)
        self.assertEqual(project, snapshot(self.project))
        self.assertEqual(state, snapshot(self.state))
        self.assertEqual(self.registry()['version'], RELEASE)
        self.cli('rollback', '--apply', '--yes')
        self.assertEqual(self.original_project, snapshot(self.project))

    def test_archive(self):
        self.cli('archive-legacy', '--dry-run', '--to', self.tmp / 'archive', expected=3)
        self.migrate('--apply', '--yes')
        entries = ['.claude/backups/old/note.txt', '.claude/config.backup', '.claude/scripts/old.backup',
                   '.claude/hooks/old.backup', '.claude/orchestration-test.txt', '.claude/persistent-write-test.txt',
                   '.claude/scripts/__pycache__/old.pyc']
        for rel in entries + ['.claude/tracked.backup', '.claude/unknown.txt']:
            p = self.project / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('legacy development data')
            p.chmod(0o640)
        self.run_command(['git', 'add', '-f', '.claude/tracked.backup'], cwd=self.project)
        before = snapshot(self.tmp)
        self.cli('archive-legacy', '--dry-run', '--to', self.project / 'inside', expected=5)
        report = json.loads(self.cli('archive-legacy', '--dry-run', '--to', self.tmp / 'archive').stdout)
        self.assertEqual({e['path'] for e in report['files']}, set(entries))
        self.assertEqual(before, snapshot(self.tmp))
        result = json.loads(self.cli('archive-legacy', '--apply', '--yes', '--to', self.tmp / 'archive').stdout)
        archive = Path(result['archive'])
        manifest = json.loads((archive / 'checksums.json').read_text())
        for rel, expected in manifest['files'].items():
            self.assertEqual(digest(archive / rel), expected)
            self.assertEqual(stat.S_IMODE((archive / rel).stat().st_mode), 0o640)
        for rel in entries:
            self.assertFalse((self.project / rel).exists())
        for rel in ('.claude/tracked.backup', '.claude/unknown.txt', 'AGENTS.md', 'app.txt'):
            self.assertTrue((self.project / rel).exists())
        self.cli('verify')


if __name__ == '__main__':
    unittest.main()
