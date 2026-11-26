# AI Orchestrator

A local AI workspace and Python CLI for coordinating AI agents in Git projects.
The engine manages verified project payloads, per-project approvals and backups;
engine updates and project payload updates are separate operations.

V5 development adds an isolated local workspace, persistent project knowledge,
provider adapters, workflows, and an authenticated dashboard. Start with the
[V5 workspace guide](docs/v5/WORKSPACE.md) and verification evidence (source checkout: `docs/v5/RESULTS.md`; omitted from packages).
This is an unpublished development implementation, not a fully verified V5 release.
Phase 2 adds guided setup, automatic local browser authentication and managed
startup: [start with one command](docs/v5/PHASE2-START.md), then read the
Phase 2 evidence and limitations (source checkout: `docs/v5/PHASE2-RESULTS.md`; omitted from packages).

## Installation

### Requirements

- **Python 3.8 or newer** and **Git**, available on PATH.
- A browser for the local dashboard.
- At least one configured provider to run AI tasks: Codex CLI, Claude Code CLI,
  or a MiniMax API account. You can install and explore the workspace before
  connecting a provider.
- Your project's own build/test tools when you want agents to use them.

Normal local use needs **no Docker, Node.js, Redis, PostgreSQL, or third-party
Python runtime packages**. The installer does not download dependencies, sign you
into providers, run model requests, or register a startup service. Run it as your
normal user; a system-wide installation is not required.

The commands below install from source for local evaluation. For a downloaded
signed release, verify its provenance first using [Team installation](docs/TEAM-INSTALL.md).
Windows wrappers exist, but documentation of a command is not native-platform
acceptance; see the [candidate scope](docs/v5/RELEASE-CANDIDATE.md).

### 1. Get the source

From a terminal with access to this repository:

```sh
git clone https://github.com/Habibur-Rahman0927/claude-codex-orchestrator.git
cd claude-codex-orchestrator
```

If you already have a checkout, use that directory and inspect any local changes
before updating it. Review the source/revision you intend to install.

### 2. Install on macOS or Linux

```sh
python3 --version
git --version
sh ./install.sh --dry-run
sh ./install.sh
export PATH="$HOME/.local/bin:$PATH"
orchestrator workspace doctor
orchestrator open
```

Inspect the dry-run output before running the installation command. The PATH
command applies to the current terminal. For future terminals, add the same
`export PATH=...` line once to your shell's startup file, such as `~/.zshrc` for
interactive zsh or `~/.bashrc` for interactive bash, then open a new terminal.
For a custom bin directory, use the exact PATH hint printed by the installer.

### 2. Install on Windows (PowerShell)

From the cloned repository directory:

```powershell
python --version
git --version
.\install.ps1 --dry-run
.\install.ps1
$env:PATH = "$env:LOCALAPPDATA\claude-codex-orchestrator\bin;$env:PATH"
orchestrator workspace doctor
orchestrator open
```

