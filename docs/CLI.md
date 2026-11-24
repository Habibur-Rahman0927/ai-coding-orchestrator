# Claude-Codex Orchestrator CLI (4.1.0)

`orchestrator` installs and manages the Claude-Codex orchestration layer in Git
projects. The engine lives in `~/.local/share/claude-codex-orchestrator`; the
command is a symlink at `~/.local/bin/orchestrator`.

Project commands act on the Git project that contains the current directory.
Pass `--project PATH` to target another project.

## Layout

| Path | Purpose |
|---|---|
| `releases/<version>/` | Immutable release payloads with `checksums.json` |
| `releases/<version>/release.json` | Release metadata (`status`: `VERIFIED`, `TESTING`, ...) |
| `current.json` | Release that `init` and `update` use by default |
| `cli-checksums.json` | Seal for `orchestrator.py`; written by `release-promote` |
| `registry/projects.json` | Global project registry |
| `backups/projects/<project-id>/` | Verified project backups |
| `backups/engine/` | Backups of the engine itself |
| `tests/test_orchestrator.py` | Regression suite |
| `~/.local/state/claude-codex/<project-id>/` | Per-project runtime state (sessions, workflows, logs, integrity manifest, profile approvals) |

## Installation in a project

```bash
orchestrator init --dry-run     # show what would be created and merged
orchestrator init               # install the current VERIFIED release
```

`init` will:

- refuse if the project already has orchestration (scripts, hooks, a
  `CLAUDE.md` section, hooks in `settings.json` or `settings.local.json`, or an
  integrity manifest);
- refuse if any file already exists at a path it would create;
- copy the release scripts and hooks to `.claude/scripts` and `.claude/hooks`
  (mode 0700);
- add a delimited block to the end of `CLAUDE.md`. Existing text is untouched.
  `@AGENTS.md` is added inside the block only when `AGENTS.md` exists and is
  not already referenced;
- merge validated allow rules and the `SessionStart` and `Stop` hooks into
  `.claude/settings.local.json`, leaving existing `allow`, `deny`, `ask`, hooks
  and other keys unchanged. `settings.json` is never modified;
- detect execution profiles. All profiles start unapproved;
- write `.claude/orchestration.json` (the installation record) and the
  integrity manifest;
- take a verified `pre-install` backup first, and restore every file
  automatically if any step fails.

New Claude sessions start in Claude-only mode. Say **"Use Codex"** to activate
orchestration and **"Use Claude only"** to pause it.

## Commands

| Command | Effect | Changes files |
|---|---|---|
| `versions` | CLI version and integrity, releases (status and integrity), current release, registered projects, this project's version | No |
| `doctor` | CLI seal, current release integrity, tool availability | No |
| `verify` | Run the project integrity check | No |
| `status [--all]` / `watch` | Orchestration status of this project or of every registered project | No |
| `projects` | Print the registry | No |
| `backup` | Create a checksum-verified backup of orchestration files and state | Backup only |
| `backups` | List backups and re-verify their checksums (exit 6 on mismatch) | No |
| `update --check` | Installed version vs. target, conflicts, active workflows | No |
| `update --dry-run` | List file operations: add, replace, remove, rewrite, merge | No |
| `update --apply --yes [--release V]` | Upgrade the project transactionally | Yes |
| `rollback --check` / `--dry-run` | Verify the backup and show what would be restored | No |
| `rollback --apply --yes [--backup NAME] [--overwrite-edits]` | Restore the latest completed pre-update backup, or the one named | Yes |
| `uninstall --dry-run` | Show what would be removed and preserved | No |
| `uninstall --apply --yes` | Remove orchestration and keep runtime state | Yes |
| `unregister [--id ID]` | Remove a project from the registry only | Registry only |
| `adopt` | Register an existing installation (for example legacy V3) without changes | Registry only |
| `profiles` | List execution profiles with their approval state | No |
| `profile-approve NAME --yes` | Approve exactly one profile command | Approval file only |
| `release-promote V --test-report R --yes` | Maintainer command: mark a release VERIFIED | Release metadata |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | General error (not installed, project or backup not found, no eligible backup) |
| 3 | Conflict: local modification, legacy V3 project, unverified release, unmanaged file at a managed path |
| 4 | Confirmation required (`--yes` or `--overwrite-edits`) |
| 5 | Unsafe path: symlink, traversal, foreign owner, world-writable, permission denied, unsafe template rule |
| 6 | Integrity failure: release, CLI, backup checksum, project check |
| 7 | Active workflow is running |
| 75 | Busy: another management operation or a managed execution holds the project lock |
| 77 | `managed-exec.py`: profile not approved |
| 78 | `managed-exec.py`: project integrity preflight failed |

## Update

1. Run `update --check` and resolve any conflicts it reports.
2. Run `update --dry-run` to review the operations.
3. Run `update --apply --yes`.

During an update:

- managed scripts and hooks are replaced. Scripts dropped by the new release
  are removed;
