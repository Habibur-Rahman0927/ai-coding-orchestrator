#!/bin/sh
# Root bootstraps packages/account; all engine/project operations run unprivileged.
set -eu
if [ "${1:-}" != --user ]; then
    image=${1:?image label required}
    [ "$(id -u)" -eq 0 ] || { echo 'Bootstrap must run as root' >&2; exit 1; }
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            python3 git openssh-client make ca-certificates tar gzip coreutils passwd util-linux
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y python3 git openssh-clients make ca-certificates tar gzip coreutils shadow-utils util-linux
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache python3 git openssh-client make ca-certificates tar gzip coreutils
    else
        echo 'Unsupported package manager' >&2
        exit 1
    fi
    mkdir -p '/srv/team home'
    if command -v useradd >/dev/null 2>&1; then
        useradd -m -d '/srv/team home/teammate' -s /bin/sh teammate
    else
        adduser -D -h '/srv/team home/teammate' -s /bin/sh teammate
    fi
    # No network operations occur after this point. The private key is not mounted.
    export CONTAINER_IMAGE="$image"
    exec su -s /bin/sh -c 'exec /bin/sh /scenario.sh --user' teammate
fi
[ "$(id -u)" -ne 0 ] || { echo 'Scenario must run as non-root' >&2; exit 1; }
[ "$(id -un)" = teammate ]
[ "$HOME" = '/srv/team home/teammate' ]
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin"
umask 077
# Use installed Python rather than grep/diffutils for assertions.
assert_contains() {
    python3 - "$1" "$2" <<'PYTHON'
from pathlib import Path
import sys
if sys.argv[2] not in Path(sys.argv[1]).read_text():
    sys.exit('Expected text missing from ' + sys.argv[1])
PYTHON
}
assert_same() {
    python3 - "$1" "$2" <<'PYTHON'
from pathlib import Path
import sys
if Path(sys.argv[1]).read_bytes() != Path(sys.argv[2]).read_bytes():
    sys.exit('Preservation check failed: snapshot listings differ')
PYTHON
}
cd "$HOME"
mkdir work
cd work
for version in 4.2.0 4.2.1; do
    (
        cd "/artifacts/$version"
        ssh-keygen -Y verify -f /artifacts/allowed_signers -I container-test \
            -n claude-codex-orchestrator-release -s SHA256SUMS.sig < SHA256SUMS
        sha256sum -c SHA256SUMS
    )
done
tar -xzf /artifacts/4.2.0/claude-codex-orchestrator-4.2.0.tar.gz
source_dir="$HOME/work/claude-codex-orchestrator-4.2.0"
cd "$source_dir"
# Negative dependency case, without removing any system package.
mkdir "$HOME/no-git"
for command in python3 uname; do
    ln -s "$(command -v "$command")" "$HOME/no-git/$command"
done
status=0
PATH="$HOME/no-git" /bin/sh ./install.sh > "$HOME/no-git.log" 2>&1 || status=$?
[ "$status" -eq 2 ]
assert_contains "$HOME/no-git.log" 'git is required'
[ ! -e "$XDG_DATA_HOME/claude-codex-orchestrator" ]
! command -v claude >/dev/null 2>&1
! command -v codex >/dev/null 2>&1
./install.sh > "$HOME/install.log" 2>&1
cat "$HOME/install.log"
assert_contains "$HOME/install.log" 'Warning: claude NOT FOUND'
assert_contains "$HOME/install.log" 'Warning: codex NOT FOUND'
orchestrator doctor > "$HOME/doctor.log"
cat "$HOME/doctor.log"
assert_contains "$HOME/doctor.log" 'claude: NOT FOUND'
assert_contains "$HOME/doctor.log" 'codex: NOT FOUND'
assert_version() {
    orchestrator versions > "$HOME/versions.json"
    python3 - "$HOME/versions.json" "$1" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    assert json.load(stream)['engine_version'] == sys.argv[2]
PY
}
assert_version 4.2.0
PROJECT="$HOME/PROJECT"
export PROJECT
git init -q "$PROJECT"
cd "$PROJECT"
printf 'test:\n\t@printf "PROFILE_TEST_PASS\\n"\n' > Makefile
orchestrator init
orchestrator verify
orchestrator profiles
python3 .claude/scripts/managed-exec.py root-make-test --dry-run
orchestrator profile-approve root-make-test --yes
ORCHESTRATOR_CLAUDE_SESSION_ID=$(python3 -c 'import uuid; print(uuid.uuid4())')
export ORCHESTRATOR_CLAUDE_SESSION_ID
python3 .claude/scripts/managed-exec.py root-make-test
orchestrator distribution configure --repository OWNER/REPO \
    --allowed-signers /artifacts/allowed_signers --signer-identity container-test
# Capture sorted relative names and hashes, including state created by managed-exec.
# JSON encoding keeps paths with spaces unambiguous; compare whole lists to catch deletions.
snapshot() {
    python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
home = Path.home()
roots = {'project': Path(os.environ['PROJECT']), 'state': home / '.local/state/claude-codex',
         'registry': home / '.local/share/claude-codex-orchestrator/registry',
         'backups': home / '.local/share/claude-codex-orchestrator/backups'}
rows = []
for label, root in roots.items():
    assert root.is_dir(), label
    for path in sorted(root.rglob('*')):
        if path.is_file():
            rows.append([label + '/' + path.relative_to(root).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
print(json.dumps(rows, sort_keys=True, indent=2))
PY
}
snapshot > "$HOME/before.json"
update() {
    orchestrator self-update "$@" \
        --archive /artifacts/4.2.1/claude-codex-orchestrator-4.2.1.tar.gz \
        --sums /artifacts/4.2.1/SHA256SUMS --signature /artifacts/4.2.1/SHA256SUMS.sig
}
update --check
update --dry-run
assert_version 4.2.0
update --apply --yes
assert_version 4.2.1
snapshot > "$HOME/after.json"
assert_same "$HOME/before.json" "$HOME/after.json"
orchestrator self-rollback --apply --yes
assert_version 4.2.0
snapshot > "$HOME/after.json"
assert_same "$HOME/before.json" "$HOME/after.json"
PREFIX="$XDG_DATA_HOME/claude-codex-orchestrator"
status=0
"$PREFIX/uninstall.sh" > "$HOME/uninstall-plan.json" || status=$?
[ "$status" -eq 4 ]
"$PREFIX/uninstall.sh" --yes
[ ! -e "$HOME/.local/bin/orchestrator" ]
[ ! -L "$HOME/.local/bin/orchestrator" ]
[ -f "$PROJECT/.claude/scripts/managed-exec.py" ]
[ -d "$HOME/.local/state/claude-codex" ]
snapshot > "$HOME/after.json"
assert_same "$HOME/before.json" "$HOME/after.json"
printf 'CONTAINER_SCENARIO_PASS %s\n' "$CONTAINER_IMAGE"