Use the Python command available on your PATH; the wrapper checks `python`, then
`python3`. Add the installer-reported bin directory to your **user PATH** through
Windows Environment Variables for future terminals. If script execution is
restricted, follow your machine's policy; the Python installer entry point is
`python -B -I .\engine\lib\ccx_install.py install --dry-run` for inspection and
the same command without `--dry-run` for installation. No execution-policy change
is required by this project. See [platform paths and requirements](docs/CROSS-PLATFORM.md#requirements-and-storage).

### Try without installing

From this checkout, start the isolated workspace with:

```sh
python3 -B engine/orchestrator.py open
python3 -B engine/orchestrator.py workspace status
python3 -B engine/orchestrator.py workspace doctor
```

The first command starts or reuses the background service and opens the authenticated
dashboard. On Windows, use `python` instead of `python3` if that is your installed
interpreter command. Choose one agent and an optional project, then describe a task in Chat.
See the [daily-use and team evaluation guide](docs/v5/DAILY-USE.md).
A pre-existing global `orchestrator` can still be an older installation; these
checkout commands select the reviewed source. Read the [candidate scope](docs/v5/RELEASE-CANDIDATE.md)
and [operations guide](docs/v5/OPERATIONS.md) before installation or recovery.
V5 is for local evaluation: native platform acceptance and live provider behavior
are not certified by the mocked and synthetic test evidence.

## First run and provider setup

1. Open the dashboard with `orchestrator open`. Normal startup authenticates the
   browser automatically; no manual token copying is needed.
2. Choose the agent you want to use. Existing Codex/Claude authentication stays
   with those CLIs; the workspace does not replace it.
3. Preview and register an approved Git project, or skip project selection until
   you are ready. Check the excluded paths before indexing.
4. Use **Ask** to send a read-only question in one action. Choose **Build** for
   implementation: **Review task → Approve & start**. Review the project, usage
   settings and file permissions in that single card. AI chooses project commands
   and verification checks; no manual command form is needed.
   One provider is enough; implementation and review use separate sessions.
5. Manage progress, results, pause/resume and cancellation in **Tasks**. Chat stays
   focused on your conversation. New tasks have no cumulative workspace usage cap;
   add one under **Optional usage limits** if wanted. Provider quotas, billing,
   model context and execution safeguards still apply. Inspect test/review evidence
   before treating a workflow as completed.

In **Providers**:

| Provider | Connection method | Configuration |
|---|---|---|
| Codex | Installed, signed-in `codex` CLI | Start the workspace from a terminal that can find `codex`; inherit native settings unless you choose an override. |
| Claude | Installed, signed-in `claude` CLI | Same approach; version compatibility and account usage restrictions still apply. |
| MiniMax | Independent API adapter | Choose an explicit model and configure a key using supported OS storage, session-only storage, or a named environment variable. |

Use **Check local setup** for diagnostics. An executable being detected does not
prove authentication or a successful live connection. A **live connection test**
can consume subscription allowance/API credits and requires explicit confirmation.
Do not paste API keys into project files, Git, issues, or ordinary configuration.
See [provider configuration](docs/V5-PROVIDERS.md) and the
[daily-use guide](docs/v5/DAILY-USE.md) for details.

## Everyday commands

```sh
orchestrator open                    # Open/reuse the background workspace
orchestrator workspace status        # Inspect the V5 service
orchestrator workspace doctor        # Diagnose V5 setup
orchestrator stop                    # Stop the managed service
orchestrator restart --background    # Restart it deliberately
```

Closing the browser does not stop background work. Pause/cancel a workflow
deliberately or stop the service. Top-level `orchestrator status` and
`orchestrator doctor` retain their legacy meanings; use the `workspace` forms for
V5. For headless operation, use `orchestrator open --no-browser`.

## Updating, backup and removal

Before an update, create a workspace backup using Settings, or run
`orchestrator workspace backup` followed by a **new absolute backup-file path**.
Keep backups private. Then stop the service, MCP processes and direct runners;
active runtimes block code replacement. Inspect local changes and select the
reviewed source revision before upgrading from that checkout:

```sh
orchestrator stop
sh ./install.sh --upgrade --dry-run
sh ./install.sh --upgrade
orchestrator open
```

On Windows use `.\install.ps1 --upgrade --dry-run`, then
`.\install.ps1 --upgrade`. Use the same `--prefix` and `--bin-dir` for custom
installations. For signed remote updates and engine rollback, follow
[Team updates](docs/TEAM-UPDATE.md); updating project payloads is a separate action.

To remove a default installation from the matching source checkout:

```sh
orchestrator stop
sh ./uninstall.sh
sh ./uninstall.sh --yes
```

The first uninstall command shows a plan and intentionally exits with code **4**;
review it before confirming. On Windows use `.\uninstall.ps1` and then
`.\uninstall.ps1 --yes`. Supply the original prefix/bin paths for custom installs.
Do not use `--purge` as routine cleanup. Engine removal does not authorize deleting
projects, workspace knowledge or provider credentials. See
[removal details](docs/TEAM-INSTALL.md#remove-the-engine) and
[backup/recovery operations](docs/v5/OPERATIONS.md).

## Troubleshooting

| Symptom | What to check |
|---|---|
| `orchestrator: command not found` | Add the installer-reported bin directory to PATH and reopen the terminal. Source-checkout commands also work without installation. |
| `open` is an unknown command | An older launcher may be selected. Use `command -v orchestrator` on macOS/Linux or `Get-Command orchestrator` in PowerShell; select or upgrade the intended installation. |
| Installation already exists | Review a deliberate `--upgrade`; do not delete the existing installation or overwrite an unrelated launcher. |
| Engine is busy (exit 75) | Stop services, MCP clients and direct runners using that engine, including custom databases, before upgrading/removing it. |
| Browser did not open / login expired | Run `orchestrator open` again. Follow its reported private fallback-token path if needed; do not paste example paths containing `...`. |
| Provider unavailable | Check Providers diagnostics and the terminal PATH; native login, model configuration and quota restrictions are separate checks. |
| Workflow waits for approval | Inspect the displayed scope and grant only the required access. A budget setting alone does not authorize spending. |
| Workflow interrupted | Inspect saved state and actual file changes before approving a retry; an unknown result might already have changed files. |

For a bug report, include OS/architecture, Python version, the source revision,
reproduction steps and a reviewed/redacted diagnostic report. Exclude API keys,
access tokens, private project contents, databases and provider session files.

## Platform and requirements

V4.3.0 is an unpublished cross-platform candidate with native macOS and Windows
adapters. See the [cross-platform guide](docs/CROSS-PLATFORM.md) and
measured verification status (source checkout: `docs/CROSS-PLATFORM-RESULTS.md`; omitted from packages) before using it.
The immutable 4.1.0 project payload remains the default; select the 4.3.0
candidate explicitly for non-Linux evaluation.

The historical Linux distribution harness covers:

- Ubuntu 20.04 (Python 3.8 floor) and 24.04
- Debian 12
- Fedora 41
- Alpine 3.20

This names the harness coverage, not a claim that a particular checkout has
passed it. Run the harness before publishing; no other distributions are claimed.

Required: Python 3.8 or newer and Git. Optional for installation: `claude`,
`codex`, `gh`, and `ssh-keygen`; missing tools produce warnings. Claude/Codex
are needed to use those agents, `gh` for GitHub downloads, and an OpenSSH
`ssh-keygen` supporting `-Y sign` / `-Y verify` for signed releases. Execution
profiles also need their project's tools, such as `make` or a package manager.

## Legacy V4 project integration

For a signed team release, follow [Team installation](docs/TEAM-INSTALL.md).
From a trusted source checkout:

```sh
orchestrator doctor
cd /path/to/PROJECT
orchestrator init --dry-run
orchestrator init
orchestrator profiles
```

Replace `/path/to/PROJECT` with your Git project's actual directory. This flow
installs project-level orchestration files and is separate from V5 dashboard
registration; V5 users do not need to run `init` to register a project. The default
4.1.0 payload is Linux-only. For macOS/Windows candidate evaluation, follow the
[cross-platform guide](docs/CROSS-PLATFORM.md) instead of running the default init.

Review and approve only the profiles you intend to run. New Claude sessions use
Claude-only mode; say **Use Codex** to activate orchestration or **Use Claude
only** to pause it.

## Guides

- [Team installation and removal](docs/TEAM-INSTALL.md)
- [Engine and project updates](docs/TEAM-UPDATE.md)
- [Release builds and signing](docs/RELEASING.md)
- [Security and limitations](docs/SECURITY.md)
- [CLI reference](docs/CLI.md)
- [Migration and recovery](docs/MIGRATION-AND-RECOVERY.md)

## Development and validation

Run from the repository root. These are local automated checks, not live-provider
or production-readiness claims:

```sh
python3 -B -m unittest discover -s tests -p 'test_v5_*.py' -v
python3 -B -m unittest discover -s tests -p test_repository_hygiene.py -v
```

The full POSIX suite against the cross-platform candidate is:

```sh
ORCH_TEST_RELEASE=4.3.0 python3 -B -m unittest discover -s tests -v
```

Browser tests use optional developer tooling; follow the browser-testing
instructions in the source phase reports. Do not use the POSIX full-suite command
as a claim of native Windows coverage; see `.github/workflows/cross-platform.yml`
for platform-specific test selection. The optional Linux distribution harness is
`sh tests/container/run.sh`.

The container harness needs Docker, Python, Git and OpenSSH on the host, plus
network access for image pulls and container package installation. It mounts
only generated public release artifacts and its scenario script, read-only;
it does not mount host HOME, configuration, or the throwaway signing key.

## License and public release status

This repository currently has **no `LICENSE` file**. The maintainer still needs to
choose and add a license before presenting the project as an open-source release.
No license terms or production certification are implied by these installation
instructions. Follow the [release guide](docs/RELEASING.md) before publishing
artifacts; do not republish this development tree under an existing release version.

Created By: Md Habibur Rahman
