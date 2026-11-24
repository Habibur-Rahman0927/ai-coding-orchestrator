# Claude-Codex Orchestrator

A Python CLI that installs and manages Claude/Codex orchestration in Git projects.
The engine manages verified project payloads, per-project approvals and backups;
engine updates and project payload updates are separate operations.

V5 development adds an isolated local workspace, persistent project knowledge,
provider adapters, workflows, and an authenticated dashboard. Start with the
[V5 workspace guide](docs/v5/WORKSPACE.md) and [verification evidence](docs/v5/RESULTS.md).
This is an unpublished development implementation, not a fully verified V5 release.

## Platform and requirements

V4.3.0 is an unpublished cross-platform candidate with native macOS and Windows
adapters. See the [cross-platform guide](docs/CROSS-PLATFORM.md) and
[measured verification status](docs/CROSS-PLATFORM-RESULTS.md) before using it.
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

## Quick start

For a signed team release, follow [Team installation](docs/TEAM-INSTALL.md).
From a trusted source checkout:

```sh
./install.sh --dry-run
./install.sh
export PATH="$HOME/.local/bin:$PATH"
orchestrator doctor
cd /path/to/PROJECT
orchestrator init --dry-run
orchestrator init
orchestrator profiles
```

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

Validation:

```sh
python3 tests/test_orchestrator.py
python3 tests/test_distribution.py
python3 tests/test_self_update.py
./tests/container/run.sh
```

The container harness needs Docker, Python, Git and OpenSSH on the host, plus
network access for image pulls and container package installation. It mounts
only generated public release artifacts and its scenario script, read-only;
it does not mount host HOME, configuration, or the throwaway signing key.

Created By: Md Habibur Rahman
