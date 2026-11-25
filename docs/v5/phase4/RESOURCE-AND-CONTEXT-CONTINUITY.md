# Resource and context continuity observations

Date: 2026-11-25. Scope: native Linux, generated repositories, actual local engine/storage/subprocesses, deterministic provider responses. No live-provider efficiency or daily-use readiness claim follows from these measurements.

## Controlled soak

The measured run lasted **900.309 seconds** and recorded **655 workflows** across three isolated Git projects: **511 completed** with engine-observed test evidence and mock review, and **144 intentionally blocked**. Every iteration reopened `Store` and constructed a new `WorkflowEngine`. Each iteration retrieved its own architecture marker and asserted that the other two projects' markers were absent. Completed workflows had a persisted verification-memory record after reopening storage.

The run used 102 controlled review-correction scenarios, 59 failing test commands, and 85 repeated incomplete-response scenarios. The first workflow ran a silent test command for 75 seconds and completed in 75.217 seconds. These results show bounded local progress and durable state under the fixture workload; they do not establish real model reasoning or provider-session reliability.

| Measurement | Observed value | Interpretation |
|---|---:|---|
| Resource samples | 716 | Nominal monitor interval was 15 seconds, with extra samples after each workflow |
| Largest recorded sample gap | 15.004 seconds | Observed cadence; not a strict real-time scheduling guarantee |
| Current process RSS, first/final | 28,192,768 / 36,364,288 bytes | Includes harness and retained measurement records |
| Largest sampled current RSS | 36,368,384 bytes | Sampled resident memory; transient peaks may be missed |
| Process peak RSS | 66,891,776 bytes | OS high-water mark, distinct from steady-state RSS |
| Process CPU increase | 118.5611 seconds | Parent process cumulative CPU, not instantaneous utilization |
| Completed-child CPU increase | 81.2846 seconds | Includes completed owned subprocesses; not provider CPU |
| Database size, first/final | 81,920 / 31,166,464 bytes | History was deliberately retained |
| Database growth | 31,084,544 bytes | Not a before/after optimization result |
| Final checkpoints / payload bytes | 11,340 / 1,971,401 | Measured SQLite checkpoint content, not all process output bytes |
| Final context-package count | 60 | Reached the implemented 20-per-project retention bound |
| Final memory records | 675 | Includes fixture architecture and workflow evidence records |
| Backup/reopen comparisons | 66 | Reopened backup memory matched source memory at each check |
| Healthy running lease observations | 57 | Distinct sampled lease values; not a count of every heartbeat |

This run does not prove the absence of leaks. Memory rose while the harness retained workflow/sample metadata, and the database retained history. Separating application steady-state memory from harness bookkeeping, comparing repeated equal-size runs, and testing longer histories remain necessary for a leak diagnosis. No idle-CPU, active-child RSS, provider RSS, provider latency, browser responsiveness, cold/warm startup, or production event-throughput result is inferred from this soak.

Independent review identified approximately quadratic aggregate storage growth from retaining a full backup every ten workflows. At one recorded observation, 50 backups occupied 492,675,072 bytes with 39,672,606,720 bytes free. This was safe for the observed temporary filesystem but unsuitable as an unbounded strategy. The subsequent harness now defaults to a 256 MiB backup budget and 512 MiB free-space floor, records skipped backups, and never deletes collected evidence to satisfy the cap. Its three focused guard tests passed. The 900-second run preceded those guards; only a short real-engine smoke validates the guarded invocation so far.

## Context continuity evidence

