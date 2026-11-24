#!/usr/bin/env python3
"""Build a reproducible, allowlisted engine distribution, optionally SSH-signed."""
import sys
sys.dont_write_bytecode = True

import argparse
import fnmatch
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine/lib'))
import ccx_platform as portable
from ccx_install import InstallError, code_version, verify_source, atomic_write, safe, target


def build(source, output, key=None):
    # Normalize caller-selected roots once, including macOS /var and /tmp.
    # Descendants stay lexical so safe/target can still reject planted links.
    source = safe(Path(os.path.realpath(source)))
    output = safe(Path(os.path.realpath(output)))
    if key is not None:
        public = safe(Path(os.path.realpath(str(key) + '.pub')))
        key = safe(Path(os.path.realpath(key)))
        # Retain the caller's public-key alias check as well as the public key
        # beside the normalized private key used by ssh-keygen.
        effective_public = safe(Path(os.path.realpath(str(key) + '.pub')))
        for candidate in (key, public, effective_public):
            if candidate == source or source in candidate.parents:
                raise InstallError('Signing key and public key must be outside the source tree', 6)
    payload = {}
    spellings = {}
    for name in ('install.sh', 'uninstall.sh', 'install.ps1', 'uninstall.ps1', 'VERSION', 'README.md', 'docs', 'engine'):
        root = source / name
        if not root.exists() and not root.is_symlink():
            if name in ('README.md', 'docs', 'install.ps1', 'uninstall.ps1'):
                continue
            raise InstallError('Missing required source: ' + name, 6)
        for path in [root] + (sorted(root.rglob('*')) if root.is_dir() else []):
            rel = path.relative_to(source).as_posix()
            portable.validate_relative(rel)
            folded = rel.casefold()
            if folded in spellings and spellings[folded] != rel:
                raise InstallError('Case-colliding distribution path: ' + rel, 6)
            spellings[folded] = rel
            parts = Path(rel).parts
            forbidden = ('*.jsonl', 'auth.json', '.credentials*', 'config.toml', '*.pem',
                         'id_rsa*', 'id_ed25519*', '.env*')
            if (portable.is_link(path) or any(p in ('registry', 'backups', 'engine-backups', 'test-reports', '__pycache__') for p in parts)
                    or any(fnmatch.fnmatch(p, pattern) for p in parts for pattern in forbidden)
                    or re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\.json', path.name)):
                raise InstallError('Forbidden distribution path: ' + rel, 6)
            if path.is_dir():
                continue
            if not path.is_file():
                raise InstallError('Non-regular distribution file: ' + rel, 6)
            data = path.read_bytes()
            if re.search(rb'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----', data):
                raise InstallError('Private key material in: ' + rel, 6)
            if re.search(rb'/(?:home|Users)/[^/\s]+/', data):
                raise InstallError('Private absolute path in: ' + rel, 6)
            payload[rel] = data
    version = payload['VERSION'].decode().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or version != code_version(source / 'engine/orchestrator.py'):
        raise InstallError('VERSION disagrees with ENGINE_VERSION or is not semver', 6)
    verify_source(source)
    manifest = {'version': version, 'files': {r: hashlib.sha256(data).hexdigest() for r, data in sorted(payload.items())}}
    payload['MANIFEST.json'] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    top = 'claude-codex-orchestrator-' + version
    tarball = target(output, top + '.tar.gz')
    sums = target(output, 'SHA256SUMS')
    sig = target(output, 'SHA256SUMS.sig')
    output.mkdir(parents=True, exist_ok=True)
    # Empty gzip filename and zero timestamps make the complete archive reproducible.
    buffer = io.BytesIO()
    with gzip.GzipFile(filename='', mode='wb', fileobj=buffer, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for rel, data in sorted(payload.items()):
                info = tarfile.TarInfo(top + '/' + rel)
                info.size = len(data)
                info.mode = 0o755 if rel.endswith('.sh') or rel == 'engine/orchestrator.py' else 0o644
                info.mtime = info.uid = info.gid = 0
                info.uname = info.gname = ''
                archive.addfile(info, io.BytesIO(data))
    atomic_write(tarball, buffer.getvalue(), 0o644)
    atomic_write(sums, hashlib.sha256(buffer.getvalue()).hexdigest() + '  ' + tarball.name + '\n', 0o644)
    safe(sig)
    if sig.exists():
        sig.unlink()
    if key:
        subprocess.run(['ssh-keygen', '-Y', 'sign', '-f', str(key), '-n',
                        'claude-codex-orchestrator-release', str(sums)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(tarball)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output-dir', type=Path)
    parser.add_argument('--sign-key', type=Path)
    args = parser.parse_args()
    try:
        build(args.source, args.output_dir or args.source / 'dist', args.sign_key)
        return 0
    except (InstallError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Release build refused: ' + str(error), file=sys.stderr)
        return 6


if __name__ == '__main__':
    sys.exit(main())
