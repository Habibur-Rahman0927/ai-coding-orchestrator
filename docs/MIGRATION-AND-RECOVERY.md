# Migration and Recovery

## Version lineage

| Version | Origin | Project marker | Status |
|---|---|---|---|
| V3 | Hand-built inside a single project before the global CLI existed | No `.claude/orchestration.json`; uses a project-specific session variable | Supported by the explicit `migrate-v3` command |
| 4.0.0 | First global CLI. `init` rewrote scripts at install time | `orchestration.json` without `"schema": 2` | `PORTABILITY_PENDING`. Kept unchanged |
| 4.1.0 | Generic release with explicit `CLAUDE.md` and `.gitignore` markers, profile approval and validated templates | `orchestration.json` with `"schema": 2` | `VERIFIED` (current) |

## Migrating a 4.0.0 project to 4.1.0

```bash
cd /path/to/project
orchestrator update --check            # must report "conflicts": []
orchestrator update --dry-run
orchestrator update --apply --yes
orchestrator verify
```

What changes in the project:

- **Session variable.** Scripts read `ORCHESTRATOR_CLAUDE_SESSION_ID`, which
  the 4.0.0 installer already wrote. Open a new Claude Code session after
  updating so the `SessionStart` hook exports it.
- **Instructions.** The unmarked "Claude-Codex Orchestration V4" section at the
  end of `CLAUDE.md` becomes a delimited block. If that section was edited by
  hand, the update refuses with exit 3: move your edits above the section and
  retry.
- **`@AGENTS.md`.** The line the 4.0.0 installer prepended at the top of
  `CLAUDE.md` stays in place as your own content.
- **Profiles.** The 4.0.0 profiles (`{name: [dir, cmd, timeout]}`) are
  converted to the 4.1.0 format and kept, but each one now needs
  `orchestrator profile-approve NAME --yes` before it can run.
- **Permissions.** The wildcard `git status`, `git diff`, `git log`,
  `git show`, `git ls-files` and `git rev-parse` rules the 4.0.0 installer
  added are removed. `Bash(git status)` and `Bash(git branch --show-current)`
  are added.
- **Unchanged:** session mappings, workflow history and logs.

To undo: `orchestrator rollback --apply --yes`. This restores the 4.0.0 files
byte-for-byte.

## V3 to managed 4.1.0 (engine 4.3.0 or newer)

Only the explicit migration command changes a V3 install. Ordinary `init`,
`update` and `uninstall` continue to refuse legacy projects; `adopt` only
registers them. Start in the project's Git root:

```sh
orchestrator migrate-v3 --check
orchestrator migrate-v3 --dry-run --report /path/to/MIGRATION-PLAN.json
orchestrator migrate-v3 --apply --yes --report /path/to/MIGRATION-RESULT.json
orchestrator verify
orchestrator profiles
```

`--project DIR` selects another Git project. `--release V` selects a target
payload; it must pass integrity and be VERIFIED. Reports must be outside the
project, engine and runtime-state directories. Check/dry-run do not change
project or runtime files; an explicit `--report` writes the requested report.
Applying without `--yes` returns 4.

Migration requires the V3 marker scripts, no `.claude/orchestration.json`, a
matching V3 integrity manifest, and a passing check by the project's own V3
`integrity-check.py`. Resolve unsafe paths (5), integrity failures (6), RUNNING
workflows (7), or busy management/execution locks (75) first. An already-managed
project or ambiguous V3 layout is refused (3).

The plan includes every file operation, the detected legacy session variable,
converted literal execution profiles (all unapproved), full replacement
`CLAUDE.md`, removed V3 orchestration text, settings changes and project rules.
Profiles are parsed as data, not imported or run. Existing nonempty approval
state must be resolved before migration; migration never grants approvals.

The supported instruction layout is a preamble, the V3 heading with sections
1–14, and `## 15. NAME Project Rules` through EOF. Migration preserves the
preamble and project rules, re-heads the rules as `# NAME Project Rules`, and
appends one standard marked V4 block without duplicating `@AGENTS.md`.
For an empty rules section, or to deliberately replace its body:

```sh
orchestrator migrate-v3 --dry-run --project-rules /path/to/RULES.md
orchestrator migrate-v3 --apply --yes --project-rules /path/to/RULES.md
```

