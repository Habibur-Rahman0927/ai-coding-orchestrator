"""Distribution configuration, signed artifact verification and update dispatch."""
import sys
sys.dont_write_bytecode = True

import contextlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile
import tempfile

import ccx_install as install
import ccx_platform as portable

NAMESPACE = 'claude-codex-orchestrator-release'
SEMVER = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
REPOSITORY = r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}'


def fail(message, code=6):
    raise install.InstallError(message, code)


def config_path():
    return install.canonical_base(portable.config_root()) / 'distribution.json'


def load_config():
    config = install.read_json(config_path())
    if not config:
        fail('Distribution config missing; run distribution configure', 1)
    if not re.fullmatch(REPOSITORY, config.get('repository', '')) or config['repository'].split('/')[1] in ('.', '..'):
        fail('Invalid distribution repository', 1)
    if not isinstance(config.get('require_signature', True), bool):
        fail('Invalid require_signature configuration', 1)
    return config


def distribution(args):
    if args.distribution_action == 'show':
        print(json.dumps(load_config(), indent=2))
        return 0
    if not re.fullmatch(REPOSITORY, args.repository) or args.repository.split('/')[1] in ('.', '..'):
        fail('Repository must be OWNER/REPO', 1)
    path = config_path()
    old = install.read_json(path, {})
    signers = Path(args.allowed_signers).read_bytes() if args.allowed_signers else None
    install.private_mkdir(path.parent)
    portable.secure_mode(str(path.parent), 0o700)
    allowed = path.parent / 'allowed_signers'
    if signers is not None:
        install.atomic_write(allowed, signers)
    config = {'repository': args.repository, 'signer_identity': args.signer_identity or old.get('signer_identity'),
              'require_signature': not args.no_require_signature,
              'allowed_signers': str(allowed) if allowed.exists() else None}
    install.write_json(path, config)
    print(json.dumps(config, indent=2))
    return 0


def artifact_version(tarball):
    match = re.fullmatch(r'claude-codex-orchestrator-(' + SEMVER + r')\.tar\.gz', tarball.name)
    if not match:
        fail('Unexpected artifact filename')
    return match.group(1)


@contextlib.contextmanager
def verify_artifact(tarball, sums, sig, config, allow_unsigned, requested_version=None):
    """Verify and expose an artifact for the duration of a context manager."""
    try:
        with _verify_artifact(tarball, sums, sig, config, allow_unsigned, requested_version) as source:
            yield source
    except (tarfile.TarError, EOFError, OSError, ValueError, TypeError) as error:
        fail('Artifact verification failed: ' + str(error))


@contextlib.contextmanager
def _verify_artifact(tarball, sums, sig, config, allow_unsigned, requested_version=None):
    """Yield a verified source root; delete all extracted data on context exit."""
    # Snapshot external inputs once; no verification step reopens their paths.
    tarball, sums = Path(tarball), Path(sums)
    with install.temporary_directory('ccx-input-') as temporary:
        private = Path(temporary).resolve()
        portable.secure_mode(str(private), 0o700)
        archive_copy = private / tarball.name
        sums_copy = private / 'checksums'
        sig_copy = private / 'signature' if sig is not None else None
        for source, destination in ((tarball, archive_copy), (sums, sums_copy)):
            with source.open('rb') as incoming, destination.open('xb') as outgoing:
                portable.secure_mode(str(destination), 0o600)
                shutil.copyfileobj(incoming, outgoing)
        if sig_copy is not None:
            try:
                with Path(sig).open('rb') as incoming, sig_copy.open('xb') as outgoing:
                    portable.secure_mode(str(sig_copy), 0o600)
                    shutil.copyfileobj(incoming, outgoing)
            except FileNotFoundError:
                sig_copy = None
        with _verify_private_artifact(archive_copy, sums_copy, sig_copy, config,
                                      allow_unsigned, requested_version) as source:
            yield source


