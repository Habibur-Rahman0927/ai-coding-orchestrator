# V4.3.0 cross-platform audit and implementation plan

Audit baseline: commit `7f7527c`, clean worktree, 2026-11-24. The checkout already
uses engine 4.3.0, CLI 4.1.0, and project payload 4.1.0. Recent V3 migration and
legacy archival implementation is present and must be preserved. There were no
uncommitted Linux changes. Legacy fixtures are test inputs, not upgrade targets.

The baseline suite actually contains 99 tests. On macOS ARM64, Python 3.9.6,
99 ran, 52 failed, 0 errors. Most failures are the explicit Linux installer gate;
two runtime tests expose the Linux-only supervision path. This is measured local
evidence, not a reproduction of the previous 85-test/five-container claim.

## Priorities and architecture

| Priority | Gap and affected platforms | Required treatment |
|---|---|---|
| P0 | `/proc` process identities/CPU/group enumeration: macOS, Windows | Native adapter; retain Linux semantics and reject unknown identity before termination |
| P0 | `fcntl`, directory inode locks and inherited lock FDs: Windows | LockFileEx shared/exclusive locks; supervised lock lifetime must cover descendants |
| P0 | Unix UID/mode checks: Windows | Native owner SID/DACL validation and protected writes; no unconditional PASS |
| P0 | Symlinks versus junction/reparse points: Windows | Reject all reparse points at security boundaries |
| P0 | POSIX process groups/signals: Windows | Job Object containment established before execution, kill on close and verified identity |
| P0 | Unix selector pipes: Windows | Concurrent bounded pipe readers with explicit shutdown |
| P0 | Archive names: Windows/case-insensitive macOS | Reject drives, UNC, ADS, reserved names, aliases and case collisions before extraction |
| P1 | Unix executable/symlink launcher: Windows | Native launcher and absolute interpreter; no admin or Developer Mode dependency |
| P1 | Bash hook/environment assumptions: Windows/IDE | Supported shell configuration, explicit propagation limitations and live lifecycle verification |
| P1 | Text default encodings/newline translation: Windows | Explicit UTF-8 source/config, byte checksums, LF-controlled generated files |
| P1 | Storage layout: all | Preserve existing Linux layout and IDs; appropriate native per-user directories for new platforms |
| P1 | Python version/dependency expectations: all | Preserve 3.8 baseline; evaluate stdlib native adapters versus isolated psutil/locking dependencies |
| P1 | Test harness imports fcntl and launches /bin/sh: Windows | Keep historical Linux coverage and add native portable tests; no fake-OS claims |
| P1 | Existing Linux gate tests reject Darwin | Update intentional platform policy expectations explicitly |
| P2 | Command profiles: Windows | Keep approval digest binding, resolve executables, explicit argv; no blanket shell approval |
| P2 | Release/build/docs: all | Include native wrappers, actual CI architecture matrix, candidate status until evidence |

Shared `ccx_platform` provides paths, native locking, ownership/permission checks,
link checks, executable discovery and process identity. The installer and CLI
consume that interface. A separately versioned 4.3.0 project payload includes a
sealed copy, keeping 4.1.0 byte-for-byte intact. Platform-specific containment
belongs in the runtime adapter. Engine and project upgrades remain independent.

psutil provides portable process inspection, but would require a pinned isolated
installation and a project interpreter migration. portalocker similarly adds
installation surface and does not solve inherited lock lifetime. Prefer native
stdlib-backed adapters where they can provide equivalent guarantees; any missing
guarantee is a blocker, never a successful check.

Implementation order: (1) native platform/security layer; (2) installer and
launchers; (3) CLI and new project payload; (4) regression/portable tests and
corrections; (5) isolated Mac installation; (6) documentation and candid release
status. Linux and Windows verification require those real operating systems.

## Integration constraints

Claude CLI was not found on PATH. The user authorized Codex-led architecture,
implementation and review instead. Dedicated `codex exec --sandbox read-only`
failed before session creation: in-process app-server initialization returned
Operation not permitted and diagnostic database writes were read-only. No session
ID exists to resume. No `resume --last`, preference/authentication changes or
sandbox escalation were used. Built-in Codex agents perform scoped implementation
under the user's alternative authorization; they are not evidence of CLI resume.