- the `CLAUDE.md` block and the `.gitignore` block are replaced in place;
- settings are reconciled against the template the project was installed
  with. Only entries new in the target release are added. Entries the release
  dropped are removed. Entries you removed yourself stay removed;
- execution profiles and their approvals are kept;
- session mappings, workflow history and logs are never touched.

`update` refuses to run when:

- the target release is not `VERIFIED` (override with `--allow-unverified`);
- a managed file was modified, deleted or replaced by a symlink;
- an unmanaged file sits at a path the new release would create;
- a workflow is `RUNNING`;
- the project lock is held.

## Rollback

`rollback` restores the newest completed `pre-update` backup. Failed updates
never produce a selectable backup. Before restoring it:

- re-verifies every checksum in the backup;
- refuses if any file has been changed or deleted since the update;
- takes a `pre-rollback` safety backup.

`--backup NAME` restores any other backup. If that would overwrite files that
changed since the backup was taken, it also requires `--overwrite-edits`.

## Uninstall

`uninstall --apply --yes` removes the scripts, hooks and configuration files
it installed, along with its `CLAUDE.md` block, `.gitignore` block, settings
entries, integrity manifest and profile approvals, and then unregisters the
project.

A `CLAUDE.md`, `settings.local.json` or `.gitignore` that did not exist before
installation is deleted once it is empty again. Session mappings, workflow
history and logs stay in the state directory. A `pre-uninstall` backup is
created first.

## Execution profiles

Profiles are detected per project. Detection covers the project root and its
top-level directories:

| Stack | Detected when | Profiles |
|---|---|---|
| Node.js / Next.js / React | `package.json` | `build`, `lint`, `typecheck`, `test`, `test:*` through `npm`, `pnpm` or `yarn` (by lockfile) |
| Laravel / PHP | `artisan` and `composer.json` | `php artisan test`; `vendor/bin/pint --test` when Pint is present |
| Python | `pyproject.toml`, `pytest.ini` or `setup.py` | `python3 -m pytest` |
| Go | `go.mod` | `go build`, `go test`, `go vet` (`./...`) |
| Rust | `Cargo.toml` | `cargo test` |
| Any | `Makefile` with a `test:` target | `make test` |

Every profile starts unapproved and exits with code 77 until it is approved:

```bash
python3 .claude/scripts/managed-exec.py PROFILE --dry-run   # review the exact command
orchestrator profile-approve PROFILE --yes
```

An approval is tied to the profile's directory, command and timeout. Changing
any of them revokes it. Approvals are stored in the state directory, outside
the project, so a sandboxed Codex process restricted to the workspace cannot
write them.

To customise profiles, edit `.claude/orchestration-profiles.json` and then
rebuild the integrity manifest by reinstalling (`uninstall`, then `init`).
Integrity protects this file.

## Release management (maintainers)

1. Create `releases/<new>` from a copy and never edit a `VERIFIED` release in
   place. Set `release.json` `status` to `TESTING` and regenerate
   `checksums.json`.
2. Run the suite:

   ```bash
   ORCH_TEST_RELEASE=<new> python3 tests/test_orchestrator.py \
     --report test-reports/<new>.json
   ```

3. Promote:

   ```bash
   orchestrator release-promote <new> --test-report test-reports/<new>.json --yes
   ```

   Promotion is refused unless the report says `PASS`, has no failures,
   errors or skips, and matches both the release `checksums.json` digest and
   the CLI's own digest. Promotion then sets `VERIFIED`, updates
   `current.json` and seals the CLI.

## Security model and limitations

- **Checksums only detect tampering by the same user.** Release checksums, CLI
  seals, project integrity manifests and backup checksums all live in files
  the same Unix user can rewrite. They catch accidental edits, partial writes
  and tool mistakes. They do not stop a malicious process that runs as you,
  because it can rewrite a file and its checksum together. Keep the engine
  directory at mode 0700 and treat it like your shell configuration.
- **Symlink checks have a small race window.** Every write and delete re-checks
  the full directory chain immediately beforehand, but the checks use
  pathnames rather than directory file descriptors. A concurrent process
  running as the same user could still swap a parent directory for a symlink
  in the moment between check and write.
- **Locks are cooperative.** The locks are `flock` locks on
  `management.lock` and `project-execution.lock`. They coordinate the
  orchestrator and the release scripts, not arbitrary editors or processes.
- **`init` writes without `--yes`.** It only appends or merges into
  `CLAUDE.md`, `settings.local.json` and `.claude/.gitignore`, and it never
  replaces or removes them. Use `init --dry-run` to preview.
- **Allow rules are restricted.** Templates may add only `Bash(git status)`,
  `Bash(git branch --show-current)` and rules for scripts shipped in that
  release. Wildcard `git diff`, `git log` and `git show` rules are rejected
  because options such as `--output` can write files.
- **Legacy V3 projects** (no `.claude/orchestration.json`) are never modified.
  `update`, `rollback` and `uninstall` refuse with exit 3.
