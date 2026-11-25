# Independent review of the controlled soak harness

Reviewed `tools/soak_workspace.py` on 2026-11-25. This is a source review and a read-only observation of an ongoing run, not its final outcome. The reviewer did not stop, alter, or clean up the running soak.

## Isolation and result validity

- Runtime library and immutable supervisor payload are copied into a generated temporary directory. Three generated Git projects and the SQLite database are separate from the source checkout and client repositories.
- The registry is explicitly offline. Its provider names do not invoke native provider executables or APIs. Synthetic usage values must remain labelled mock data.
- Implementation changes use scoped patches. The direct `app.txt = bad` write occurs before creating the next workflow and is a controlled fixture fault injection.
- Execution uses actual approved test subprocesses, SQLite state, source snapshots, engine review gates, fresh controllers and backup reopening. Reviewer decisions themselves are deterministic fixtures.
- Durations are real monotonic time. Input bounds cap duration at 7,200 seconds, quiet commands at 600 seconds and workflows at 5,000. Reaching the workflow cap before the duration is reported as `CAPPED_EARLY`, not a passed duration.
- Expected no-progress and failed-test cases must be `BLOCKED`; successful cases require verified task/test evidence and preserved memory. Database integrity is checked each iteration.
- RSS fields distinguish current process RSS from peak process RSS. Child CPU is cumulative for completed children. These samples cannot establish the absence of leaks or provider resource behavior.

## Observed running sample

At 594.54 elapsed seconds the report was `RUNNING`, with 426 recorded workflows, 466 resource samples, 60 context packages and 38 observed healthy lease changes. These observations support actual progress and bounded context-package retention; they do not constitute the completed soak result.

The read-only filesystem sample contained 43 full database backups totaling 350,244,864 bytes, alongside an approximately 18.5 MB live database. The progress report was about 295 KB. Values are a point-in-time observation and may differ from final totals.

## Remaining harness concerns

| Severity | Finding | Recommendation |
|---|---|---|
| Medium | Full backups are retained every ten workflows. Count/time bounds are finite, but aggregate backup storage grows approximately quadratically with workflow history; no byte/free-space guard exists. | Before a larger soak, add an explicit runtime-byte or free-space budget and report `CAPPED_RESOURCE` while preserving collected evidence. Do not silently delete historical records. |
| Medium | Harness assertions and approved Python acceptance assertions can be disabled by optimized Python (`-O` or inherited `PYTHONOPTIMIZE`). | Record and enforce nonoptimized harness and child interpreters, or use explicit exceptions for acceptance checks. This is an alternate-invocation weakness, not a demonstrated failure of the current normal invocation. |
| Low | The docstring promises progress at least every 15 seconds, but the monitor waits 15 seconds plus sampling/SQLite/I/O time. | Describe 15 seconds as the nominal monitor interval; use recorded sample timestamps to assess actual gaps. |

No production security weakening or unauthorized provider usage was found in the inspected harness. No code change was made during this review. The final run report must retain the actual duration, status, failures, resource samples and mock-provider limitations.
