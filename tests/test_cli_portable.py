"""Native end-to-end candidate CLI lifecycle in isolated Unicode directories."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class PortableCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx lifecycle café ')
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.engine = self.base / 'engine'
        self.project = self.base / 'project ü space'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        LOCALAPPDATA=str(self.home / 'local'),
                        XDG_CONFIG_HOME=str(self.home / 'config'),
                        ORCHESTRATOR_CLAUDE_SESSION_ID=str(uuid.uuid4()))
        self.env.pop('ORCHESTRATOR_FAULT', None)
        self.env.pop('ORCHESTRATOR_INSTALL_FAULT', None)
        self.run_command([sys.executable, '-I', str(ROOT / 'engine/lib/ccx_install.py'),
                          'install', '--prefix', str(self.engine), '--bin-dir', str(self.base / 'bin')])
        self.run_command(['git', 'init', '-q', str(self.project)])
        (self.project / 'CLAUDE.md').write_bytes('# Project notes\r\nKeep ü.\r\n'.encode('utf-8'))
        (self.project / '.claude').mkdir()
        self.settings = {'env': {'USER_VALUE': 'preserve'}, 'permissions': {'deny': ['Bash(secret)']}}
        (self.project / '.claude/settings.local.json').write_text(json.dumps(self.settings), encoding='utf-8')
        self.original = (self.project / 'CLAUDE.md').read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, expected=0, stdin=None):
        result = subprocess.run(command, cwd=self.project, env=self.env, input=stdin,
                                capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def cli(self, *args, expected=0):
        return self.run_command([sys.executable, '-B', str(self.engine / 'orchestrator.py'), *args], expected)

    def script(self, name, *args):
        return self.run_command([sys.executable, str(self.project / '.claude/scripts' / name), *args])

    def init(self):
        self.cli('init', '--release', '4.3.0', '--allow-unverified')

    def snapshot(self):
        # Include project, registry, backups and runtime state to catch any write.
        return {str(p.relative_to(self.base)): p.read_bytes() if p.is_file() else None
                for p in self.base.rglob('*')}

    @unittest.skipIf(sys.platform.startswith('linux'), 'requires a real non-Linux host')
    def test_legacy_init_refused_without_writes(self):
        before = self.snapshot()
        for release in (None, '4.0.0', '4.1.0'):
            for dry_run in (False, True):
                with self.subTest(release=release, dry_run=dry_run):
                    args = ['init']
                    if release:
                        args += ['--release', release]
                    if dry_run:
                        args += ['--dry-run']
                    result = self.cli(*args, expected=3)
                    self.assertIn('payload requires Linux', result.stderr)
                    self.assertIn('--release 4.3.0 --allow-unverified', result.stderr)
                    self.assertEqual(self.snapshot(), before)
        self.init()
        self.assertTrue(json.loads(self.cli('verify').stdout)['runtime_compatible'])

    @unittest.skipUnless(sys.platform.startswith('linux'), 'requires a real Linux host')
    def test_linux_legacy_init_still_succeeds(self):
        self.cli('init', '--release', '4.1.0')
        report = json.loads(self.cli('verify').stdout)
        self.assertEqual(report['status'], 'PASS')
        self.assertTrue(report['runtime_compatible'])

    @unittest.skipIf(sys.platform.startswith('linux'), 'requires a real non-Linux host')
    def test_legacy_update_and_adopt_refused_without_writes(self):
        self.init()
        for release in ('4.0.0', '4.1.0'):
            for mode in (['--dry-run'], ['--apply', '--yes']):
                with self.subTest(release=release, mode=mode):
                    before = self.snapshot()
                    result = self.cli('update', '--release', release, *mode, expected=3)
                    self.assertIn('payload requires Linux', result.stderr)
                    self.assertEqual(self.snapshot(), before)
            # Model an existing legacy installation record without installing a
            # Linux-only runtime on this host. Adoption must refuse before checking it.
            config_path = self.project / '.claude/orchestration.json'
            config = json.loads(config_path.read_text(encoding='utf-8'))
            config['version'] = release
            config_path.write_text(json.dumps(config), encoding='utf-8')
            before = self.snapshot()
            self.cli('adopt', expected=3)
            self.assertEqual(self.snapshot(), before)
            # A modified record still has the same integrity failure/exit code.
            raw = subprocess.run(
                [sys.executable, str(self.project / '.claude/scripts/integrity-check.py')],
                cwd=self.project, env=self.env, capture_output=True, text=True, timeout=45)
            report = json.loads(self.cli('verify', expected=raw.returncode).stdout)
            self.assertFalse(report.pop('runtime_compatible'))
            self.assertEqual(report, json.loads(raw.stdout))
            # Seal the fixture's record to also check PASS remains PASS, exit 0.
            manifests = list(self.home.rglob('integrity/manifest.json'))
            self.assertEqual(len(manifests), 1)
            manifest_path = manifests[0]
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['files']['.claude/orchestration.json'] = hashlib.sha256(
                config_path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            report = json.loads(self.cli('verify').stdout)
            self.assertEqual(report['status'], 'PASS')
            self.assertFalse(report['runtime_compatible'])

    def test_complete_project_lifecycle_and_preservation(self):
        self.init()
        self.cli('doctor')
        self.cli('verify')
        self.assertFalse(json.loads(self.script('task-state.py', 'status').stdout)['active'])
        self.assertTrue(json.loads(self.script('task-state.py', 'start').stdout)['active'])
        self.script('task-state.py', 'pause')
        self.script('context-monitor.py')
        self.cli('status', '--all')
        self.cli('projects')
        self.cli('backup')
        backups = list((self.engine / 'backups/projects').glob('*/*-manual'))
        self.assertTrue(backups)
        self.cli('backups')
        self.cli('rollback', '--apply', '--yes', '--backup', backups[0].name)
        self.cli('verify')
        self.cli('uninstall', '--apply', '--yes')
        settings = json.loads((self.project / '.claude/settings.local.json').read_text(encoding='utf-8'))
        self.assertEqual(settings, self.settings)
        # Existing text merging normalizes newlines intentionally; content survives.
        self.assertIn('Keep ü.', (self.project / 'CLAUDE.md').read_text(encoding='utf-8'))
        self.assertFalse((self.project / '.claude/orchestration.json').exists())

    def test_profile_approval_revoked_by_command_change(self):
        (self.project / 'package.json').write_text('{"scripts":{"test":"echo ok"}}', encoding='utf-8')
        self.init()
        self.cli('profile-approve', 'root-test', '--yes')
        profiles = self.project / '.claude/orchestration-profiles.json'
        data = json.loads(profiles.read_text(encoding='utf-8'))
        data['profiles']['root-test']['command'].append('changed')
        profiles.write_text(json.dumps(data), encoding='utf-8')
        result = subprocess.run([sys.executable, str(self.project / '.claude/scripts/managed-exec.py'),
                                 'root-test'], cwd=self.project, env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((self.home / '.local/state/claude-codex').glob('*/managed-executions/*.log')))

    def make_payload_cache(self):
        source = self.project / '.claude/scripts/ccx_platform.py'
        cache = source.parent / '__pycache__'
        cache.mkdir()
        pyc = cache / ('ccx_platform.' + sys.implementation.cache_tag + '.pyc')
        self.run_command([sys.executable, '-B', '-c',
                          'import py_compile,sys; py_compile.compile(sys.argv[1],cfile=sys.argv[2],doraise=True)',
                          str(source), str(pyc)])
        return cache, pyc

    def test_uninstall_removes_only_recognized_payload_bytecode(self):
        self.init()
        cache, pyc = self.make_payload_cache()
        data = pyc.read_bytes()
        plan = json.loads(self.cli('uninstall', '--dry-run').stdout)
        self.assertIn(pyc.relative_to(self.project).as_posix(), plan['remove'])
        self.assertEqual(pyc.read_bytes(), data)
        self.cli('uninstall', '--apply', '--yes')
        self.assertFalse(cache.exists())
        self.assertFalse(cache.parent.exists())
        backups = list((self.engine / 'backups/projects').glob('*/*-pre-uninstall'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'files' / pyc.relative_to(self.project)).read_bytes(), data)

    def test_uninstall_preserves_mixed_cache(self):
        self.init()
        cache, pyc = self.make_payload_cache()
        unrelated = cache / 'user-data.txt'
        unrelated.write_text('keep', encoding='utf-8')
        data = pyc.read_bytes()
        self.cli('uninstall', '--apply', '--yes')
        self.assertEqual(unrelated.read_text(encoding='utf-8'), 'keep')
        self.assertEqual(pyc.read_bytes(), data)

    def test_uninstall_preserves_linked_cache(self):
        self.init()
        outside = self.base / 'outside-cache'
        outside.mkdir()
        marker = outside / 'keep.pyc'
        marker.write_bytes(b'keep')
        cache = self.project / '.claude/scripts/__pycache__'
        try:
            cache.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest('Host does not permit directory symlinks: ' + str(error))
        self.cli('uninstall', '--apply', '--yes')
        self.assertTrue(cache.is_symlink())
        self.assertEqual(marker.read_bytes(), b'keep')

    def test_candidate_commands_use_bytecode_flag(self):
        self.init()
        settings = json.loads((self.project / '.claude/settings.template.json').read_text(encoding='utf-8'))
        for rule in settings['permissions']['allow']:
            if 'python' in rule:
                self.assertIn(' -B .claude/', rule)
        for hooks in settings['hooks'].values():
            for group in hooks:
                for hook in group['hooks']:
                    self.assertIn(' -B "$CLAUDE_PROJECT_DIR/', hook['command'])
        instructions = (self.project / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertIn(' -B .claude/scripts/', instructions)
        self.assertNotIn('python3 .claude/', instructions)
        if os.name == 'nt' and shutil.which('python'):
            self.assertNotIn('python3 ', instructions)

    def test_candidate_requires_explicit_opt_in(self):
        self.cli('init', '--release', '4.3.0', expected=3)
        self.assertFalse((self.project / '.claude/orchestration.json').exists())


if __name__ == '__main__':
    unittest.main()
