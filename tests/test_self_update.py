#!/usr/bin/env python3
"""Signed distribution integration tests; no live GitHub access."""
import fcntl
import hashlib
import gzip
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = 'release-test'


def snapshot(root):
    return {str(p.relative_to(root)): ('link', os.readlink(p)) if p.is_symlink() else p.read_bytes()
            for p in root.rglob('*') if p.is_symlink() or p.is_file()}


def run(command, env=None, cwd=None, expected=0):
    result = subprocess.run([str(x) for x in command], env=env, cwd=cwd, capture_output=True, text=True)
    if result.returncode != expected:
        raise AssertionError('Unexpected exit %s, expected %s:\n%s\n%s' %
                             (result.returncode, expected, result.stdout, result.stderr))
    return result


def sign(sums, key):
    sig = sums.parent / 'SHA256SUMS.sig'
    if sig.exists():
        sig.unlink()
    run(['ssh-keygen', '-Y', 'sign', '-f', key, '-n', 'claude-codex-orchestrator-release', sums])


class SelfUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory(prefix='ccx-artifacts-')
        cls.root = Path(cls.shared.name).resolve()
        cls.key = cls.root / 'signing-key'
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', cls.key])
        cls.signers = cls.root / 'signers'
        cls.signers.write_text(IDENTITY + ' ' + cls.key.with_suffix('.pub').read_text())
        cls.sources = {}
        cls.artifacts = {}
        for version in ('4.2.0', '4.2.1'):
            src = cls.root / ('source-' + version)
            src.mkdir()
            for folder in ('engine', 'docs', 'tools', 'scripts'):
                shutil.copytree(ROOT / folder, src / folder)
            for name in ('VERSION', 'install.sh', 'uninstall.sh'):
                shutil.copy2(ROOT / name, src / name)
            (src / 'VERSION').write_text(version + '\n')
            cli = src / 'engine/orchestrator.py'
            cli.write_text(re.sub(r'^ENGINE_VERSION = "[^"]+"$', 'ENGINE_VERSION = "' + version + '"', cli.read_text(), flags=re.M))
            run([sys.executable, '-I', src / 'tools/build_release.py', '--sign-key', cls.key])
            cls.sources[version] = src
            cls.artifacts[version] = src / 'dist'

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-update-test-')
        self.tmp = Path(self.temp.name).resolve()
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.prefix = self.tmp / 'engine'
        self.bin = self.tmp / 'bin'
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE="1", XDG_CONFIG_HOME=str(self.home / 'config'), TMPDIR=str(self.tmp))
        self.env.pop('ORCHESTRATOR_INSTALL_FAULT', None)
        run(['/bin/sh', self.sources['4.2.0'] / 'install.sh', '--prefix', self.prefix, '--bin-dir', self.bin], env=self.env)
        self.configure()
        self.project = self.tmp / 'project'
        run(['git', 'init', '-q', self.project], env=self.env)
        self.cli('init', cwd=self.project)
        self.state = self.home / '.local/state/claude-codex/fake/session.json'
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text('{"state":"keep"}')
        (self.prefix / 'backups').mkdir(exist_ok=True)
        (self.prefix / 'backups/project-data').write_text('keep')

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0, env=None, cwd=None):
        return run([sys.executable, '-I', self.prefix / 'orchestrator.py'] + list(args),
                   expected=expected, env=env or self.env, cwd=cwd)

    def configure(self, unsigned=False):
        args = ['distribution', 'configure', '--repository', 'example/orchestrator', '--allowed-signers',
                str(self.signers), '--signer-identity', IDENTITY]
        if unsigned:
            args.append('--no-require-signature')
        return self.cli(*args)

    def update(self, *args, version='4.2.1', directory=None, signature=True, expected=0, env=None):
        directory = directory or self.artifacts[version]
        command = ['self-update', '--archive', str(directory / ('claude-codex-orchestrator-' + version + '.tar.gz')),
                   '--sums', str(directory / 'SHA256SUMS')]
        if signature:
            command += ['--signature', str(directory / 'SHA256SUMS.sig')]
        return self.cli(*(command + list(args)), expected=expected, env=env)

    def protected(self):
        return {name: snapshot(path) for name, path in (
            ('registry', self.prefix / 'registry'), ('backups', self.prefix / 'backups'),
            ('releases', self.prefix / 'releases'), ('project', self.project), ('state', self.state.parent))}

    def code(self):
        return {r: data for r, data in snapshot(self.prefix).items() if not r.startswith('engine-backups/')}

    def version(self):
        return json.loads(self.cli('versions').stdout)['engine_version']

    def test_config_and_plans(self):
        config = json.loads(self.cli('distribution', 'show').stdout)
        path = self.home / 'config/claude-codex-orchestrator/distribution.json'
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        allowed = Path(config['allowed_signers'])
        self.assertNotEqual(allowed, self.signers)
        self.assertEqual(allowed.read_bytes(), self.signers.read_bytes())
        self.assertEqual(allowed.stat().st_mode & 0o777, 0o600)
        before = snapshot(self.tmp)
        self.cli('distribution', 'configure', '--repository', '../bad', expected=1)
        self.update('--check')
        self.update('--dry-run')
        self.update('--apply', expected=4)
        self.assertEqual(before, snapshot(self.tmp))
        self.cli('self-rollback', '--check', expected=1)

    def test_apply_noop_downgrade_and_protected_data(self):
        protected = self.protected()
        self.update('--apply', '--yes')
        self.assertEqual(self.version(), '4.2.1')
        self.assertEqual(protected, self.protected())
        receipt = json.loads((self.prefix / 'install-receipt.json').read_text())
        self.assertEqual(receipt['bin_dir'], str(self.bin))
        before = snapshot(self.tmp)
        self.assertIn('UP_TO_DATE', self.update('--apply', '--yes').stdout)
        self.update('--apply', '--yes', version='4.2.0', expected=3)
        self.assertEqual(before, snapshot(self.tmp))

    def fake_gh(self):
        tools = self.tmp / 'tools'
        tools.mkdir()
        gh = tools / 'gh'
        gh.write_text('#!' + sys.executable + '\n' + '''import json, pathlib, shutil, sys
args = sys.argv[1:]
assert '--repo' in args and args[args.index('--repo') + 1] == 'example/orchestrator'
if args[:2] == ['release', 'list']:
    assert '--exclude-drafts' in args and '--exclude-pre-releases' in args
    print(json.dumps([{'tagName': 'v4.2.0'}, {'tagName': 'v4.2.1'}, {'tagName': 'v4.3.0-rc1'}]))
elif args[:2] == ['release', 'download']:
    assert args[2] == 'v4.2.1'
    dest = pathlib.Path(args[args.index('--dir') + 1])
    for i, arg in enumerate(args):
        if arg == '--pattern':
            shutil.copy2(pathlib.Path(SOURCE) / args[i+1], dest / args[i+1])
else:
    sys.exit(2)
'''.replace('SOURCE', repr(str(self.artifacts['4.2.1']))))
        gh.chmod(0o700)
        return dict(self.env, PATH=str(tools) + os.pathsep + os.environ['PATH'])

    def test_remote_via_gh(self):
        env = self.fake_gh()
        before = snapshot(self.tmp)
        check = json.loads(self.cli('self-update', '--check', env=env).stdout)
        self.assertEqual(check['available_version'], '4.2.1')
        self.assertEqual(before, snapshot(self.tmp))
        self.cli('self-update', '--apply', '--yes', env=env)
        self.assertEqual(self.version(), '4.2.1')

    def test_missing_config_or_gh(self):
        config = self.home / 'config/claude-codex-orchestrator/distribution.json'
        data = config.read_bytes()
        config.unlink()
        self.cli('self-update', '--check', expected=1)
        config.write_bytes(data)
        empty = self.tmp / 'empty-path'
        empty.mkdir()
        self.cli('self-update', '--check', env=dict(self.env, PATH=str(empty)), expected=1)

    def artifact_copy(self):
        directory = self.tmp / 'artifact'
        shutil.copytree(self.artifacts['4.2.1'], directory)
        return directory

    def test_tampered_archive_and_sums(self):
        directory = self.artifact_copy()
        archive = directory / 'claude-codex-orchestrator-4.2.1.tar.gz'
        original = archive.read_bytes()
        before = snapshot(self.prefix)
        archive.write_bytes(original + b'bad')
        self.update('--apply', '--yes', directory=directory, expected=6)
        archive.write_bytes(original)
        sums = directory / 'SHA256SUMS'
        sums.write_text('0' * 64 + '  ' + archive.name + '\n')
        sign(sums, self.key)
        self.update('--apply', '--yes', directory=directory, expected=6)
        self.assertEqual(before, snapshot(self.prefix))

    def test_unknown_key_and_missing_signature(self):
        directory = self.artifact_copy()
        key = self.tmp / 'unknown-key'
        run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', key])
        sign(directory / 'SHA256SUMS', key)
        before = snapshot(self.prefix)
        self.update('--apply', '--yes', directory=directory, expected=6)
        self.update('--apply', '--yes', signature=False, expected=6)
        self.update('--apply', '--yes', '--allow-unsigned', signature=False, expected=6)
        self.assertEqual(before, snapshot(self.prefix))

    def test_unsigned_requires_both_controls(self):
        self.configure(unsigned=True)
        before = snapshot(self.prefix)
        self.update('--apply', '--yes', signature=False, expected=6)
        self.assertEqual(before, snapshot(self.prefix))
        self.update('--apply', '--yes', '--allow-unsigned', signature=False)
        self.assertEqual(self.version(), '4.2.1')

    def malicious(self, directory, kind):
        archive = directory / 'claude-codex-orchestrator-4.2.1.tar.gz'
        with tarfile.open(archive, 'r:gz') as handle:
            entries = [(m, handle.extractfile(m).read()) for m in handle if m.isfile()]
        with tarfile.open(archive, 'w:gz') as handle:
            for member, data in entries:
                handle.addfile(member, io.BytesIO(data))
            member = tarfile.TarInfo('claude-codex-orchestrator-4.2.1/' + ('../escape' if kind == 'traversal' else 'extra'))
            if kind == 'symlink':
                member.type = tarfile.SYMTYPE
                member.linkname = '../../escape'
                handle.addfile(member)
            else:
                member.size = 1
                handle.addfile(member, io.BytesIO(b'x'))
        sums = directory / 'SHA256SUMS'
        sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
        sign(sums, self.key)

    def test_unsafe_archive_members_and_manifest(self):
        for kind in ('traversal', 'symlink', 'extra'):
            with self.subTest(kind=kind):
                directory = self.artifact_copy()
                self.malicious(directory, kind)
                before = snapshot(self.tmp)
                self.update('--apply', '--yes', directory=directory, expected=6)
                self.assertEqual(before, snapshot(self.tmp))
                shutil.rmtree(directory)

    def test_archive_limits_invalid_format_and_requested_tag(self):
        directory = self.artifact_copy()
        archive = directory / 'claude-codex-orchestrator-4.2.1.tar.gz'
        before = snapshot(self.prefix)
        self.update('--apply', '--yes', '--version', '4.2.2', directory=directory, expected=6)
        for kind in ('size', 'count', 'invalid'):
            if kind == 'size':
                member = tarfile.TarInfo('claude-codex-orchestrator-4.2.1/huge')
                member.size = 100 * 1024 * 1024 + 1
                data = member.tobuf() + b'\0' * 1024
            elif kind == 'count':
                chunks = []
                for i in range(5001):
                    member = tarfile.TarInfo('claude-codex-orchestrator-4.2.1/dir%d' % i)
                    member.type = tarfile.DIRTYPE
                    chunks.append(member.tobuf())
                data = b''.join(chunks) + b'\0' * 1024
            else:
                data = b'not a tar archive'
            archive.write_bytes(gzip.compress(data))
            sums = directory / 'SHA256SUMS'
            sums.write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name + '\n')
            sign(sums, self.key)
            self.update('--apply', '--yes', directory=directory, expected=6)
            self.assertEqual(before, snapshot(self.prefix))

    def test_verification_snapshots_external_inputs_once(self):
        sys.path.insert(0, str(ROOT / 'engine/lib'))
        import ccx_distribution as distribution
        directory = self.artifact_copy()
        archive = directory / 'claude-codex-orchestrator-4.2.1.tar.gz'
        sums, sig = directory / 'SHA256SUMS', directory / 'SHA256SUMS.sig'
        inputs = {archive: 0, sums: 0, sig: 0}
        original_open = Path.open
        original_verify = distribution._verify_private_artifact
        config = {'require_signature': True, 'allowed_signers': str(self.signers),
                  'signer_identity': IDENTITY}

        def counted_open(path, *args, **kwargs):
            if path in inputs:
                inputs[path] += 1
                self.assertEqual(inputs[path], 1, 'External input reopened')
            return original_open(path, *args, **kwargs)

        def replace_originals(*args, **kwargs):
            for path in inputs:
                with original_open(path, 'wb') as stream:
                    stream.write(b'replaced after snapshot')
            for path in args[:3]:
                self.assertNotIn(path, inputs)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return original_verify(*args, **kwargs)

        with mock.patch.object(Path, 'open', counted_open), mock.patch.object(
                distribution, '_verify_private_artifact', replace_originals):
            with distribution.verify_artifact(archive, sums, sig, config, False, '4.2.1') as source:
                self.assertEqual((source / 'VERSION').read_text(), '4.2.1\n')
        self.assertEqual(list(inputs.values()), [1, 1, 1])

    def test_build_rejects_private_material_and_in_tree_signers(self):
        src = self.tmp / 'source'
        shutil.copytree(self.sources['4.2.0'], src)
        planted = src / 'engine/release-key'
        for label in ('OPENSSH', 'RSA', 'EC', 'ENCRYPTED'):
            planted.write_text('-----BEGIN ' + label + ' PRIVATE KEY-----\nsynthetic fixture\n')
            run([sys.executable, '-I', src / 'tools/build_release.py'], expected=6)
        planted.unlink()
        # Location checks must reject keys even outside the packaged allowlist.
        local_key = src / 'unpackaged-signing-key'
        local_key.write_text('synthetic placeholder')
        run([sys.executable, '-I', src / 'tools/build_release.py', '--sign-key', local_key], expected=6)
        alias = self.tmp / 'key-alias'
        alias.symlink_to(local_key)
        run([sys.executable, '-I', src / 'tools/build_release.py', '--sign-key', alias], expected=6)
        alias.unlink()
        alias.symlink_to(self.key)
        public = src / 'public-key'
        public.write_text(self.key.with_suffix('.pub').read_text())
        Path(str(alias) + '.pub').symlink_to(public)
        run([sys.executable, '-I', src / 'tools/build_release.py', '--sign-key', alias], expected=6)

    def test_apply_failure_restores(self):
        before, protected = self.code(), self.protected()
        for point in ('after-stage', 'after-move', 'after-link', 'after-doctor'):
            self.update('--apply', '--yes', env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT=point), expected=1)
            self.assertEqual(before, self.code())
            self.assertEqual(protected, self.protected())

    def test_rollback_reversible_and_failure(self):
        protected = self.protected()
        self.update('--apply', '--yes')
        before = snapshot(self.tmp)
        self.cli('self-rollback', '--check')
        self.cli('self-rollback', '--dry-run')
        self.cli('self-rollback', '--apply', expected=4)
        self.assertEqual(before, snapshot(self.tmp))
        self.cli('self-rollback', '--apply', '--yes')
        self.assertEqual(self.version(), '4.2.0')
        self.cli('self-rollback', '--apply', '--yes')
        self.assertEqual(self.version(), '4.2.1')
        before = self.code()
        self.cli('self-rollback', '--apply', '--yes', env=dict(self.env, ORCHESTRATOR_INSTALL_FAULT='after-move'), expected=1)
        self.assertEqual(before, self.code())
        self.assertEqual(protected, self.protected())

    def test_lock_busy_and_bad_backup(self):
        self.update('--apply', '--yes')
        fd = os.open(self.prefix, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.update('--apply', '--yes', expected=75)
            self.cli('self-rollback', '--apply', '--yes', expected=75)
        finally:
            os.close(fd)
        backup = next((self.prefix / 'engine-backups').iterdir())
        (backup / 'orchestrator.py').write_text('tampered')
        before = snapshot(self.prefix)
        self.cli('self-rollback', '--apply', '--yes', expected=6)
        self.assertEqual(before, snapshot(self.prefix))

    def test_build_deterministic_and_forbidden(self):
        src = self.tmp / 'source'
        shutil.copytree(self.sources['4.2.0'], src)
        artifact = src / 'dist/claude-codex-orchestrator-4.2.0.tar.gz'
        first = hashlib.sha256(artifact.read_bytes()).hexdigest()
        run(['/bin/sh', src / 'scripts/build-release.sh'])
        self.assertEqual(first, hashlib.sha256(artifact.read_bytes()).hexdigest())
        for rel, data in (('engine/registry/x.json', '{}'), ('docs/private.txt', '/home/someone/private'),
                          ('engine/auth.json', '{}')):
            path = src / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
            run([sys.executable, '-I', src / 'tools/build_release.py'], expected=6)
            path.unlink()
            if path.parent.name == 'registry':
                path.parent.rmdir()
        (src / 'VERSION').write_text('9.9.9\n')
        run([sys.executable, '-I', src / 'tools/build_release.py'], expected=6)


if __name__ == '__main__':
    unittest.main()
