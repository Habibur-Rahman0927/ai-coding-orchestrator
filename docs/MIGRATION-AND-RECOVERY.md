# Migration and Recovery

## Version lineage

| Version | Origin | Project marker | Status |
|---|---|---|---|
| V3 | Hand-built inside a single project before the global CLI existed | No `.claude/orchestration.json`; uses a project-specific session variable | Legacy. The CLI never modifies it |
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

## V3 projects

V3 projects are registered with `adopt`, which changes no files, and every
other management command refuses to touch them. Migration from V3 is
deliberately disabled: V3 installs contain project-specific instructions,
hooks and permission rules that cannot be separated safely by automation.

If V3 is ever retired for a project, do it as a planned manual change:

1. Back up the project's `.claude/` directory and `CLAUDE.md`.
2. Remove the V3 scripts, hooks and orchestration sections by hand.
3. Run `orchestrator init`.

Back up `~/.local/state/claude-codex/<project-id>/` first as well. `init` does
not delete it, and the existing session mappings can be reused.

## Recovery procedures

| Situation | Action |
|---|---|
| `init`, `update`, `rollback` or `uninstall` failed partway | Changes are restored automatically and the error ends with "All changes were rolled back." Fix the cause and re-run |
| Error ends with `RESTORE_INCOMPLETE` | Automatic restoration could not finish (for example, the disk is full). After `update` or `rollback`: run `orchestrator backups`, then `orchestrator rollback --apply --yes --backup <newest pre-update or pre-rollback backup> --overwrite-edits`. After `init` or `uninstall`: copy the files back from `backups/projects/<project-id>/<stamp>-pre-install/files/` (or `-pre-uninstall`); each file's checksum is in that backup's `backup.json` |
| Process killed mid-operation (power loss, SIGKILL) | Every file write is atomic, so each file is either old or new. Run `orchestrator verify`. If it fails, restore the newest backup with `rollback --backup NAME` |
| `update`, `rollback` or `uninstall` returns 75 | Another management operation or a managed execution holds the lock. Wait for it to finish, check `orchestrator status`, and do not start a duplicate |
| Returns 7 | A workflow is RUNNING. Finish it or pause it (`python3 .claude/scripts/task-state.py pause`, or say "Use Claude only") |
| Returns 3 with MODIFIED or DELETED entries | Restore the file (`git checkout`, or use the backup) or keep your change and skip the update |
| `verify` reports an unregistered script | Remove the extra file from `.claude/scripts` or `.claude/hooks`. Unknown scripts are never trusted automatically |
| `backups` reports a checksum FAIL | Do not restore that backup. Use an older backup that passes |
| CLI integrity mismatch (exit 6) | `orchestrator.py` changed after it was sealed. Compare it with `backups/engine/*/orchestrator.py` and reinstall a known-good copy. Re-seal only through `release-promote` after a passing test run |
| Release integrity mismatch | A release file changed. Never regenerate the checksums of a VERIFIED release; restore it from backup or rebuild it as a new version |

## Engine backups

`self-update --apply` saves the replaced engine under
`engine-backups/<version>-<timestamp>/`. `orchestrator self-rollback --apply --yes`
restores the most recent one. Registry, project backups and project files are
never modified by engine updates.