| Area | Evidence and observed behavior | Limit |
|---|---|---|
| Reopening project knowledge | Every soak workflow used fresh store/controller instances and recovered the selected architecture marker | Same long-running harness process; not a machine restart or independent native AI session |
| Cross-project scope | Three markers remained isolated in every soak retrieval; Phase 3 context tests also reject foreign workflow/task IDs through MCP and include malicious repository instructions | Broader adversarial paths still require their own tests; model compliance is not the boundary |
| Completed work memory | Successful soak workflows required a persistent verification-memory reference after reopening storage | Mock reviewer acceptance does not prove independent model quality |
| Backup integrity | 66 backup/reopen memory comparisons; a near-final private SQLite copy returned `integrity_check=ok` | The retained snapshot was captured before the final three workflows completed |
| Pause and continuation | Workload G records fresh-controller continuation and zero repeated scoped patches after the deliberate pause | It is not a backend crash or OS reboot; the separate pause/resume regression now passes six independent checks |
| Source freshness | Phase 3 context regression covers branch changes, rename/delete, stale source-backed instructions and deleted-memory context regeneration | Not a measured semantic retrieval benchmark across real development tasks |
| Required constraints | Phase 3 regression requires complete root/user instructions or an explicit budget failure | No claim of unlimited context or automatic hierarchical summarization |
| Provider handoff/session ownership | Existing deterministic workflow tests exercise destination approval, role-specific session mapping and exact supplied session IDs | Mocked contracts only; native Codex/MiniMax/Claude resume and handoff remain live-verification requirements |
| Real context/token benefit | No live matched A/B provider measurement occurred | Real token/cost savings, reduced human effort and model-quality equivalence are unverified |

The pause/resume fix was independently reviewed against original journaled permissions: only unchanged scoped read-only planner/reviewer work can be reissued after explicit resume. Executor/native-access or changed-snapshot cancellations require recovery approval. Six focused resume tests, 21 reliability tests, and four cancellation tests passed independently; [RESUME-INDEPENDENT-REVIEW.json](RESUME-INDEPENDENT-REVIEW.json) records commands and scope. These are mock-provider contracts with real local engine behavior.

The representative workload evidence is in [WORKLOAD-EVIDENCE.json](WORKLOAD-EVIDENCE.json). Workload G explicitly distinguishes a fresh controller from a machine restart; its generated provider session IDs are fixture IDs. The retained Phase 3 tests establish narrower automated boundaries and must not be upgraded to native provider or platform verification.

## Durable evidence

- [SOAK-EVIDENCE.json](SOAK-EVIDENCE.json): complete recorded samples, fixture workflow IDs, outcomes and mock-call counts.
- [SOAK-RESOURCE-SUMMARY.json](SOAK-RESOURCE-SUMMARY.json): derived values used above.
- [SOAK-PROVENANCE.json](SOAK-PROVENANCE.json): original harness digest and observed invocation/environment limits.
- [SOAK-DATABASE-EVIDENCE.json](SOAK-DATABASE-EVIDENCE.json): private near-final snapshot digest, integrity and record counts; no database binary is included here.
- [soak-guard-tests.log](soak-guard-tests.log): three focused tests for optimization refusal, resource bounds and an actual short engine smoke.
- [SOAK-EVIDENCE-MANIFEST.json](SOAK-EVIDENCE-MANIFEST.json): original/retained hashes and path-prefix redactions. No measured values were changed.

The near-final database contains 652 workflows, including one still running at capture time. The final JSON contains all 655 terminal fixture outcomes. This difference is expected and recorded; the snapshot is not represented as a terminal backup of the complete run. The private snapshot remains outside repository and release artifacts.

## Automatic learning boundary

Source inspection of `WorkflowEngine._correction` and the completion path confirms
that correction observations are stored with workflow/task provenance and a 30-day
expiry; they remain observations, not independently established model conclusions.
Successful completion stores a snapshot-bound verification summary with criteria,
review action IDs, test exit codes and the resolved-correction summary. An exact existing
workflow/snapshot/body record is reused, then project sources are reindexed.

This is narrower than automatically rewriting architecture, business requirements,
technical decisions and every historical bug entry. Old correction observations may
still carry `resolved: false`; the completion record separately states prior corrections
resolved. No semantic contradiction reconciliation or automatic promotion of all useful
model lessons was demonstrated. Session references persist in workflow/session tables,
not as an unlimited native conversation memory. Those limits remain visible rather than
claiming the full requested automatic-learning behavior from verification receipts alone.
