# V4.3.0 candidate: installation, architecture and verification

On non-Linux hosts, `init`, `adopt`, `update`, and `migrate-v3` refuse Linux-only payloads
4.0.0 and 4.1.0 before any backup or write, including dry runs. The default
4.1.0 therefore requires Linux. To evaluate the candidate explicitly, use
`init --release 4.3.0 --allow-unverified` (or the same release flags with
`update --apply --yes`). `verify` adds `runtime_compatible` to its JSON report
without changing integrity status or exit codes. Inspection, removal, backup,
and rollback remain available for legacy installations.

This is an unpublished cross-platform candidate. The existing 4.1.0 project
release is retained unchanged and remains the default. Do not use the old
Linux-only runtime to claim macOS or Windows process supervision support.
Explicitly select the candidate in an isolated project for evaluation.

See [audit and prioritized implementation plan](CROSS-PLATFORM-AUDIT.md) and
[measured verification report](CROSS-PLATFORM-RESULTS.md). A Windows runner,
Windows client machine, and Linux containers must pass before full verification.
No platform is marked VERIFIED by copying Linux release metadata.

## Known limitations

The immutable 4.1.0 payload's Codex delegation requires Python >= 3.11 because
`codex-session.py` imports `tomllib` unconditionally. The legacy 4.0.0 fixture
has the same defect. The documented Python 3.8 floor applies to the engine and
4.3.0 candidate, not legacy Codex delegation. Ubuntu 20.04/22.04 users running
the default Python should evaluate 4.3.0 explicitly with
`--release 4.3.0 --allow-unverified`. Without `tomllib`, the candidate lets Codex
inherit its saved configuration instead of parsing it in the wrapper.

## Requirements and storage

Python 3.8+ and Git are required. No system pip installation or administrator
privileges are needed. The implementation uses standard-library native adapters:
Linux `/proc` and flock, macOS libproc and flock, Windows SID/DACL, LockFileEx,
process creation FILETIME and Job Objects. psutil and portalocker were evaluated;
no additional runtime dependency is installed. Python before 3.11 lacks tomllib;
the new payload lets Codex read its own saved preferences instead of requiring it.

Optional tools: Claude CLI, Codex CLI, GitHub CLI, OpenSSH `ssh-keygen` supporting
SSH signatures. Missing tools are reported; offline management does not require
agent authentication. Profiles require the tools they actually invoke.

| Purpose | Linux / WSL2 | macOS | Native Windows |
|---|---|---|---|
| Engine | `$XDG_DATA_HOME/claude-codex-orchestrator`, default `~/.local/share/claude-codex-orchestrator` | `~/Library/Application Support/claude-codex-orchestrator` | `%LOCALAPPDATA%\claude-codex-orchestrator` |
| Launcher | `~/.local/bin/orchestrator` | `~/.local/bin/orchestrator` | engine `bin\orchestrator.cmd` |
| Runtime state | `~/.local/state/claude-codex` | same legacy Unix state directory to retain 4.1 compatibility | engine application directory `state` |
| Distribution config | `$XDG_CONFIG_HOME/claude-codex-orchestrator` or `~/.config/claude-codex-orchestrator` | engine application directory `config` (explicit XDG override honored) | engine application directory `config` |

Explicit XDG overrides on macOS are honored. Existing Linux layouts and project
ID hashes remain unchanged. Engine uninstall retains state and registry/backups.
No shell startup files, saved model preferences or authentication files are edited.

## Ubuntu, Debian and WSL2

From a trusted checkout (or a separately signature-verified release):

```sh
sh install.sh --dry-run
sh install.sh
export PATH="$HOME/.local/bin:$PATH"
orchestrator doctor
```

WSL2 uses the Linux implementation. It is not evidence for native Windows.
The existing Docker harness covers Ubuntu 20.04/24.04, Debian 12, Fedora 41 and
Alpine 3.20; executing it is a separate requirement, not a historical PASS claim.

## macOS Apple Silicon and Intel

```sh
sh install.sh --dry-run
sh install.sh
export PATH="$HOME/.local/bin:$PATH"
orchestrator doctor
```

For a non-destructive evaluation use temporary HOME, explicit `--prefix` and
`--bin-dir` under a disposable directory. Do not run a default installation in
this review until choosing to install into your actual account. Python and Git
must already be available; the installer does not install system packages.

## Windows native: PowerShell, CMD, Git Bash

PowerShell, with Python on PATH:

```powershell
.\install.ps1 --dry-run
.\install.ps1
$env:PATH = "$env:LOCALAPPDATA\claude-codex-orchestrator\bin;$env:PATH"
orchestrator doctor
```

If PowerShell execution policy prevents running a local wrapper, use the common
Python entry point; do not change execution policy globally:

```powershell
python -I engine/lib/ccx_install.py install --dry-run
python -I engine/lib/ccx_install.py install
```

CMD:

```bat
python -I engine\lib\ccx_install.py install --dry-run
python -I engine\lib\ccx_install.py install
set "PATH=%LOCALAPPDATA%\claude-codex-orchestrator\bin;%PATH%"
orchestrator doctor
```

Git Bash can invoke `orchestrator.cmd` explicitly after adding its directory to
PATH. Native Python executes the Windows adapters; WSL Python does not. Windows
10/11 support still requires real client testing and compatible upstream tools.
CI Windows Server coverage alone does not verify these client versions.