## Complete tracked-file scan inventory

Every tracked file was read for this inventory, including fixtures, docs, release
metadata and hidden templates. Matches below are audit locations, not a claim that
every match is defective. Fixture platform assumptions are intentionally retained.

| File | Dependencies and review locations |
|---|---|
| `.gitignore` | No direct platform API detected; retained in format/payload review. |
| `README.md` | P1 Windows/macOS: paths and launch (lines 9, 33, 57, 58, 59) |
| `VERSION` | No direct platform API detected; retained in format/payload review. |
| `docs/CLI.md` | P0 Windows: Unix locks (lines 290)<br>P0 Windows: filesystem security (lines 8, 151, 168, 195, 288)<br>P1 Windows/macOS: paths and launch (lines 7, 8, 11, 25, 29, 136, 137, 148, 232, 233, 240, 241, 261, 262, 268) |
| `docs/MIGRATION-AND-RECOVERY.md` | P0 macOS/Windows: process supervision (lines 145)<br>P1 Windows/macOS: paths and launch (lines 13, 147) |
| `docs/RELEASING.md` | P0 macOS/Windows: process supervision (lines 22, 23, 37, 38, 40, 59, 65)<br>P1 Windows/macOS: paths and launch (lines 9, 10, 11, 16, 22)<br>P1 all: text/archive/identity portability (lines 42) |
| `docs/SECURITY.md` | P0 Windows: Unix locks (lines 44) |
| `docs/TEAM-INSTALL.md` | P0 macOS/Windows: process supervision (lines 5, 18, 19, 25, 36)<br>P0 Windows: filesystem security (lines 65, 66, 103)<br>P1 Windows/macOS: paths and launch (lines 3, 32, 39, 42, 56, 57, 61, 78, 94, 100, 111)<br>P1 all: text/archive/identity portability (lines 4, 27) |
| `docs/TEAM-UPDATE.md` | P1 Windows/macOS: paths and launch (lines 38) |
| `engine/lib/ccx_distribution.py` | P1 Windows/macOS: paths and launch (lines 26)<br>P1 all: text/archive/identity portability (lines 10, 76, 123, 140, 173) |
| `engine/lib/ccx_install.py` | P0 Windows: Unix locks (lines 117, 120)<br>P0 Windows: filesystem security (lines 37, 44, 52, 92, 240, 254, 255, 309, 322, 323, 339, 390, 405, 517)<br>P1 Windows/macOS: paths and launch (lines 1, 352, 353, 585, 589, 593)<br>P1 all: text/archive/identity portability (lines 33, 71, 79, 169, 178, 215, 312, 419) |
| `engine/lib/ccx_migration.py` | P0 Windows: filesystem security (lines 246, 297, 302, 307, 320)<br>P1 Windows/macOS: paths and launch (lines 18, 143)<br>P1 all: text/archive/identity portability (lines 28, 43, 70, 84, 161, 162, 177, 252, 306, 311, 319, 332, 338, 351) |
| `engine/orchestrator.py` | P0 Windows: Unix locks (lines 10, 300, 909)<br>P0 Windows: filesystem security (lines 116, 120, 121, 134, 135, 162, 164, 166, 167, 170, 171, 174, 176, 194, 195, 198, 206, 264, 295, 318, 346, 347, 389, 404, 411, 476, 616, 652, 655, 661, 682, 697, 780, 832, 838, 852, 866, 877, 965, 1047, 1137, 1216, 1369, 1376)<br>P1 Windows/macOS: paths and launch (lines 1, 6, 35, 68, 72, 713, 714, 716, 1136, 1518)<br>P1 all: text/archive/identity portability (lines 86, 87, 91, 149, 270, 309, 318, 465, 471, 476, 490, 499, 554, 617, 621, 656, 662, 701, 713, 723, 733, 767, 831, 843, 868, 963, 969, 970, 990, 992, 1225, 1288, 1290, 1302, 1364, 1372, 1557, 1558, 1561, 1563, 1570) |
| `engine/releases/4.1.0/VERSION` | No direct platform API detected; retained in format/payload review. |
| `engine/releases/4.1.0/checksums.json` | No direct platform API detected; retained in format/payload review. |
| `engine/releases/4.1.0/hooks/completion-gate.py` | P0 Windows: Unix locks (lines 3, 64, 66)<br>P0 Windows: filesystem security (lines 31)<br>P1 Windows/macOS: paths and launch (lines 1, 49)<br>P1 all: text/archive/identity portability (lines 30, 43, 72, 122) |
| `engine/releases/4.1.0/hooks/session-init.py` | P1 Windows/macOS: paths and launch (lines 1, 17) |
| `engine/releases/4.1.0/release.json` | No direct platform API detected; retained in format/payload review. |
| `engine/releases/4.1.0/scripts/codex-session.py` | P0 Windows: Unix locks (lines 4, 129, 160, 162, 166, 168, 256, 318, 319, 329)<br>P0 Windows: filesystem security (lines 394)<br>P1 Windows/macOS: paths and launch (lines 1, 118)<br>P1 all: text/archive/identity portability (lines 111, 132, 393) |
| `engine/releases/4.1.0/scripts/context-monitor.py` | P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 46, 55, 82) |
| `engine/releases/4.1.0/scripts/integrity-check.py` | P0 Windows: filesystem security (lines 41, 51, 54)<br>P1 Windows/macOS: paths and launch (lines 1, 18)<br>P1 all: text/archive/identity portability (lines 12, 27, 57, 69) |
| `engine/releases/4.1.0/scripts/managed-exec.py` | P0 Windows: Unix locks (lines 4, 201, 203, 206, 208, 223, 224, 249)<br>P0 macOS/Windows: process supervision (lines 265)<br>P0 Windows: filesystem security (lines 28, 193)<br>P1 Windows/macOS: paths and launch (lines 1, 22, 161)<br>P1 all: text/archive/identity portability (lines 20, 30, 52, 57, 155, 192) |
| `engine/releases/4.1.0/scripts/orchestration-status.py` | P0 Windows: Unix locks (lines 9, 53, 55, 57)<br>P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 39, 120) |
| `engine/releases/4.1.0/scripts/recovery-controller.py` | P0 Windows: Unix locks (lines 23, 157)<br>P0 macOS/Windows: process supervision (lines 6, 48, 57, 58, 73, 111, 128, 156, 162, 166, 172, 211, 371)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 79) |
| `engine/releases/4.1.0/scripts/task-state.py` | P0 Windows: Unix locks (lines 4, 96, 98, 101, 167)<br>P0 Windows: filesystem security (lines 160, 364)<br>P1 Windows/macOS: paths and launch (lines 1, 62)<br>P1 all: text/archive/identity portability (lines 56, 159, 170, 363) |
| `engine/releases/4.1.0/scripts/usage-guard.py` | P0 Windows: Unix locks (lines 4, 85)<br>P0 Windows: filesystem security (lines 118)<br>P1 Windows/macOS: paths and launch (lines 1, 72)<br>P1 all: text/archive/identity portability (lines 66, 87, 114) |
| `engine/releases/4.1.0/scripts/watchdog.py` | P0 macOS/Windows: process supervision (lines 32, 36)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 32, 56) |
| `engine/releases/4.1.0/templates/.gitignore` | No direct platform API detected; retained in format/payload review. |
| `engine/releases/4.1.0/templates/CLAUDE.md` | P1 Windows/macOS: paths and launch (lines 39, 43, 66, 68, 70, 74, 85, 89, 93, 97, 101, 105, 109, 113, 154, 158, 181, 204, 208, 234, 252, 256) |
| `engine/releases/4.1.0/templates/settings.template.json` | P1 Windows/macOS: paths and launch (lines 6, 7, 8, 9, 10, 11, 12, 13, 22, 32) |
| `install.sh` | P1 Windows/macOS: paths and launch (lines 1, 3, 7, 21, 22) |
| `scripts/build-release.sh` | P1 Windows/macOS: paths and launch (lines 1, 3, 4) |
| `tests/container/run.sh` | P0 Windows: filesystem security (lines 43, 44)<br>P1 Windows/macOS: paths and launch (lines 1, 4, 5, 15, 57)<br>P1 all: text/archive/identity portability (lines 31, 34, 37) |
| `tests/container/scenario.sh` | P1 Windows/macOS: paths and launch (lines 1, 10, 12, 14, 21, 23, 26, 27, 32, 33, 34, 38, 46, 69, 73, 89, 97, 104, 106, 107, 108, 114, 118, 119, 120, 152, 153, 155)<br>P1 all: text/archive/identity portability (lines 41, 61, 126) |
| `tests/fixtures/legacy-4.0.0/orchestrator.py` | P0 Windows: Unix locks (lines 4, 101)<br>P0 Windows: filesystem security (lines 85, 179, 180, 273, 302, 304, 321, 327, 456, 461, 467, 475, 478)<br>P1 Windows/macOS: paths and launch (lines 1, 70, 121)<br>P1 all: text/archive/identity portability (lines 30, 62, 77, 94, 186, 195, 221, 233, 354, 382, 393, 403, 407, 413, 422, 427, 433, 435, 482, 485, 533) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/VERSION` | No direct platform API detected; retained in format/payload review. |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/checksums.json` | No direct platform API detected; retained in format/payload review. |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/hooks/completion-gate.py` | P0 Windows: Unix locks (lines 3, 64, 66)<br>P0 Windows: filesystem security (lines 31)<br>P1 Windows/macOS: paths and launch (lines 1, 49)<br>P1 all: text/archive/identity portability (lines 30, 43, 72, 122) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/hooks/session-init.py` | P1 Windows/macOS: paths and launch (lines 1, 17) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/release.json` | No direct platform API detected; retained in format/payload review. |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/codex-session.py` | P0 Windows: Unix locks (lines 4, 129, 160, 162, 166, 168, 256, 318, 319, 329)<br>P0 Windows: filesystem security (lines 394)<br>P1 Windows/macOS: paths and launch (lines 1, 118)<br>P1 all: text/archive/identity portability (lines 111, 132, 393) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/context-monitor.py` | P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 46, 55, 82) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/integrity-check.py` | P0 Windows: filesystem security (lines 41, 51, 54)<br>P1 Windows/macOS: paths and launch (lines 1, 18)<br>P1 all: text/archive/identity portability (lines 12, 27, 57, 69) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/managed-exec.py` | P0 Windows: Unix locks (lines 4, 167, 169, 172, 174, 189, 190, 215)<br>P0 macOS/Windows: process supervision (lines 231)<br>P0 Windows: filesystem security (lines 159)<br>P1 Windows/macOS: paths and launch (lines 1, 127)<br>P1 all: text/archive/identity portability (lines 94, 121, 158) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/orchestration-status.py` | P0 Windows: Unix locks (lines 9, 53, 55, 57)<br>P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 39, 120) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/recovery-controller.py` | P0 Windows: Unix locks (lines 23, 157)<br>P0 macOS/Windows: process supervision (lines 6, 48, 57, 58, 73, 111, 128, 156, 162, 166, 172, 211, 371)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 79) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/task-state.py` | P0 Windows: Unix locks (lines 4, 96, 98, 101, 167)<br>P0 Windows: filesystem security (lines 160, 364)<br>P1 Windows/macOS: paths and launch (lines 1, 62)<br>P1 all: text/archive/identity portability (lines 56, 159, 170, 363) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/usage-guard.py` | P0 Windows: Unix locks (lines 4, 85)<br>P0 Windows: filesystem security (lines 118)<br>P1 Windows/macOS: paths and launch (lines 1, 72)<br>P1 all: text/archive/identity portability (lines 66, 87, 114) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/scripts/watchdog.py` | P0 macOS/Windows: process supervision (lines 32, 36)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 32, 56) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/templates/.gitignore` | No direct platform API detected; retained in format/payload review. |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/templates/CLAUDE.md` | P1 Windows/macOS: paths and launch (lines 41, 45, 68, 70, 72, 76, 87, 91, 95, 99, 103, 107, 111, 115, 153, 157, 164, 166, 168, 183, 206, 210, 236, 254, 258) |
| `tests/fixtures/legacy-4.0.0/releases/4.0.0/templates/settings.template.json` | P1 Windows/macOS: paths and launch (lines 11, 12, 13, 14, 15, 16, 17, 18, 27, 37) |
| `tests/fixtures/legacy-v3/.claude/.gitignore` | No direct platform API detected; retained in format/payload review. |
| `tests/fixtures/legacy-v3/.claude/hooks/completion-gate.py` | P0 Windows: Unix locks (lines 3, 64, 66)<br>P0 Windows: filesystem security (lines 31)<br>P1 Windows/macOS: paths and launch (lines 1, 49)<br>P1 all: text/archive/identity portability (lines 30, 43, 72, 122) |
| `tests/fixtures/legacy-v3/.claude/hooks/session-init.py` | P1 Windows/macOS: paths and launch (lines 1, 17) |
| `tests/fixtures/legacy-v3/.claude/scripts/codex-session.py` | P0 Windows: Unix locks (lines 4, 129, 160, 162, 166, 168, 256, 318, 319, 329)<br>P0 Windows: filesystem security (lines 394)<br>P1 Windows/macOS: paths and launch (lines 1, 118)<br>P1 all: text/archive/identity portability (lines 111, 132, 393) |
| `tests/fixtures/legacy-v3/.claude/scripts/context-monitor.py` | P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 46, 55, 82) |
| `tests/fixtures/legacy-v3/.claude/scripts/integrity-check.py` | P0 Windows: filesystem security (lines 41, 51, 54)<br>P1 Windows/macOS: paths and launch (lines 1, 18)<br>P1 all: text/archive/identity portability (lines 12, 27, 57, 69) |
| `tests/fixtures/legacy-v3/.claude/scripts/managed-exec.py` | P0 Windows: Unix locks (lines 4, 167, 169, 172, 174, 189, 190, 215)<br>P0 macOS/Windows: process supervision (lines 231)<br>P0 Windows: filesystem security (lines 159)<br>P1 Windows/macOS: paths and launch (lines 1, 127)<br>P1 all: text/archive/identity portability (lines 94, 121, 158) |
| `tests/fixtures/legacy-v3/.claude/scripts/orchestration-status.py` | P0 Windows: Unix locks (lines 9, 53, 55, 57)<br>P1 Windows/macOS: paths and launch (lines 1, 32)<br>P1 all: text/archive/identity portability (lines 26, 39, 120) |
| `tests/fixtures/legacy-v3/.claude/scripts/recovery-controller.py` | P0 Windows: Unix locks (lines 23, 157)<br>P0 macOS/Windows: process supervision (lines 6, 48, 57, 58, 73, 111, 128, 156, 162, 166, 172, 211, 371)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 79) |
| `tests/fixtures/legacy-v3/.claude/scripts/task-state.py` | P0 Windows: Unix locks (lines 4, 96, 98, 101, 167)<br>P0 Windows: filesystem security (lines 160, 364)<br>P1 Windows/macOS: paths and launch (lines 1, 62)<br>P1 all: text/archive/identity portability (lines 56, 159, 170, 363) |
| `tests/fixtures/legacy-v3/.claude/scripts/usage-guard.py` | P0 Windows: Unix locks (lines 4, 85)<br>P0 Windows: filesystem security (lines 118)<br>P1 Windows/macOS: paths and launch (lines 1, 72)<br>P1 all: text/archive/identity portability (lines 66, 87, 114) |
| `tests/fixtures/legacy-v3/.claude/scripts/watchdog.py` | P0 macOS/Windows: process supervision (lines 32, 36)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 32, 56) |
| `tests/fixtures/legacy-v3/.claude/settings.template.json` | P1 Windows/macOS: paths and launch (lines 11, 12, 13, 14, 15, 16, 17, 18, 27, 37) |
| `tests/fixtures/legacy-v3/CLAUDE.md` | P1 Windows/macOS: paths and launch (lines 41, 45, 68, 70, 72, 76, 87, 91, 95, 99, 103, 107, 111, 115, 153, 157, 164, 166, 168, 183, 206, 210, 236, 254, 258) |
| `tests/fixtures/legacy-v3/README-FIXTURE.md` | No direct platform API detected; retained in format/payload review. |
| `tests/test_distribution.py` | P0 Windows: Unix locks (lines 3, 259)<br>P0 Windows: filesystem security (lines 24, 25, 66, 112, 119, 255, 266, 283, 288, 292, 301, 304, 310, 314, 349, 357, 360, 363, 367)<br>P1 Windows/macOS: paths and launch (lines 1, 43, 228, 236, 271, 279, 282, 284, 340, 343, 356, 358, 361, 362, 363, 366, 368)<br>P1 all: text/archive/identity portability (lines 24, 80, 94, 95, 101, 102, 107, 116, 125, 126, 128, 142, 144, 145, 157, 158, 173, 177, 189, 192, 213, 220, 230, 231, 241, 242, 323, 325, 329, 330, 335, 336, 342, 351, 362, 366) |
| `tests/test_migration.py` | P0 Windows: Unix locks (lines 3, 249)<br>P0 Windows: filesystem security (lines 24, 93, 96, 217, 222, 226, 295, 307)<br>P1 Windows/macOS: paths and launch (lines 1, 38, 59)<br>P1 all: text/archive/identity portability (lines 20, 24, 25, 42, 45, 46, 47, 55, 58, 66, 68, 90, 94, 99, 121, 133, 137, 138, 145, 151, 161, 170, 173, 178, 181, 189, 195, 206, 230, 233, 240, 294, 304) |
| `tests/test_orchestrator.py` | P0 Windows: Unix locks (lines 12, 734, 741)<br>P0 Windows: filesystem security (lines 60, 63, 101, 113, 114, 196, 584, 588, 592, 600, 605, 620, 627, 639, 766, 772, 804, 861, 879, 887)<br>P1 Windows/macOS: paths and launch (lines 1, 5, 8, 34, 105, 151, 288, 299, 328, 705, 900, 920)<br>P1 all: text/archive/identity portability (lines 57, 64, 67, 71, 75, 77, 78, 94, 96, 97, 98, 100, 126, 154, 161, 162, 164, 166, 173, 175, 180, 199, 209, 213, 228, 229, 231, 235, 257, 263, 269, 272, 273, 274, 306, 328, 342, 345, 382, 386, 388, 431, 452, 483, 485, 506, 510, 517, 518, 608, 636, 637, 638, 648, 650, 656, 659, 660, 661, 669, 678, 682, 686, 693, 694, 697, 707, 709, 783, 784, 786, 798, 799, 801, 803, 854, 855, 857, 860, 877, 899, 902, 905, 914, 922, 924, 935, 937, 941, 942, 945, 947, 949, 950, 952, 953, 977, 978, 983) |
| `tests/test_repository_hygiene.py` | P0 Windows: filesystem security (lines 40, 41)<br>P1 Windows/macOS: paths and launch (lines 1, 10, 23)<br>P1 all: text/archive/identity portability (lines 39) |
| `tests/test_self_update.py` | P0 Windows: Unix locks (lines 3, 374)<br>P0 Windows: filesystem security (lines 26, 27, 130, 131, 135, 175, 243, 255, 314, 315, 337, 340, 343)<br>P1 Windows/macOS: paths and launch (lines 1, 83, 84, 88, 176, 195, 228, 390)<br>P1 all: text/archive/identity portability (lines 14, 26, 53, 63, 65, 90, 92, 149, 160, 211, 237, 239, 242, 244, 251, 271, 277, 278, 285, 321, 329, 334, 342, 380, 389, 391, 396, 401) |
| `tools/build_release.py` | P0 Windows: filesystem security (lines 24, 32)<br>P1 Windows/macOS: paths and launch (lines 1)<br>P1 all: text/archive/identity portability (lines 13, 37, 59, 67, 69, 77) |
| `uninstall.sh` | P1 Windows/macOS: paths and launch (lines 1, 3, 7, 21, 26) |
