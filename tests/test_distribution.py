#!/usr/bin/env python3
"""Distribution integration tests; temporary state uses tempfile defaults (including TMPDIR)."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace
import contextlib
import io

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]


def snapshot(path):
    return {str(p.relative_to(path)): ('link', os.readlink(p)) if p.is_symlink() else p.read_bytes()
            for p in path.rglob('*') if p.is_symlink() or p.is_file()}


class Distribution(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='.distribution-'))
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.prefix = self.tmp / 'prefix'
        self.bin = self.tmp / 'bin'
        self.env = dict(os.environ, HOME=str(self.home), TMPDIR=str(self.tmp))
        self.env.pop('ORCHESTRATOR_INSTALL_FAULT', None)
        self.env.pop('XDG_DATA_HOME', None)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_cli(self, *args, action='install', source=ROOT, env=None, expected=0):
        result = subprocess.run(['/bin/sh', str(source / (action + '.sh')), '--prefix', str(self.prefix),
                                 '--bin-dir', str(self.bin)] + list(args), env=env or self.env,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def source(self):
        src = self.tmp / 'source'
        src.mkdir()
        shutil.copytree(ROOT / 'engine', src / 'engine')
        for name in ('install.sh', 'uninstall.sh', 'VERSION'):
            shutil.copy2(ROOT / name, src / name)
        return src

    def test_fresh_spaces_homes_and_init(self):
        for name in ('one', 'two with spaces'):
            self.prefix = self.tmp / name / 'engine with spaces'
            self.bin = self.tmp / name / 'bin with spaces'
            self.home = self.tmp / name / 'home'
            self.home.mkdir(parents=True)
            self.env['HOME'] = str(self.home)
            result = self.run_cli()
            self.assertIn('Engine version: 4.2.0', result.stdout)
            self.assertTrue((self.bin / 'orchestrator').is_symlink())
            project = self.tmp / name / 'project'
            subprocess.run(['git', 'init', '-q', str(project)], check=True, env=self.env)
            result = subprocess.run([str(self.bin / 'orchestrator'), 'init'], cwd=project,
                                    env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((project / '.claude').is_dir())

    def test_duplicate_and_foreign(self):
        self.run_cli()
        before = snapshot(self.tmp)
        self.run_cli(expected=3)
        self.assertEqual(before, snapshot(self.tmp))
        (self.bin / 'orchestrator').unlink()
        (self.bin / 'orchestrator').write_text('foreign')
        before = snapshot(self.tmp)
        self.run_cli('--upgrade', expected=3)
        self.assertEqual(before, snapshot(self.tmp))

    def test_faults_leave_no_trace(self):
        for point in ('after-stage', 'after-move', 'after-link', 'after-doctor'):
            before = sorted(str(p) for p in self.tmp.rglob('*'))
            self.run_cli(env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT=point), expected=1)
            self.assertEqual(before, sorted(str(p) for p in self.tmp.rglob('*')))

    def test_existing_destination_rollback_and_preservation(self):
        self.prefix.mkdir()
        (self.prefix / 'registry').mkdir()
        (self.prefix / 'registry/projects.json').write_text('{"projects": {}}')
        (self.prefix / 'unknown').write_text('keep')
        before = snapshot(self.tmp)
        for point in ('after-stage', 'after-move', 'after-link', 'after-doctor'):
            self.run_cli(env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT=point), expected=1)
            self.assertEqual(before, snapshot(self.tmp))
        self.run_cli()
        self.assertEqual((self.prefix / 'unknown').read_text(), 'keep')
        self.assertEqual((self.prefix / 'registry/projects.json').read_text(), '{"projects": {}}')

    def test_release_conflict(self):
        self.run_cli()
        p = self.prefix / 'releases/4.1.0/checksums.json'
        p.write_text('{}')
        before = snapshot(self.prefix)
        self.run_cli('--upgrade', expected=3)
        self.assertEqual(before, snapshot(self.prefix))

    def test_tampering_and_symlink(self):
        src = self.source()
        release = src / 'engine/releases/4.1.0/VERSION'
        original = release.read_bytes()
        release.write_text('bad')
        self.run_cli(source=src, expected=6)
        release.write_bytes(original)
        (src / 'engine/lib/link').symlink_to(release)
        self.run_cli(source=src, expected=5)
        self.assertFalse(self.prefix.exists())

    def test_manifest(self):
        src = self.source()
        hashes = {r: hashlib.sha256(data).hexdigest() for r, data in snapshot(src).items()}
        (src / 'MANIFEST.json').write_text(json.dumps({'files': hashes}))
        self.run_cli('--dry-run', source=src)
        (src / 'engine/unlisted').write_text('x')
        self.run_cli(source=src, expected=6)

    def test_dry_run(self):
        before = snapshot(self.tmp)
        plan = json.loads(self.run_cli('--dry-run').stdout)
        self.assertEqual(plan['operation'], 'install')
        self.assertEqual(before, snapshot(self.tmp))
        self.assertFalse(self.prefix.exists())

    def legacy(self):
        self.run_cli()
        (self.prefix / 'install-receipt.json').unlink()
        p = self.prefix / 'orchestrator.py'
        p.write_text(p.read_text().replace('ENGINE_VERSION = "4.2.0"', ''))
        (self.prefix / 'backups').mkdir()
        (self.prefix / 'backups/user').write_text('precious')
        (self.prefix / 'registry/projects.json').write_text('{"projects": {"id": {"path": "unavailable"}}}')

    def test_legacy_upgrade_and_backup(self):
        self.legacy()
        preserved = {name: snapshot(self.prefix / name) for name in ('registry', 'backups', 'releases')}
        old = (self.prefix / 'orchestrator.py').read_bytes()
        self.run_cli('--upgrade')
        for name, expected in preserved.items():
            self.assertEqual(expected, snapshot(self.prefix / name))
        backup = next((self.prefix / 'engine-backups').iterdir())
        self.assertTrue(backup.name.startswith('legacy-'))
        self.assertEqual((backup / 'orchestrator.py').read_bytes(), old)
        for rel, expected in json.loads((backup / 'checksums.json').read_text()).items():
            self.assertEqual(hashlib.sha256((backup / rel).read_bytes()).hexdigest(), expected)
        before = snapshot(self.prefix)
        self.assertIn('UP_TO_DATE', self.run_cli('--upgrade').stdout)
        self.assertEqual(before, snapshot(self.prefix))

    def test_upgrade_rollback(self):
        self.legacy()
        before = snapshot(self.prefix)
        for point in ('after-stage', 'after-move', 'after-link', 'after-doctor'):
            self.run_cli('--upgrade', env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT=point), expected=1)
            after = {r: data for r, data in snapshot(self.prefix).items() if not r.startswith('engine-backups/')}
            self.assertEqual(before, after)

    def test_file_to_directory_upgrade_failure_restores(self):
        self.run_cli()
        (self.prefix / 'lib/extensions').write_text('original extension data')
        before = snapshot(self.prefix)
        src = self.source()
        (src / 'engine/lib/extensions').mkdir()
        (src / 'engine/lib/extensions/helper.py').write_text('VALUE = 1\n')
        self.run_cli('--upgrade', source=src,
                     env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT='after-move'), expected=1)
        after = {r: data for r, data in snapshot(self.prefix).items()
                 if not r.startswith('engine-backups/')}
        self.assertEqual(before, after)
        self.assertTrue((self.prefix / 'lib/extensions').is_file())

    def test_upgrade_recovery_continues_after_path_error(self):
        sys.path.insert(0, str(ROOT / 'engine/lib'))
        import ccx_install as installer
        self.run_cli()
        (self.prefix / 'lib/extensions').write_text('original extension data')
        src = self.source()
        (src / 'engine/lib/extensions').mkdir()
        (src / 'engine/lib/extensions/helper.py').write_text('VALUE = 1\n')
        recovering = []
        atomic = installer.atomic_write

        def fail_after_move(point):
            if point == 'after-move':
                recovering.append(True)
                raise installer.InstallError('original failure', 1)

        def restore_with_error(path, data, mode=0o600):
            if recovering and path == self.prefix / 'orchestrator.py':
                raise OSError('simulated per-path restore error')
            return atomic(path, data, mode)

        args = SimpleNamespace(prefix=self.prefix, bin_dir=self.bin, upgrade=True,
                               dry_run=False, allow_downgrade=False)
        errors = io.StringIO()
        with mock.patch.object(installer, 'fault', fail_after_move), mock.patch.object(
                installer, 'atomic_write', restore_with_error), contextlib.redirect_stderr(errors):
            with self.assertRaisesRegex(installer.InstallError, 'original failure'):
                installer.install(args, src)
        self.assertEqual((self.prefix / 'lib/extensions').read_text(), 'original extension data')
        self.assertIn('simulated per-path restore error', errors.getvalue())
        self.assertIn('verified backup retained', errors.getvalue())

    def test_downgrade(self):
        self.run_cli()
        p = self.prefix / 'orchestrator.py'
        p.write_text(p.read_text().replace('ENGINE_VERSION = "4.2.0"', 'ENGINE_VERSION = "9.0.0"'))
        before = snapshot(self.prefix)
        self.run_cli('--upgrade', expected=3)
        self.assertEqual(before, snapshot(self.prefix))
        self.run_cli('--upgrade', '--allow-downgrade')

    def test_uninstall(self):
        self.run_cli()
        state = self.home / '.local/state/claude-codex/session'
        state.parent.mkdir(parents=True)
        state.write_text('keep')
        (self.prefix / 'unknown').write_text('keep')
        before = snapshot(self.tmp)
        self.run_cli(action='uninstall', expected=4)
        self.assertEqual(before, snapshot(self.tmp))
        # Installed shell copy must locate its installed module.
        result = subprocess.run(['/bin/sh', str(self.prefix / 'uninstall.sh'), '--prefix', str(self.prefix),
                                 '--bin-dir', str(self.bin), '--yes'], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.bin / 'orchestrator').exists())
        self.assertTrue((self.prefix / 'registry/projects.json').exists())
        self.assertEqual(state.read_text(), 'keep')
        self.assertEqual((self.prefix / 'unknown').read_text(), 'keep')
        self.run_cli('--yes', '--purge', action='uninstall')
        self.assertFalse((self.prefix / 'registry').exists())

    def test_purge_refuses_registered(self):
        self.legacy()
        before = snapshot(self.tmp)
        self.run_cli('--yes', '--purge', action='uninstall', expected=3)
        self.assertEqual(before, snapshot(self.tmp))
        self.run_cli('--yes', action='uninstall')
        self.assertTrue((self.prefix / 'backups/user').exists())
        self.assertFalse((self.prefix / 'releases').exists())

    def test_lock_and_symlink_prefix(self):
        self.run_cli()
        fd = os.open(self.prefix, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_cli('--upgrade', expected=75)
            self.run_cli('--yes', action='uninstall', expected=75)
        finally:
            os.close(fd)
        real = self.prefix
        self.prefix = self.tmp / 'alias'
        self.prefix.symlink_to(real)
        self.run_cli('--yes', action='uninstall', expected=5)

    def test_default_paths_and_shells(self):
        env = dict(self.env, XDG_DATA_HOME=str(self.home / 'data with spaces'))
        for shell in (['/bin/dash'], [shutil.which('busybox'), 'ash']):
            if not shell[0]:
                continue
            result = subprocess.run(shell + [str(ROOT / 'install.sh'), '--dry-run'],
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(result.stdout)
            self.assertEqual(plan['prefix'], str(self.home / 'data with spaces/claude-codex-orchestrator'))
            self.assertEqual(plan['bin_dir'], str(self.home / '.local/bin'))
        commands = self.tmp / 'tools'
        commands.mkdir()
        for name in ('python3', 'git', 'uname', 'dirname'):
            (commands / name).symlink_to(shutil.which(name))
        result = self.run_cli(env=dict(self.env, PATH=str(commands)))
        self.assertIn('claude: NOT FOUND', result.stdout)
        self.assertIn('codex: NOT FOUND', result.stdout)

    def test_symlinked_parent_paths(self):
        real = self.tmp / 'real home parent'
        real.mkdir()
        alias = self.tmp / 'home parent alias'
        alias.symlink_to(real, target_is_directory=True)
        self.home = alias / 'user'
        self.home.mkdir()
        self.env['HOME'] = str(self.home)
        self.prefix = self.home / 'missing/data/engine'
        self.bin = self.home / 'missing/bin'
        self.run_cli()
        self.assertEqual((self.bin / 'orchestrator').resolve(), self.prefix.resolve() / 'orchestrator.py')
        self.run_cli('--upgrade')
        # A symlink at the base itself is still forbidden.
        original = self.prefix
        self.prefix = self.home / 'engine alias'
        self.prefix.symlink_to(original, target_is_directory=True)
        self.run_cli('--yes', action='uninstall', expected=5)
        self.run_cli('--upgrade', expected=5)
        self.prefix = original
        original_bin = self.bin
        self.bin = self.home / 'bin alias'
        self.bin.symlink_to(original_bin, target_is_directory=True)
        self.run_cli('--yes', action='uninstall', expected=5)
        self.bin = original_bin
        # Symlinks below the prefix remain forbidden too.
        (self.prefix / 'lib/unsafe').symlink_to(self.home)
        self.run_cli('--yes', action='uninstall', expected=5)
        (self.prefix / 'lib/unsafe').unlink()
        self.run_cli('--yes', action='uninstall')
        self.assertTrue((self.prefix / 'registry/projects.json').exists())

    def test_uninstall_removes_upgrade_backups(self):
        self.run_cli()
        src = self.source()
        (src / 'VERSION').write_text('4.3.0\n')
        cli = src / 'engine/orchestrator.py'
        cli.write_text(cli.read_text().replace('ENGINE_VERSION = "4.2.0"', 'ENGINE_VERSION = "4.3.0"'))
        self.run_cli('--upgrade', source=src)
        self.assertTrue(any((self.prefix / 'engine-backups').iterdir()))
        (self.prefix / 'backups').mkdir()
        (self.prefix / 'backups/user').write_text('keep')
        (self.prefix / 'unknown').write_text('keep')
        self.run_cli('--yes', action='uninstall')
        for name in ('lib', 'releases', 'engine-backups'):
            self.assertFalse((self.prefix / name).exists(), name)
        self.assertTrue((self.prefix / 'registry/projects.json').exists())
        self.assertEqual((self.prefix / 'backups/user').read_text(), 'keep')
        self.assertEqual((self.prefix / 'unknown').read_text(), 'keep')

    def test_installed_uninstall_default_prefix(self):
        self.run_cli()
        default = self.home / '.local/share/claude-codex-orchestrator'
        default.mkdir(parents=True)
        (default / 'untouched').write_text('keep')
        result = subprocess.run(['/bin/sh', str(self.prefix / 'uninstall.sh'),
                                 '--bin-dir', str(self.bin), '--yes'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['prefix'], str(self.prefix.resolve()))
        self.assertFalse((self.prefix / 'orchestrator.py').exists())
        self.assertFalse((self.bin / 'orchestrator').is_symlink())
        self.assertTrue((self.prefix / 'registry/projects.json').exists())
        self.assertEqual((default / 'untouched').read_text(), 'keep')

    def test_shell_gates(self):
        commands = self.tmp / 'commands'
        commands.mkdir()
        for name in ('python3', 'uname', 'dirname'):
            (commands / name).symlink_to(shutil.which(name))
        env = dict(self.env, PATH=str(commands))
        self.assertIn('git is required', self.run_cli(env=env, expected=2).stderr)
        (commands / 'git').symlink_to(shutil.which('git'))
        (commands / 'python3').unlink()
        (commands / 'python3').write_text('#!/bin/sh\necho 3.6\nexit 0\n')
        (commands / 'python3').chmod(0o700)
        self.assertIn('3.8', self.run_cli(env=env, expected=2).stderr)
        (commands / 'uname').unlink()
        (commands / 'uname').write_text('#!/bin/sh\necho Darwin\n')
        (commands / 'uname').chmod(0o700)
        self.assertIn('Linux', self.run_cli(env=env, expected=2).stderr)


if __name__ == '__main__':
    unittest.main()