## Candidate project integration and team upgrades

The candidate is intentionally not promoted. Use a disposable Git project:

```sh
git init candidate-test
cd candidate-test
orchestrator init --release 4.3.0 --allow-unverified
orchestrator verify
orchestrator profiles
```

Review each profile, then approve only commands you intend to run with
`orchestrator profile-approve NAME --yes`. Changes to directory, command or timeout
invalidate its approval. Built-in detection covers npm/pnpm/yarn, Composer/PHP,
Laravel, pytest, Go, Make, Docker Compose validation and PowerShell scripts;
other explicit argv profiles can be configured and approved.

Team members can upgrade just the engine, preserving project state:

```sh
sh install.sh --upgrade --dry-run
sh install.sh --upgrade
orchestrator self-rollback --dry-run
```

Windows uses `.\install.ps1 --upgrade` or the Python entry point with `--upgrade`.
Signed distribution commands and independent signer trust are unchanged; see
[team update](TEAM-UPDATE.md). Candidate project migration is separate:

```sh
orchestrator update --release 4.3.0 --check
orchestrator update --release 4.3.0 --dry-run
orchestrator update --release 4.3.0 --allow-unverified --apply --yes
orchestrator verify
orchestrator rollback --dry-run
```

Do not migrate real team/client projects during candidate evaluation. Existing
V3 migration and legacy archival commands are preserved. V3 migration requires
a VERIFIED target unless explicitly evaluating the candidate with
`migrate-v3 --release 4.3.0 --allow-unverified --apply --yes`. Default V3 migration
on non-Linux hosts refuses the Linux-only target, including dry runs.
State, session mappings and project IDs are preserved; immutable payloads are
not rewritten. Successful migration creates a backup before replacing scripts.

## Hooks, agents and shell limitations

Claude-only remains the default. Say **Use Codex** to activate the workflow and
**Use Claude only** to pause it. Persistent sessions resume by explicit UUID,
never `--last`. Code does not select a new model or edit saved preferences.

Windows Claude integration requires Git Bash for the exported environment
contract. Native CLI management still runs from PowerShell/CMD. PowerShell-only
Claude hooks cannot be claimed equivalent: official documentation states that
PowerShell hooks do not receive `CLAUDE_ENV_FILE`. The candidate explicitly selects
Bash for hooks. Verify the installed Claude version supports the hook fields,
and inspect SessionStart and Stop in a real session before deployment.
See [Claude hook reference](https://code.claude.com/docs/en/hooks).

CLI and IDE environments can have different PATH and environment propagation.
A passing script invocation is not proof the IDE launched its SessionStart hook.
Live agent lifecycle verification remains separate from controlled CI tests.
Explicit session resume is documented in
[Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

Windows `.cmd`/`.bat` profiles use a trusted system cmd.exe with each argument
quoted and expansion disabled. Arguments containing quotes, percent, exclamation,
newlines or NUL are rejected rather than reinterpreted. Native `codex.exe` should
be available for delegation: npm `codex.cmd` cannot safely carry the TOML-quoted
configuration overrides through this restricted adapter.

## Security and recovery

Windows security uses owner SIDs and DACLs, not chmod. Junctions and all reparse
points are rejected at mutation boundaries. New protected directories and files
exclude untrusted writers. Windows backups retain owner/group/DACL descriptors;
restoration requires the same owner. Inherited ACEs can be recalculated by Windows
if parent ACLs change, so rollback cannot promise identical inheritance under a
changed parent policy. Unsupported security operations fail closed.

Linux directory inode locks remain in use. Windows engine lock names are retained
after uninstall to avoid split-lock races; do not manually remove a live lock.
Project execution uses shared/exclusive native locks. Windows runtime containment
uses Job Objects assigned atomically during native process creation; Unix retains
session/process-group supervision. PID creation identity prevents blind PID reuse.

Archive extraction rejects traversal, links, devices, Windows reserved names,
ADS, drive/UNC paths and case aliases. Signatures and exact checksum manifests
remain required by existing policy. LF source checkout rules keep signed payload
bytes independent of Git autocrlf. User files with CRLF are readable; managed
text merges normalize newlines to LF, while backups retain original bytes.

Atomic replacement is per file, not a transaction over the whole filesystem.
Caught failures restore verified backups. Abrupt power loss still requires
integrity verification and manual recovery, as documented in
[migration and recovery](MIGRATION-AND-RECOVERY.md). Same-user malicious writers
and pathname TOCTOU races remain outside complete protection.

Project removal: `orchestrator uninstall --dry-run`, then
`orchestrator uninstall --apply --yes`. Engine removal: `sh uninstall.sh --yes`
or `.\uninstall.ps1 --yes`; the Python installer supports `uninstall --yes` too.
Use explicit prefix/bin paths when evaluating an isolated installation.

## CI and remaining verification

The matrix uses Ubuntu 24.04, macOS 15 ARM64, macOS 15 Intel and Windows Server
2025. Runner architecture is printed in each job. Windows 10/11 and macOS Intel
require actual passing runs, not a mocked platform flag. GitHub availability is
based on its [hosted runner reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
A separate Ubuntu Python 3.8 job exercises the advertised Python floor.
No Claude/Codex authentication secrets are required. Windows native primitive,
installer, runtime and CLI tests run separately from historical POSIX fixtures.
