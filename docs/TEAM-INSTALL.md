# Team installation

**macOS and Windows:** the commands and paths below describe Linux. Use the
[cross-platform storage table](CROSS-PLATFORM.md#requirements-and-storage) for
your platform's engine, state, and configuration locations. After verifying the
`SHA256SUMS` signature against independently trusted signers, macOS can check
archive checksums with:

```sh
shasum -a 256 -c SHA256SUMS
```

In PowerShell, compute the downloaded archive's checksum with:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath .\claude-codex-orchestrator-X.Y.Z.tar.gz
```

Compare `Hash` with the matching entry in the authenticated `SHA256SUMS`; stop
on any mismatch. After verification and extraction, install from PowerShell:

```powershell
.\install.ps1 --dry-run
.\install.ps1
```

For the unpublished 4.3.0 cross-platform candidate, see the
[cross-platform guide](CROSS-PLATFORM.md) and [verification report](CROSS-PLATFORM-RESULTS.md).

Use Linux with Python >= 3.8 and Git. For this signed-release flow, also install
GitHub CLI, OpenSSH with `ssh-keygen -Y verify`, `sha256sum`, and `tar`.
Replace `OWNER/REPO`, `X.Y.Z`, `SIGNER_IDENTITY`, and file paths below.
Obtain the team's `allowed_signers` through an independently trusted channel;
a key downloaded beside an artifact does not establish its provenance.

## Signed GitHub release

Run as your normal user. The following commands assume a POSIX shell. Stop if
any verification command fails; do not extract or run an unverified archive.

```sh
set -eu
gh auth login
VERSION=X.Y.Z
SIGNER_IDENTITY=SIGNER_IDENTITY
ALLOWED_SIGNERS=/path/to/allowed_signers
DOWNLOAD=$(mktemp -d)
gh release download "v$VERSION" --repo OWNER/REPO --dir "$DOWNLOAD" \
  --pattern "claude-codex-orchestrator-$VERSION.tar.gz" \
  --pattern SHA256SUMS --pattern SHA256SUMS.sig
cd "$DOWNLOAD"
ssh-keygen -Y verify -f "$ALLOWED_SIGNERS" -I "$SIGNER_IDENTITY" \
  -n claude-codex-orchestrator-release -s SHA256SUMS.sig < SHA256SUMS
sha256sum -c SHA256SUMS
tar -xzf "claude-codex-orchestrator-$VERSION.tar.gz"
cd "claude-codex-orchestrator-$VERSION"
./install.sh --dry-run
./install.sh
export PATH="$HOME/.local/bin:$PATH"
orchestrator doctor
orchestrator versions
orchestrator distribution configure --repository OWNER/REPO \
  --allowed-signers "$ALLOWED_SIGNERS" --signer-identity "$SIGNER_IDENTITY"
```

Persist the PATH addition in your shell's startup file. Missing `claude`,
`codex`, `gh` or `ssh-keygen` causes installer warnings, not failure; `doctor`
prints `NOT FOUND` for missing Claude/Codex. Distribution configuration copies
the signers file next to `${XDG_CONFIG_HOME:-$HOME/.config}/claude-codex-orchestrator/distribution.json`.
The directory is 0700; configuration and copied signers are 0600. Signatures
are required by default. Install Claude/Codex separately when ready to use them.

## Source checkout and custom locations

Use a trusted checkout; local checksums are not independent authentication.

```sh
git clone https://github.com/OWNER/REPO.git SOURCE
cd SOURCE
./install.sh
```

Defaults are `${XDG_DATA_HOME:-$HOME/.local/share}/claude-codex-orchestrator`
and `$HOME/.local/bin`. Both paths may contain spaces:

```sh
./install.sh --prefix "$HOME/team tools/engine" --bin-dir "$HOME/team tools/bin"
export PATH="$HOME/team tools/bin:$PATH"
```

A duplicate engine install is refused with exit 3; see [upgrading](TEAM-UPDATE.md).
A symlinked prefix or bin directory is refused; symlinks in their ancestors are
canonicalised, so a symlinked home parent is supported.

## First project and approvals

In an existing Git project:

```sh
cd /path/to/PROJECT
orchestrator init --dry-run
orchestrator init
orchestrator verify
orchestrator profiles
python3 .claude/scripts/managed-exec.py PROFILE --dry-run
orchestrator profile-approve PROFILE --yes
```

Replace `PROFILE` with a listed profile and review its exact command first.
Approval is bound to directory, command and timeout; changing them invalidates
approval. For a root Makefile containing `test:`, the profile is `root-make-test`.
Managed execution requires the Claude session ID supplied by the session hook.
In Claude say **Use Codex** to activate orchestration and **Use Claude only**
to pause it. These are conversation instructions, not shell commands.

## Remove the engine

For the default location:

```sh
PREFIX="${XDG_DATA_HOME:-$HOME/.local/share}/claude-codex-orchestrator"
"$PREFIX/uninstall.sh"                 # JSON plan; expected exit 4
"$PREFIX/uninstall.sh" --yes
```

For a custom location, the installed uninstaller infers its own prefix; supply
`--bin-dir` if it differs from `$HOME/.local/bin`. A source-checkout uninstaller
accepts explicit `--prefix DIR --bin-dir DIR`.

Engine code, releases and engine backups are removed. The command symlink is
removed only when it points into the prefix. Unknown files are kept and reported;
the prefix is removed only if empty. Project registry and project backups are
kept unless `--purge` is supplied with `--yes`. Purge refuses with exit 3 while
any project remains registered. Deliberately unregister or uninstall projects
before requesting purge. Keep the source uninstaller if you may purge later.

Engine uninstall never edits projects, their `.claude` directories, global
`~/.claude` or `~/.codex`, or `~/.local/state/claude-codex`. It also leaves
user distribution configuration in place. To remove orchestration from a
project, use the separate `orchestrator uninstall --dry-run` and
`orchestrator uninstall --apply --yes` before removing the engine.
