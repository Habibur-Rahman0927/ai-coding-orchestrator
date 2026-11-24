#!/usr/bin/env python3
"""Portable engine distribution operations (Python 3.8+, standard library only).

Directory inode locks avoid persistent lock files and are shared by upgrades and
uninstalls. Receipts describe code, never project registry or runtime state.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


class InstallError(Exception):
    def __init__(self, message, code=3):
        super().__init__(message)
        self.code = code


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_base(path):
    """Resolve ancestors while retaining the base itself as a symlink boundary.

    Path.resolve(strict=False) resolves the nearest existing ancestor and keeps
    missing trailing components, including for a fresh destination.
    """
    path = Path(os.path.abspath(path))
    if path.is_symlink():
        raise InstallError('Refusing symlink: ' + str(path), 5)
    return safe(path.parent.resolve() / path.name)


def safe(path):
    path = Path(os.path.abspath(path))
    for item in (path,) + tuple(path.parents):
        if item.is_symlink():
            raise InstallError('Refusing symlink: ' + str(item), 5)
    return path


def target(base, rel):
    p = Path(rel)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise InstallError('Unsafe relative path: ' + str(rel), 5)
    return safe(base / p)


def files(root):
    safe(root)
    result = {}
    if root.exists():
        for p in sorted(root.rglob('*')):
            safe(p)
            if p.is_file():
                result[p.relative_to(root).as_posix()] = p
            elif not p.is_dir():
                raise InstallError('Non-regular payload: ' + str(p), 5)
    return result


def read_json(path, default=None):
    safe(path)
    return json.loads(path.read_text()) if path.exists() else default


def atomic_write(path, data, mode=0o600):
    path = safe(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ccx-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data.encode() if isinstance(data, str) else data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, str(path))
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_json(path, value):
    atomic_write(path, json.dumps(value, indent=2) + '\n')


def read_receipt(prefix):
    return read_json(prefix / 'install-receipt.json')


def write_receipt(prefix, receipt):
    write_json(prefix / 'install-receipt.json', receipt)


@contextlib.contextmanager
def lock_engine(prefix):
    fd = os.open(str(safe(prefix)), os.O_RDONLY | os.O_DIRECTORY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError('Engine is busy', 75)
        yield
    finally:
        os.close(fd)


def verify_hashes(base, manifest):
    if not isinstance(manifest, dict):
        raise InstallError('Invalid checksum manifest')
    for rel, expected in manifest.items():
        p = target(base, rel)
        if not p.is_file() or digest(p) != expected:
            raise InstallError('Checksum mismatch: ' + str(p), 6)


def engine_payload(src):
    src = canonical_base(src)
    result = {'orchestrator.py': target(src, 'engine/orchestrator.py'),
              'uninstall.sh': target(src, 'uninstall.sh')}
    for folder in ('lib', 'releases'):
        result.update({folder + '/' + k: v for k, v in files(src / 'engine' / folder).items()})
    result.update({'docs/' + k: v for k, v in files(src / 'docs').items()})
    return result


def verify_source(src):
    src = canonical_base(src)
    engine_files = files(src / 'engine')
    payload = engine_payload(src)
    for p in payload.values():
        if not p.is_file():
            raise InstallError('Missing payload: ' + str(p))
    releases = src / 'engine/releases'
    for release in releases.iterdir():
        safe(release)
        if not release.is_dir():
            raise InstallError('Invalid release: ' + str(release))
        verify_hashes(release, read_json(release / 'checksums.json'))
    manifest = read_json(src / 'MANIFEST.json')
    if manifest is not None:
        listing = manifest.get('files', manifest)
        verify_hashes(src, listing)
        for rel in engine_files:
            if 'engine/' + rel not in listing:
                raise InstallError('Unlisted engine file: ' + rel, 6)
    version = (src / 'VERSION').read_text().strip()
    if version != code_version(src / 'engine/orchestrator.py', 'ENGINE_VERSION'):
        raise InstallError('VERSION disagrees with engine')
    return payload


def code_version(path, key='ENGINE_VERSION'):
    if not path.exists():
        return 'legacy'
    match = re.search(r'^' + key + r'\s*=\s*[\'"]([^\'"]+)', path.read_text(), re.M)
    return match.group(1) if match else 'legacy'


def version_key(version):
    if not re.fullmatch(r'\d+(?:\.\d+)*', version):
        raise InstallError('Invalid version: ' + version)
    return tuple(int(p) for p in version.split('.'))


def fault(point):
    if os.environ.get('ORCHESTRATOR_INSTALL_FAULT') == point:
        raise InstallError('Injected fault: ' + point, 1)


def mode(rel):
    return 0o700 if rel in ('orchestrator.py', 'uninstall.sh') else 0o600


def populate(stage, src, payload, bin_dir):
    for rel, source in payload.items():
        atomic_write(target(stage, rel), source.read_bytes(), mode(rel))
    versions = [p.name for p in (stage / 'releases').iterdir()
                if read_json(p / 'release.json', {}).get('status') == 'VERIFIED']
    if not versions:
        raise InstallError('No VERIFIED release')
    write_json(stage / 'current.json', {'version': max(versions, key=version_key)})
    write_json(stage / 'cli-checksums.json', {
        'orchestrator.py': digest(stage / 'orchestrator.py'),
        'cli_version': code_version(stage / 'orchestrator.py', 'CLI_VERSION'),
        'engine_version': code_version(stage / 'orchestrator.py')})
    hashes = {rel: digest(target(stage, rel)) for rel in payload}
    for rel in ('current.json', 'cli-checksums.json'):
        hashes[rel] = digest(stage / rel)
    write_receipt(stage, {'engine_version': code_version(stage / 'orchestrator.py'),
                         'installed_at': datetime.now(timezone.utc).isoformat(),
                         'bin_dir': str(bin_dir),
                         'source_manifest_sha256': digest(src / 'MANIFEST.json') if (src / 'MANIFEST.json').exists() else None,
                         'files': hashes})
    verify_hashes(stage, hashes)


def link_matches(link, prefix, into=False):
    if not link.is_symlink():
        return False
    dest = Path(os.path.abspath(link.parent / os.readlink(str(link))))
    return prefix in dest.parents if into else dest == prefix / 'orchestrator.py'


def atomic_link(link, prefix):
    fd, temp = tempfile.mkstemp(prefix='.ccx-', dir=str(link.parent))
    os.close(fd)
    os.unlink(temp)
    try:
        os.symlink(str(prefix / 'orchestrator.py'), temp)
        os.replace(temp, str(link))
    finally:
        if os.path.lexists(temp):
            os.unlink(temp)


def doctor(prefix):
    subprocess.run([sys.executable, '-I', str(prefix / 'orchestrator.py'), 'doctor'], check=True)


def install(args, src):
    payload = verify_source(src)  # Always before any destination mutation.
    prefix, bin_dir = canonical_base(args.prefix), canonical_base(args.bin_dir)
    link = bin_dir / 'orchestrator'
    if os.path.lexists(str(link)) and not link_matches(link, prefix):
        raise InstallError('Foreign orchestrator executable: ' + str(link))
    if (prefix / 'orchestrator.py').exists() and not args.upgrade:
        raise InstallError('Prefix already exists; use --upgrade')
    if args.upgrade and not (prefix / 'orchestrator.py').is_file():
        raise InstallError('--upgrade requires an installed engine')
    plan = {'operation': 'upgrade' if args.upgrade else 'install', 'prefix': str(prefix),
            'bin_dir': str(bin_dir), 'files': sorted(payload)}
    if args.dry_run:
        print(json.dumps(plan, indent=2))
        return
    created_dirs = []
    stage = None
    saved_prefix = None
    moved = linked = False
    def mkdir(p):
        if not p.exists():
            mkdir(p.parent)
            p.mkdir(mode=0o700)
            created_dirs.append(p)
    locks = contextlib.ExitStack()
    try:
        if args.upgrade:
            locks.enter_context(lock_engine(prefix))
        mkdir(prefix.parent)
        stage = Path(tempfile.mkdtemp(prefix='.ccx-stage-', dir=str(prefix if args.upgrade else prefix.parent)))
        populate(stage, src, payload, bin_dir)
        if prefix.exists() and not args.upgrade:
            # Preserve pre-existing data and unknown files in a fresh destination.
            existing_files = files(prefix)
            for release in (stage / 'releases').iterdir():
                existing = prefix / 'releases' / release.name
                if existing.exists():
                    if (existing / 'checksums.json').read_bytes() != (release / 'checksums.json').read_bytes():
                        raise InstallError('Existing release differs: ' + release.name)
                    shutil.rmtree(release)
                    shutil.copytree(existing, release)
            for rel, source in existing_files.items():
                dest = target(stage, rel)
                if not dest.exists():
                    atomic_write(dest, source.read_bytes(), source.stat().st_mode & 0o777)
            for directory in prefix.rglob('*'):
                if directory.is_dir():
                    target(stage, directory.relative_to(prefix)).mkdir(parents=True, exist_ok=True, mode=0o700)
        fault('after-stage')
        if args.upgrade:
            upgrade(args, prefix, stage, link, mkdir)
        else:
            if not (stage / 'registry/projects.json').exists():
                write_json(stage / 'registry/projects.json', {'projects': {}})
            if prefix.exists():
                saved_prefix = Path(tempfile.mkdtemp(prefix='.ccx-original-', dir=str(prefix.parent)))
                saved_prefix.rmdir()
                os.rename(str(prefix), str(saved_prefix))
            os.rename(str(stage), str(prefix))
            moved = True
            fault('after-move')
            mkdir(bin_dir)
            if not link_matches(link, prefix):
                atomic_link(link, prefix)
                linked = True
            fault('after-link')
            doctor(prefix)
            fault('after-doctor')
    except BaseException:
        if linked:
            link.unlink()
        if moved:
            shutil.rmtree(prefix)
        if saved_prefix is not None and saved_prefix.exists():
            os.rename(str(saved_prefix), str(prefix))
        raise
    finally:
        if saved_prefix is not None and saved_prefix.exists():
            shutil.rmtree(saved_prefix)
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        locks.close()
    if str(bin_dir) not in os.environ.get('PATH', '').split(os.pathsep):
        print('PATH hint: add ' + str(bin_dir) + ' to PATH')


def is_code_path(rel):
    p = Path(rel)
    return (not p.is_absolute() and '..' not in p.parts and bool(p.parts)
            and (p.parts[0] in ('lib', 'docs') or str(p) in (
                'orchestrator.py', 'uninstall.sh', 'cli-checksums.json',
                'current.json', 'install-receipt.json')))


def current_code(prefix):
    old = {}
    for rel in ('orchestrator.py', 'uninstall.sh', 'cli-checksums.json', 'current.json', 'install-receipt.json'):
        p = target(prefix, rel)
        if p.exists():
            old[rel] = p
    old.update({'lib/' + r: p for r, p in files(prefix / 'lib').items()})
    old.update({'docs/' + r: p for r, p in files(prefix / 'docs').items()})
    # Receipt paths are restricted to code to keep user data out of backups.
    receipt = read_receipt(prefix)
    if receipt:
        for rel in receipt['files']:
            if is_code_path(rel) and target(prefix, rel).is_file():
                old[rel] = target(prefix, rel)
    return old


def backup_engine(prefix, old=None):
    """Snapshot and verify code only; caller holds lock_engine(prefix)."""
    if old is None:
        old = current_code(prefix)
    old_version = code_version(prefix / 'orchestrator.py')
    backup_root = target(prefix, 'engine-backups')
    backup_root.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=old_version + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '-', dir=str(backup_root)))
    for rel, p in old.items():
        atomic_write(target(backup, rel), p.read_bytes(), p.stat().st_mode & 0o777)
    checksums = {rel: digest(p) for rel, p in old.items()}
    write_json(backup / 'checksums.json', checksums)
    verify_hashes(backup, checksums)
    return backup


def restore_code(prefix, source, listing, remove):
    for rel in remove:
        if rel not in listing:
            path = target(prefix, rel)
            if path.exists():
                path.unlink()
    for rel in listing:
        path = target(source, rel)
        atomic_write(target(prefix, rel), path.read_bytes(), path.stat().st_mode & 0o777)


def rollback_engine(prefix, apply=False, yes=False):
    prefix = canonical_base(prefix)
    if apply and not yes:
        raise InstallError('CONFIRMATION_REQUIRED: add --yes', 4)
    with lock_engine(prefix):
        folder = target(prefix, 'engine-backups')
        candidates = list(folder.iterdir()) if folder.exists() else []
        if not candidates:
            raise InstallError('No engine backup available', 1)
        for p in candidates:
            safe(p)
        backup = max(candidates, key=lambda p: (p.stat().st_mtime_ns, p.name))
        listing = read_json(backup / 'checksums.json')
        if (not isinstance(listing, dict) or not listing or 'orchestrator.py' not in listing
                or any(not is_code_path(r) for r in listing)
                or set(files(backup)) != set(listing) | {'checksums.json'}):
            raise InstallError('Invalid engine backup manifest', 6)
        verify_hashes(backup, listing)
        print(json.dumps({'operation': 'self-rollback', 'backup': str(backup),
                          'engine_version': code_version(backup / 'orchestrator.py'),
                          'files': sorted(listing)}, indent=2))
        if not apply:
            return 0
        current = current_code(prefix)
        undo = backup_engine(prefix, current)
        try:
            restore_code(prefix, backup, listing, current)
            fault('after-move')
            doctor(prefix)
            fault('after-doctor')
        except BaseException:
            restore_code(prefix, undo, current, listing)
            raise
        return 0


def upgrade(args, prefix, stage, link, mkdir):
    old_version = code_version(prefix / 'orchestrator.py')
    new_version = code_version(stage / 'orchestrator.py')
    if old_version != 'legacy' and version_key(new_version) < version_key(old_version) and not args.allow_downgrade:
        raise InstallError('Downgrade refused; use --allow-downgrade')
    incoming = files(stage)
    for release in (stage / 'releases').iterdir():
        existing = target(prefix, 'releases/' + release.name)
        if existing.exists() and (existing / 'checksums.json').read_bytes() != (release / 'checksums.json').read_bytes():
            raise InstallError('Existing release differs: ' + release.name)
    receipt = read_receipt(prefix)
    if receipt and receipt.get('bin_dir') == str(link.parent) and old_version == new_version and all(target(prefix, r).is_file() and digest(target(prefix, r)) == h for r, h in read_receipt(stage)['files'].items()) and link_matches(link, prefix):
        print('UP_TO_DATE')
        return
    old = current_code(prefix)
    backup = backup_engine(prefix, old)
    added = []
    linked = False
    original_dirs = {p for p in prefix.rglob('*') if p.is_dir()}
    try:
        for rel in old:
            if rel not in incoming:
                target(prefix, rel).unlink()
        for rel, p in incoming.items():
            dest = target(prefix, rel)
            if rel.startswith('releases/') and (prefix / 'releases' / Path(rel).parts[1]).exists():
                # Copy missing release directories as a unit below.
                continue
            if rel.startswith('releases/'):
                continue
            if dest.exists() and rel not in old:
                raise InstallError('Refusing unowned file: ' + rel)
            if not dest.exists():
                added.append(dest)
            atomic_write(dest, p.read_bytes(), mode(rel))
        for release in (stage / 'releases').iterdir():
            dest = target(prefix, 'releases/' + release.name)
            if not dest.exists():
                dest.parent.mkdir(mode=0o700, exist_ok=True)
                added.append(dest)
                shutil.copytree(release, dest)
        fault('after-move')
        mkdir(link.parent)
        if not link_matches(link, prefix):
            atomic_link(link, prefix)
            linked = True
        fault('after-link')
        doctor(prefix)
        fault('after-doctor')
    except BaseException:
        # Recovery is best-effort across every path; preserve the original error.
        recovery_errors = []
        if linked:
            try:
                link.unlink()
            except OSError as error:
                recovery_errors.append(str(error))
        for p in reversed(added):
            try:
                safe(p)
                if p.is_dir() and p not in original_dirs:
                    shutil.rmtree(p)
                elif p.is_file():
                    p.unlink()
            except (OSError, InstallError) as error:
                recovery_errors.append(str(error))
        for rel in old:
            try:
                p = target(backup, rel)
                dest = target(prefix, rel)
                # A newly created directory may occupy an original file's name.
                if dest.is_dir() and dest not in original_dirs:
                    shutil.rmtree(dest)
                atomic_write(dest, p.read_bytes(), p.stat().st_mode & 0o777)
            except (OSError, InstallError) as error:
                recovery_errors.append(str(error))
        for p in sorted(prefix.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if p.is_dir() and p not in original_dirs:
                try:
                    p.rmdir()
                except OSError:
                    pass
        if recovery_errors:
            print('Incomplete recovery; verified backup retained at ' + str(backup), file=sys.stderr)
            for error in recovery_errors:
                print('Recovery error: ' + error, file=sys.stderr)
        raise


def uninstall(args):
    prefix, bin_dir = canonical_base(args.prefix), canonical_base(args.bin_dir)
    if not prefix.exists():
        print(json.dumps({'operation': 'uninstall', 'files': []}))
        if not args.yes:
            raise InstallError('Use --yes to uninstall', 4)
        return
    with lock_engine(prefix):
        receipt = read_receipt(prefix)
        if args.purge and read_json(prefix / 'registry/projects.json', {'projects': {}}).get('projects'):
            raise InstallError('Cannot purge: registered projects remain')
        names = list(receipt['files']) + ['install-receipt.json', 'lib', 'releases', 'engine-backups'] if receipt else [
            'orchestrator.py', 'lib', 'uninstall.sh', 'releases', 'engine-backups',
            'cli-checksums.json', 'current.json', 'install-receipt.json']
        if args.purge:
            names += ['registry', 'backups']
        if receipt and any(Path(name).parts[0] in ('registry', 'backups') for name in receipt['files']):
            raise InstallError('Receipt may not own user data', 5)
        paths = [target(prefix, name) for name in names]
        # Validate whole removable trees before deleting anything.
        for p in paths:
            if p.is_dir():
                files(p)
        unknown = [r for r in files(prefix) if not any(target(prefix, r) == p or p in target(prefix, r).parents for p in paths)]
        link = bin_dir / 'orchestrator'
        print(json.dumps({'operation': 'uninstall', 'prefix': str(prefix), 'files': names,
                          'kept': unknown, 'remove_link': link_matches(link, prefix, True)}, indent=2))
        if args.dry_run or not args.yes:
            raise InstallError('Use --yes to uninstall', 4)
        if link_matches(link, prefix, True):
            link.unlink()
        for p in paths:
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        for p in sorted(prefix.rglob('*'), key=lambda p: len(p.parts), reverse=True):
            if p.is_dir() and p.parts[len(prefix.parts)] not in ('registry', 'backups'):
                try:
                    p.rmdir()
                except OSError:
                    pass
        try:
            prefix.rmdir()
        except OSError:
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('install', 'uninstall'))
    parser.add_argument('--prefix', type=Path)
    parser.add_argument('--bin-dir', type=Path, default=Path.home() / '.local/bin')
    for option in ('dry-run', 'upgrade', 'allow-downgrade', 'yes', 'purge'):
        parser.add_argument('--' + option, action='store_true')
    args = parser.parse_args()
    if args.prefix is None:
        engine_root = Path(__file__).resolve().parents[1]
        if args.operation == 'uninstall' and (engine_root / 'uninstall.sh').is_file():
            args.prefix = engine_root
        else:
            args.prefix = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'claude-codex-orchestrator'
    os.umask(0o077)
    try:
        if args.operation == 'install':
            install(args, Path(__file__).resolve().parents[2])
        else:
            uninstall(args)
        return 0
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return getattr(error, 'code', 1)


if __name__ == '__main__':
    sys.exit(main())
