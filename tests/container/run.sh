#!/bin/sh
# Build isolated signed fixtures, then run the matrix without host credentials.
set -eu
repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
for tool in docker python3 git ssh-keygen; do
    command -v "$tool" >/dev/null 2>&1 || { echo "Required host tool missing: $tool" >&2; exit 1; }
done
work=$(mktemp -d "${TMPDIR:-/tmp}/ccx-harness.XXXXXX")
work=$(CDPATH= cd -P -- "$work" && pwd -P)
trap 'rm -rf "$work"' 0
trap 'exit 130' INT
trap 'exit 143' TERM
mkdir "$work/public"
ssh-keygen -q -t ed25519 -N '' -f "$work/signing-key"
{ printf 'container-test '; cat "$work/signing-key.pub"; } > "$work/public/allowed_signers"
python3 - "$repo" "$work" <<'PY'
from pathlib import Path
import re
import shutil
import subprocess
import sys
repo, work = map(Path, sys.argv[1:])
for version in ('4.2.0', '4.2.1'):
    source = work / ('source-' + version)
    source.mkdir()
    for name in ('install.sh', 'uninstall.sh', 'install.ps1', 'uninstall.ps1', 'VERSION', 'README.md', 'docs', 'engine'):
        path = repo / name
        if path.is_dir():
            shutil.copytree(path, source / name)
        elif path.exists():
            shutil.copy2(path, source / name)
    (source / 'VERSION').write_text(version + '\n')
    cli = source / 'engine/orchestrator.py'
    text, count = re.subn(r'^ENGINE_VERSION = "[^"]+"$',
                          'ENGINE_VERSION = "' + version + '"', cli.read_text(), flags=re.M)
    if count != 1:
        raise SystemExit('Expected exactly one ENGINE_VERSION assignment')
    cli.write_text(text)
    subprocess.run([sys.executable, '-I', str(repo / 'tools/build_release.py'),
                    '--source', str(source), '--output-dir', str(work / 'public' / version),
                    '--sign-key', str(work / 'signing-key')], check=True)
# Only public artifacts are mounted. Make them readable by the container user.
for path in (work / 'public').rglob('*'):
    path.chmod(0o755 if path.is_dir() else 0o644)
(work / 'public').chmod(0o755)
PY
if [ "$#" -eq 0 ]; then
    set -- ubuntu:20.04 ubuntu:24.04 debian:12 fedora:41 alpine:3.20
fi
failed=0
: > "$work/results"
for image in "$@"; do
    printf '\nRunning %s\n' "$image"
    # Do not mount HOME, config, source checkout, or the private signing key.
    if docker run --rm \
        --mount "type=bind,src=$work/public,dst=/artifacts,readonly" \
        --mount "type=bind,src=$repo/tests/container/scenario.sh,dst=/scenario.sh,readonly" \
        --entrypoint /bin/sh "$image" /scenario.sh "$image"; then
        printf '%s\tPASS\n' "$image" >> "$work/results"
    else
        printf '%s\tFAIL\n' "$image" >> "$work/results"
        failed=1
    fi
done
printf '\nIMAGE\tRESULT\n'
cat "$work/results"
exit "$failed"
