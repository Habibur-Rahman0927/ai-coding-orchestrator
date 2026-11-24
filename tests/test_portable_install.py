"""Real-host installation tests; no simulated OS claims or agent credentials."""
import json
import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
import ccx_install as install
import ccx_distribution as distribution


class PortableInstall(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ccx portable ')
        self.base = Path(self.temporary.name).resolve()
        self.prefix = self.base / 'engine café space'
        self.bin = self.base / 'bin space'
        self.home = self.base / 'home'
        self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        LOCALAPPDATA=str(self.home / 'AppData/Local'),
                        XDG_DATA_HOME=str(self.home / 'data'),
                        XDG_CONFIG_HOME=str(self.home / 'config'))
        self.env.pop('ORCHESTRATOR_INSTALL_FAULT', None)

    def tearDown(self):
        self.temporary.cleanup()

    def command(self, operation, *args, expected=0, env=None):
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'engine/lib/ccx_install.py'),
                                 operation, '--prefix', str(self.prefix), '--bin-dir', str(self.bin),
                                 *args], env=env or self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def test_install_doctor_upgrade_and_safe_uninstall(self):
        self.command('install')
        launcher = install.launcher_path(self.bin)
        self.assertTrue(launcher.exists())
        result = subprocess.run([str(launcher), 'doctor'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        keep = self.prefix / 'registry/user-note'
        keep.write_text('preserve me', encoding='utf-8')
        self.command('install', '--upgrade')
        self.command('uninstall', '--yes')
        self.assertEqual(keep.read_text(), 'preserve me')
        self.assertFalse(launcher.exists())
        self.assertFalse((self.prefix / 'orchestrator.py').exists())

    def test_failed_install_rolls_back(self):
        self.command('install', expected=1,
                     env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT='after-link'))
        self.assertFalse(self.prefix.exists())
        self.assertFalse(install.launcher_path(self.bin).exists())

    def test_engine_upgrade_and_self_rollback_preserve_user_data(self):
        self.command('install')
        note = self.prefix / 'registry/user-note'
        note.write_text('keep across engine upgrades', encoding='utf-8')
        source = self.base / 'upgrade-source'
        shutil.copytree(ROOT / 'engine', source / 'engine')
        for name in ('install.sh', 'uninstall.sh', 'install.ps1', 'uninstall.ps1', 'VERSION'):
            shutil.copy2(ROOT / name, source / name)
        original = (source / 'engine/orchestrator.py').read_text(encoding='utf-8')
        version = (source / 'VERSION').read_text().strip()
        new_version = '99.0.0'
        (source / 'VERSION').write_text(new_version + '\n', encoding='utf-8')
        (source / 'engine/orchestrator.py').write_text(
            original.replace('ENGINE_VERSION = "' + version + '"',
                             'ENGINE_VERSION = "' + new_version + '"'), encoding='utf-8')
        result = subprocess.run([sys.executable, '-I', str(source / 'engine/lib/ccx_install.py'),
                                 'install', '--upgrade', '--prefix', str(self.prefix),
                                 '--bin-dir', str(self.bin)], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(install.code_version(self.prefix / 'orchestrator.py'), new_version)
        result = subprocess.run([sys.executable, '-I', str(self.prefix / 'orchestrator.py'),
                                 'self-rollback', '--apply', '--yes'], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(install.code_version(self.prefix / 'orchestrator.py'), version)
        self.assertEqual(note.read_text(), 'keep across engine upgrades')

    def test_dry_run_reports_actual_platform_without_installing(self):
        report = json.loads(self.command('install', '--dry-run').stdout)
        self.assertIn('architecture', report)
        self.assertIn('git', report['tools'])
        self.assertFalse(self.prefix.exists())

    def test_foreign_launcher_preserved(self):
        self.bin.mkdir()
        launcher = install.launcher_path(self.bin)
        launcher.write_text('foreign executable', encoding='utf-8')
        self.command('install', expected=3)
        self.assertEqual(launcher.read_text(), 'foreign executable')

    def test_platform_independent_archive_path_rejection(self):
        for rel in ('../escape', 'C:/escape', 'C:escape', '//host/share', 'NUL',
                    'a/file:stream', 'trailing.', 'a/CON.txt'):
            with self.subTest(path=rel), self.assertRaises(install.InstallError):
                install.target(self.base, rel)

    def test_windows_launcher_is_quoted_and_literal(self):
        # This checks emitted source only; executing it requires the Windows job.
        launcher = install.windows_launcher(self.base / 'percent% bang! & space').decode('utf-8')
        self.assertIn('DisableDelayedExpansion', launcher)
        self.assertIn('percent%% bang! & space', launcher)
        self.assertIn('" %*\r\n', launcher)

    def test_archive_rejects_case_aliases_and_windows_special_names(self):
        top = 'claude-codex-orchestrator-4.3.0'
        archive = self.base / (top + '.tar.gz')
        sums = self.base / 'SHA256SUMS'
        for names in (['NUL.txt'], ['C:stream'], ['Case', 'case'], ['Dir/a', 'dir/b']):
            with self.subTest(names=names):
                with tarfile.open(archive, 'w:gz') as output:
                    for name in names:
                        entry = tarfile.TarInfo(top + '/' + name)
                        entry.size = 1
                        output.addfile(entry, io.BytesIO(b'x'))
                sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest()
                                + '  ' + archive.name + '\n', encoding='utf-8')
                with self.assertRaises(install.InstallError):
                    with distribution.verify_artifact(archive, sums, None,
                                                       {'require_signature': False}, True):
                        self.fail('Unsafe archive accepted')

    @unittest.skipUnless(shutil.which('ssh-keygen'), 'OpenSSH signature support required')
    def test_signed_release_round_trip_and_tamper(self):
        key = self.base / 'test-signing-key'
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)],
                       check=True, capture_output=True)
        allowed = self.base / 'allowed_signers'
        allowed.write_text('portable-test ' + Path(str(key) + '.pub').read_text(), encoding='utf-8')
        output = self.base / 'release'
        build = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/build_release.py'),
                                '--output-dir', str(output), '--sign-key', str(key)],
                               capture_output=True, text=True)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        archive = next(output.glob('*.tar.gz'))
        config = {'allowed_signers': str(allowed), 'signer_identity': 'portable-test',
                  'require_signature': True}
        with distribution.verify_artifact(archive, output / 'SHA256SUMS',
                                           output / 'SHA256SUMS.sig', config, False) as source:
            self.assertTrue((source / 'engine/orchestrator.py').is_file())
        archive.write_bytes(archive.read_bytes() + b'tamper')
        with self.assertRaises(install.InstallError):
            with distribution.verify_artifact(archive, output / 'SHA256SUMS',
                                               output / 'SHA256SUMS.sig', config, False):
                self.fail('Tampered signed release accepted')


if __name__ == '__main__':
    unittest.main()
