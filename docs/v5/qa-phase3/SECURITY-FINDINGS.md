# Security findings and corrections

Severity follows request §5. All credentials in reproductions were synthetic.
The pre-fix source remains identified by `c933c04`; no production history was erased.

| ID | Severity / requirement | Actual behavior before correction | Expected / correction | Evidence |
|---|---|---|---|---|
| S1 | CRITICAL; §7,22,24 | Indexer rejected recognizable GitHub tokens, but scoped read/search returned them; duplicate filters disagreed | Shared conservative detector used for indexing, tools, patches and command/diff output | `security-before.log`, `security-after.log`; test_v5_phase3_security |
| S2 | CRITICAL; §22,24 | Provider output/history persisted secrets in actions and browser results; split events could bypass per-event filtering | Validate nested results and accumulated output before durable storage/telemetry; refuse uncertain workflow result and require recovery | `output-before.log`, `output-review-before.log`, `output-review-after.log`; test_v5_phase3_output |
| S3 | HIGH; §18,22,29 | FIFO open blocked before regular-file validation, hanging source/tool reads | lstat, nonblocking/no-follow open where supported, bounded descriptor validation and identity checks | security tests include actual FIFO and controlled file-to-FIFO swap |
| S4 | HIGH; §16,18,25 | Cancel/pause changed state while approved subprocess kept executing | Propagate cancellation into tests/tools; terminate owned supervisor; preserve uncertain action for reconciliation | `cancel-before.log`, `cancel-after.log`, `cancel-postdeadline-review.log` |
| S5 | HIGH; §8,10,11 | Context silently discarded root constraints beyond line 24 and long user instructions | Preserve complete current root/user instructions first; reject insufficient budget explicitly | `context-before.log`, `context-after.log` |
| S6 | CRITICAL; §22,24 | Workflow objective/criteria, task text and nested approval scope stored recognizable credentials before later validation | Validate text and nested approval scope before insertion; benign exact command arguments preserved | `input-before.log`, `input-after.log`, `approval-before.log`, `approval-after.log` |
| S7 | HIGH; §8,9,26 | Deleting replacement memory revived superseded facts; a timestamp-only correction also failed under clock rollback | Atomically expire predecessor with a fixed past sentinel while retaining historical record | `storage-before.log`, `storage-independent-clock.log`, storage regression |
| S8 | HIGH; §26,32 | Unsupported future schema was changed before version rejection | Preflight schema version before any DDL | storage future-version byte-preservation regression |
| S9 | HIGH; §19,26 | Failed initialization committed partial schema before raising | Explicit schema transaction rolls back all DDL on failure | storage injected-failure regression and independent SQLite page-cap test |
| S10 | MEDIUM; §26 | Disk-full/locked/corrupt errors were hidden as optional FTS unavailability | Only missing FTS module uses fallback; other storage errors propagate and roll back | `storage-fts-before.log`, `storage-independent-fts-cap.log` |
| T1 | MEDIUM; §3,33 | Mock runtime fixtures inherited unsafe checkout file modes and failed before exercising intended session behavior | Normalize only disposable copied payload modes to remove write permissions; runtime security unchanged | baseline/final-expanded failures, `runtime-fixture.log` |

Sources: `engine/lib/ccx_workspace/{security,store,tools,providers,chat,workflows}.py`.
Independent review reproduced S1–S4, reviewed output correction and found the
additional streaming gap, and approved context/cancellation fixes. Same assistant
model in separate contexts; this is not independent-provider verification.

Remaining limitations: recognizers cannot detect arbitrary or encoded secrets.
Approved native CLI access and exact commands have intentionally broader authority
than filtered tools. Same-user filesystem races are not a complete OS sandbox.
No real vault CRUD, native Windows containment, or live-provider security claim.
Historical records were not rewritten or deleted; remediation of existing sensitive
history needs a separately authorized investigation. Test fixtures contained no
real secrets. No security-pass label is issued for the entire requested scope.