@contextlib.contextmanager
def _verify_private_artifact(tarball, sums, sig, config, allow_unsigned, requested_version):
    # Authenticate the checksum document before trusting any of its contents.
    required = config.get('require_signature', True) or not allow_unsigned
    if sig is not None and Path(sig).is_file():
        if not config.get('allowed_signers') or not config.get('signer_identity'):
            fail('Signature verification needs allowed_signers and signer_identity')
        with sums.open('rb') as stream:
            result = subprocess.run(['ssh-keygen', '-Y', 'verify', '-f', config['allowed_signers'],
                                     '-I', config['signer_identity'], '-n', NAMESPACE, '-s', str(sig)],
                                    stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            fail('Release signature verification failed')
    elif required:
        fail('Release signature required')
    matches = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](.+)', line)
        if not match:
            fail('Invalid SHA256SUMS')
        if match.group(2) == tarball.name:
            matches.append(match.group(1).lower())
    if len(matches) != 1 or install.digest(tarball) != matches[0]:
        fail('Artifact SHA256SUMS mismatch')
    version = artifact_version(tarball)
    if requested_version is not None and version != requested_version:
        fail('Artifact does not match requested tag')
    top = 'claude-codex-orchestrator-' + version
    with install.temporary_directory('ccx-verify-') as temporary:
        root = Path(temporary).resolve()
        portable.secure_mode(str(root), 0o700)
        seen = set()
        spellings = {}
        total = 0
        with tarfile.open(str(tarball), 'r:gz') as archive:
            for count, member in enumerate(archive, 1):
                parts = PurePosixPath(member.name).parts
                if (count > 5000 or not parts or parts[0] != top or member.name.startswith('/')
                        or '..' in parts or '\\' in member.name or member.name.rstrip('/') != '/'.join(parts)
                        or not (member.isfile() or member.isdir()) or member.name.rstrip('/') in seen):
                    fail('Unsafe archive member or member count exceeded')
                key = member.name.rstrip('/').casefold()
                if key in seen:
                    fail('Case-colliding archive member')
                seen.add(key)
                for length in range(1, len(parts) + 1):
                    spelling = '/'.join(parts[:length])
                    folded = spelling.casefold()
                    if folded in spellings and spellings[folded] != spelling:
                        fail('Case-colliding archive directory or member')
                    spellings[folded] = spelling
                total += member.size
                if member.size < 0 or total > 100 * 1024 * 1024:
                    fail('Archive size limit exceeded')
                dest = install.target(root, '/'.join(parts))
                if member.isdir():
                    install.private_mkdir(dest)
                else:
                    if len(parts) < 2:
                        fail('Artifact root must be a directory')
                    with archive.extractfile(member) as stream:
                        data = stream.read(member.size + 1)
                    if len(data) != member.size:
                        fail('Truncated archive member')
                    install.atomic_write(dest, data, 0o700 if member.mode & 0o111 else 0o600)
        source = root / top
        manifest = install.read_json(source / 'MANIFEST.json')
        extracted = install.files(source)
        if not isinstance(manifest, dict) or not isinstance(manifest.get('files'), dict):
            fail('Missing or invalid MANIFEST.json')
        if set(manifest['files']) != set(extracted) - {'MANIFEST.json'}:
            fail('MANIFEST.json does not exactly cover artifact')
        install.verify_hashes(source, manifest['files'])
        if manifest.get('version') != version or (source / 'VERSION').read_text(encoding="utf-8").strip() != version:
            fail('Manifest/VERSION does not match requested tag')
        install.verify_source(source)
        yield source


def gh_run(arguments):
    if not shutil.which('gh'):
        fail('gh is required for remote releases', 1)
    result = subprocess.run(['gh'] + arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    if result.returncode:
        fail('gh release command failed; check your gh authentication and repository access', 1)
    return result.stdout


def self_update(args, prefix):
    if args.apply and not args.yes:
        fail('CONFIRMATION_REQUIRED: add --yes', 4)
    config = load_config()
    current = install.code_version(prefix / 'orchestrator.py')
    if args.archive:
        if not args.sums:
            fail('--archive requires --sums', 1)
        version = args.version or artifact_version(Path(args.archive))
    else:
        if args.sums or args.signature:
            fail('--sums and --signature require --archive', 1)
        tags = json.loads(gh_run(['release', 'list', '--repo', config['repository'], '--exclude-drafts',
                                  '--exclude-pre-releases', '--json', 'tagName', '--limit', '50']))
        versions = [t['tagName'][1:] for t in tags if re.fullmatch('v' + SEMVER, t.get('tagName', ''))]
        if not versions:
            fail('No stable engine releases found', 1)
        version = args.version or max(versions, key=install.version_key)
    if not re.fullmatch(SEMVER, version):
        fail('Version must be a stable semantic version', 1)
    if args.check:
        print(json.dumps({'engine_version': current, 'available_version': version,
                          'update_available': install.version_key(version) > install.version_key(current)}, indent=2))
        return 0
    if install.version_key(version) < install.version_key(current) and not args.allow_downgrade:
        fail('Downgrade refused; use --allow-downgrade', 3)
    with install.temporary_directory('ccx-download-') as temporary:
        if args.archive:
            tarball, sums, sig = Path(args.archive), Path(args.sums), args.signature
        else:
            folder = Path(temporary)
            name = 'claude-codex-orchestrator-' + version + '.tar.gz'
            gh_run(['release', 'download', 'v' + version, '--repo', config['repository'], '--dir', str(folder),
                    '--pattern', name, '--pattern', 'SHA256SUMS', '--pattern', 'SHA256SUMS.sig'])
            tarball, sums, sig = folder / name, folder / 'SHA256SUMS', folder / 'SHA256SUMS.sig'
        with verify_artifact(tarball, sums, sig, config, args.allow_unsigned, version) as source:
            receipt = install.read_receipt(prefix) or {}
            bin_dir = receipt.get('bin_dir', str(install.default_bin_dir()))
            command = [sys.executable, '-B', '-I', str(source / 'engine/lib/ccx_install.py'), 'install', '--upgrade',
                       '--prefix', str(prefix), '--bin-dir', bin_dir]
            if args.allow_downgrade:
                command.append('--allow-downgrade')
            if args.dry_run:
                command.append('--dry-run')
            return subprocess.run(command).returncode
