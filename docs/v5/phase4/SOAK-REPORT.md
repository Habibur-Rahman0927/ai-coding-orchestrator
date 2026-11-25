# Controlled local soak

Status: **PASSED**. Actual wall duration: **900.309 seconds**; target: 900 seconds.

655 workflows: 511 completed and verified by engine checks with mock reviewers; 144 intentionally blocked. Live provider calls: **0**.

The runtime was copied into a disposable directory and exercised three separate generated Git projects. Actual SQLite, approved subprocesses, scoped patches, context retrieval, controller reopen, and backups were used. A 75-second quiet command exercised healthy running lease renewal. No-progress and failed-test fixtures were required to stop in bounded blocked states.

Progress JSON: `/tmp/ccx-phase4-soak.json`. It contains measured memory/CPU/database/checkpoint growth, workflow IDs and outcomes. RSS is a process observation, not proof of absence of leaks. Provider decisions are deterministic fixtures, not real independent-model acceptance. No machine reboot, native Windows/macOS soak, or 30/60-minute run is claimed.

## Evidence and measured limits

The 900.309-second run used harness SHA256 `eb744edc4cdbdb8a727c7f89c3619338a03d587bd38159584f18d05244ebfce3`, preserved privately with fixture evidence. It ran before the later harness resource guards. The launch command omitted `-O`; the matching launch environment had `PYTHONOPTIMIZE` unset and interpreter optimization level 0. The running process was not separately inspectable across the tool process namespace, so that environment observation is not represented as an in-process measurement.

Final observations: current process RSS 36,364,288 bytes; peak RSS 66,891,776 bytes; database 31,166,464bytes ; 11,340 checkpoints containing 1,971,401 payload  bytes; 60 context packages (20 per project). There were 102 controlled correction scenarios, 59 failed-test cases, and 85 no-progress cases. Historical evidence accumulated intentionally. These measurements do not prove absence of a memory leak or establish an unlimited retention policy.

A consistent near-final SQLite snapshot was preserved at 895.417 seconds in the private directory `/tmp/ccx-phase4-soak-evidence/`, filename `workspace-final.sqlite3`. Its SHA256 is `e001d18d8895ef6e263172838c92044a339eb9cf333d05aed8707353082bf413`; SQLite integrity check returned `ok`. It contains 652 workflows: 508 completed, 143 blocked, and 1 running at snapshot time. It is intentionally labelled near-final, not a terminal snapshot of all 655 workflows. `database-evidence.json` records the counts and digest. The snapshot contains only generated fixture state and is not packaged into repository/release artifacts.

## Harness hardening after the measured run

Independent review found that optional periodic backups accumulated without an explicit byte cap, and Python optimization could disable acceptance assertions. The current harness rejects optimized execution before creating artifacts, records the optimization level and source digest, caps retained fixture backups at 256 MiB by default, and reserves 512 MiB free space. When another backup exceeds the configured cap/headroom it records an explicit skipped-backup reason while continuing other checks. Falling below the free-space floor prevents further workflow work. Existing evidence is not deleted to meet these budgets.

Three focused tests passed, including actual subprocess checks for `-O` and `PYTHONOPTIMIZE=1`, measured backup-byte/free-space boundaries, and an actual short engine smoke with the backup cap reached. The 900-second run has **not** been repeated with these guards; its original evidence is preserved separately. Current guarded harness SHA256: `03ae6a2f76f0e66215a46acc38f684ea9aa30af23cd6399e37642079a65b7f07`.
