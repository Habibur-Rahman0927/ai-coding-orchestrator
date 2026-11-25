# Phase 4 isolated workload evidence

Date: 2026-11-25. Status: **MOCK_TESTED_WITH_REAL_LOCAL_EFFECTS**.

The harness creates disposable Git repositories and separate disposable runtime databases. All implementation edits use the real workflow engine’s authorized `patch` tool, including hash preconditions. Actual Python unittest subprocesses provide acceptance evidence for A/C/D/E/F/G; B uses actual Chrome/CDP browser interactions. SQLite checkpoints, review gates, completion, project memory, and reopening use the production implementation. No client project, provider credential, external endpoint, or live provider was used.

Providers are deterministic protocol fixtures. The reviewer reads actual source files and checks engine test artifacts against explicit expected fixture content; this validates the correction mechanism, not independent model reasoning or live development quality. The fixtures report no provider token usage. Engine estimates must not be interpreted as measured tokens or savings.

## Observed results

| Workload | Calls (mock) | Correction rounds | Engine test exit codes | Scoped patches | Seconds |
|---|---:|---:|---|---:|---:|
| A — Backend calculation defect and reviewer correction | 6 | 1 | 0, 0 | 3 | 0.586 |
| B — Frontend counter reset verified by actual browser interaction | 3 | 0 | 0 | 1 | 2.538 |
| C — Local API handler failure contract (no HTTP listener) | 3 | 0 | 0 | 1 | 0.357 |
| D — Stable deduplication algorithmic bottleneck | 3 | 0 | 0 | 1 | 0.541 |
| E — Multi-file refactor with compatibility acceptance | 3 | 0 | 0 | 2 | 0.35 |
| F — Deliberate regression mutation detected by actual tests | 5 | 1 | 1, 0 | 2 | 0.561 |
| G — Documentation and knowledge recovery through fresh controller | 3 | 0 | 0 | 1 | 0.39 |

All seven workflows reached `COMPLETED`, passed an independent final acceptance invocation (unittest or actual Chrome), had current verified evidence, retained one verified workflow-memory record after reopening, and returned SQLite `integrity_check=ok`. Every fixture’s initial acceptance command failed before implementation. D’s separate baseline semantic test passed: its failing acceptance concerned measured algorithm work, not incorrect output.

- **A — backend defect:** the executor first emits a controlled zero-quantity bug. The deliberately limited first test passes, but the reviewer rejects the actual source and missing edge test. A second scoped patch fixes the implementation and adds the zero-quantity regression; real acceptance and review then pass.
- **B — frontend control:** actual Chrome clicks expose the initial Reset defect (baseline command exits 1). The executor emits one scoped HTML/JavaScript patch; the engine-approved browser command exits 0 and a separate final browser command exits 0. Increment behavior and absence of JavaScript exceptions are checked.
- **C — API failure handling:** actual handler calls retain normal and legacy empty-name responses and normalize injected `TimeoutError`/`ConnectionError` to the stable 503 contract. The API convention remains in project memory. This is a local handler test, not HTTP end-to-end evidence.
- **D — controlled algorithm bottleneck:** stable deduplication is initially semantically correct but performs repeated equality scans. Actual hashing/equality instrumentation exceeds the public work budget. The engine applies one scoped patch, preserving order and empty/repeated/negative input behavior while satisfying the budget. Timing measurements are separate observations, not acceptance thresholds.
- **E — multi-file refactor:** a scoped create of `normalize.py` and replacement of `render.py` preserve ordinary, empty and Unicode input behavior under real tests.
- **F — regression mutation:** the executor deliberately introduces a wrong implementation through the scoped patch tool. The actual engine test exits 1; the correction loop applies the correct implementation and the test exits 0. The mutated state cannot complete.
- **G — documentation/recovery:** after the scoped documentation edit, the harness deliberately pauses. A fresh Store, WorkflowEngine and provider fixture instance continue from persisted state. No patch is replayed; native-session references are retained as mock identifiers. The no-deployment rule, recovery convention and verified memory survive reopening.

## Intervention and usage accounting

Each workload receives exactly four fixture-issued approval grants: sharing for two mock roles, patch permission, and the exact acceptance command (unittest or B’s browser script). G additionally issues one pause and one resume (six counted actions). These counts exclude fixture creation, registration and workflow creation and describe only the synthetic control sequence. No human effort, improvement over manual work, model capability, provider usage or cost superiority is inferred.

Live execution is deliberately unavailable in this harness: `run_workload(..., live=True)` raises before creating a repository or accessing a provider. The separate authorized live pilot must establish real provider, session, review and token evidence.

## Reproduction and evidence

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s tests -p test_v5_phase4_pilot.py -v
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/pilot_workloads.py --output /tmp/ccx-phase4-workloads.json
```

Targeted regression: **7 tests passed** (see retained current test log for duration), exit 0. Harness runs: all six non-browser workloads and the separately authorized native-browser B workload completed, exit 0. [Machine-readable evidence](WORKLOAD-EVIDENCE.json) records actual fixture workflow/session identifiers, decisions, source hashes and counts. Test log: `/tmp/ccx-phase4-workload-tests.log`.

All generated repositories and databases are removed by their fixture context after evidence is collected. No immutable V4 payload or production source was changed for these workloads. No pilot-readiness or live-integration label is granted by this report.

## D performance measurements

The controlled input contains 1,024 hashable values, including 512 duplicates.
Acceptance counts public equality and hashing operations and requires at most
8,192 operations; it does not assert a selected source string or a wall-clock
speed threshold. Output order and edge cases are independently asserted.

| Measurement | Before | After |
|---|---:|---:|
| Baseline semantic unittest exit | 0 | 0 |
| Equality plus hashing operations | 262144 | 1536 |
| Median function-call time, seven samples (ms) | 1.336147 | 0.017500 |

Timing samples exclude process startup/imports, use the same 1,024 integer input,
and are preserved in the JSON evidence. They describe this generated algorithm
fixture only; no workspace-wide speedup, model quality, token or cost benefit is
claimed.

## B native browser run

B is deliberately selected separately because native Chrome/CDP needs process
and loopback permissions absent from ordinary sandboxed unit runs:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B tools/pilot_workloads.py --workload B --output /tmp/ccx-phase4-workload-B.json
```

The generated page starts at zero; two actual browser clicks increment to two;
Reset must return zero without JavaScript exceptions. Initial Reset incorrectly
sets one. A mocked executor emits the scoped source patch; engine acceptance and
a final independent browser invocation both passed. The recorded sequence is
initial acceptance exit **1**, engine acceptance exit **0**, independent final
acceptance exit **0**. Chrome **144.0.7559.109** ran with its sandbox enabled; no
JavaScript errors were recorded. B completed in **2.538 seconds**, with three
mock provider calls, one scoped patch, no correction round and one verified memory
record. Its exact result was merged into the aggregate evidence without rerunning
or replacing any non-browser measurements.