Review the replacement in the dry-run. `AGENTS.md`, `.agents/skills`, and
application files are not modified. Settings remove only allow entries and
whole hook definitions equal to those in the V3 template snapshot, then merge
the target template. Other allow rules, deny/ask lists, user hooks and other
settings remain. The ignore file keeps custom lines, drops exact duplicates of
the target block and the two V3 test-file names, then appends the marked block.
V3 managed scripts absent from the target payload are removed.

Runtime session mappings, tasks, workflow history, logs and execution records
remain byte-identical. The **integrity manifest is intentionally replaced** for
V4. Profile approval state is left alone. New Claude sessions export
`ORCHESTRATOR_CLAUDE_SESSION_ID` through the SessionStart hook: restart sessions
opened before migration. No user shell configuration is edited.

### Undo migration

```sh
orchestrator rollback --check
orchestrator rollback --dry-run
orchestrator rollback --apply --yes
```

Migration creates a verified `pre-migrate-v3` backup containing every touched
project file and the old integrity manifest. Only completed migrations are
eligible for automatic rollback. Normal rollback selects the latest completed
project update or migration, refuses post-operation edits, and restores the V3
bytes and modes, including its manifest. `.claude/orchestration.json` is removed
and the registry returns to version `3`, preserving `registered_at`.

### Archive legacy development artifacts

After migration, review this separate opt-in operation:

```sh
orchestrator archive-legacy --dry-run --to /path/to/ARCHIVES
orchestrator archive-legacy --apply --yes --to /path/to/ARCHIVES
```

It requires a managed install with passing integrity. The destination must be
outside the project and runtime state. It enumerates files under
`.claude/backups/`, immediate `*.backup` files in `.claude`, `scripts`, and
`hooks`, the two legacy test files, and files in script/hook `__pycache__`
directories. Tracked or integrity-managed files are kept and reported.

Files are copied to `ARCHIVES/PROJECT_ID-STAMP/` with relative paths and modes;
`checksums.json` is verified before any source removal. Cache `.pyc` files may
be deleted without archival, as shown in the plan. Only listed source files
are removed, one by one, and only their now-empty parent directories are
removed. It never recursively deletes `.claude` or edits application files.
An archival failure during removal restores already-removed files; the verified
archive remains available.

## Recovery procedures

| Situation | Action |
|---|---|
| `init`, `migrate-v3`, `update`, `rollback` or `uninstall` failed partway | Changes are restored automatically and the error ends with "All changes were rolled back." Fix the cause and re-run |
| Error ends with `RESTORE_INCOMPLETE` | Automatic restoration could not finish (for example, the disk is full). After `update` or `rollback`: run `orchestrator backups`, then `orchestrator rollback --apply --yes --backup <newest pre-update or pre-rollback backup> --overwrite-edits`. After `init` or `uninstall`: copy the files back from `backups/projects/<project-id>/<stamp>-pre-install/files/` (or `-pre-uninstall`); each file's checksum is in that backup's `backup.json` |
| Process killed mid-operation (power loss, SIGKILL) | Every file write is atomic, so each file is either old or new. Run `orchestrator verify`. If it fails, restore the newest backup with `rollback --backup NAME` |
| `update`, `rollback` or `uninstall` returns 75 | Another management operation or a managed execution holds the lock. Wait for it to finish, check `orchestrator status`, and do not start a duplicate |
| Returns 7 | A workflow is RUNNING. Finish it or pause it (`python3 .claude/scripts/task-state.py pause`, or say "Use Claude only") |
| Returns 3 with MODIFIED or DELETED entries | Restore the file (`git checkout`, or use the backup) or keep your change and skip the update |
| `verify` reports an unregistered script | Remove the extra file from `.claude/scripts` or `.claude/hooks`. Unknown scripts are never trusted automatically |
| `backups` reports a checksum FAIL | Do not restore that backup. Use an older backup that passes |
| CLI integrity mismatch (exit 6) | `orchestrator.py` changed after it was sealed. Compare it with `engine-backups/*/orchestrator.py` and reinstall a known-good copy. Re-seal only through `release-promote` after a passing test run |
| Release integrity mismatch | A release file changed. Never regenerate the checksums of a VERIFIED release; restore it from backup or rebuild it as a new version |

## Engine backups

`self-update --apply` saves the replaced engine under
`engine-backups/<version>-<timestamp>/`. `orchestrator self-rollback --apply --yes`
restores the most recent one. Registry, project backups and project files are
never modified by engine updates.
