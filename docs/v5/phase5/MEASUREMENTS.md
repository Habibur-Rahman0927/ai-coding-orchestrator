# Synthetic quality and performance measurements

The same generator and corpus hashes were used against a frozen Phase 4 runtime copy
and Phase 5. All data is generated; no client repository or provider was accessed.
The three corpora contain 39, 263 and 1,031 files. These sizes are relative local test
sizes, not proof of performance on an enterprise monorepo. Eight ground-truth tasks per
size cover architecture, rare symbols, explicit paths, separated symbols, historical
solutions, dependency/test references, persistent decisions and unrelated-query rules.

[BASELINE.json](BASELINE.json) and [OPTIMIZED.json](OPTIMIZED.json) retain individual
samples, CPU, source reads, Git process counts, bytes, estimates, references, indexing and
storage metrics. [COMPARISON.json](COMPARISON.json) is derived from those records.

Complete required-context recovery: **16/24 → 24/24 cases**. Required elements recovered:
**22/30 → 30/30**. Required constraints: **24/24 before and after**. Fresh-controller
knowledge recovery, stale source rejection and cross-project marker isolation passed at
each size. This is a small deterministic evaluation, not measured live development quality.

| Corpus files | Initial index ms, before → after | Unchanged index ms, before → after | Duplicate memory rows | Final DB bytes |
|---:|---:|---:|---:|---:|
| 39 | 22.017 → 23.339 | 11.801 → 10.210 | 10 → 1 | 151552 → 163840 |
| 263 | 112.210 → 107.816 | 44.855 → 42.956 | 10 → 1 | 462848 → 479232 |
| 1031 | 645.216 → 478.466 | 177.028 → 163.529 | 10 → 1 | 1519616 → 1527808 |

Timing uses three unpinned samples per retrieval case, not three fresh full index runs.
Initial/unchanged indexing figures are single observations and are not an optimization
claim by themselves. Full samples expose variability. Informational timing guard: median
must stay below max(2× baseline, baseline + 5 ms); every recorded case passed. The 5 ms
allowance avoids treating sub-millisecond scheduler noise as a failure. This provisional
guard is not an SLA or a statistically established production threshold.

| Files | Query | Median ms before | Median ms after | Git checks before → after | Context bytes before → after |
|---:|---|---:|---:|---:|---:|
| 39 | rare_symbol_among_common_matches | 62.892 | 12.948 | 37 → 3 | 1309 → 1309 |
| 39 | explicit_path | 6.673 | 6.565 | 2 → 3 | 190 → 290 |
| 39 | distributed_symbols | 8.307 | 7.481 | 3 → 3 | 744 → 901 |
| 263 | rare_symbol_among_common_matches | 175.217 | 24.409 | 102 → 3 | 946 → 1163 |
| 263 | explicit_path | 6.574 | 7.213 | 2 → 3 | 190 → 290 |
| 263 | distributed_symbols | 8.062 | 6.889 | 3 → 3 | 744 → 901 |
| 1031 | rare_symbol_among_common_matches | 271.319 | 26.483 | 102 → 3 | 946 → 1163 |
| 1031 | explicit_path | 8.883 | 8.025 | 2 → 3 | 190 → 290 |
| 1031 | distributed_symbols | 11.354 | 7.294 | 3 → 3 | 744 → 901 |

The broad common-term query benefits from batched fresh Git checks and correct candidate
ranking. Content is still read/hashed for freshness; no reusable-ID cache bypass is claimed.
Some narrow queries cost more due to metadata ranking, and several packages grow because
missing required evidence is now present. A shorter but incomplete baseline is not counted
as successful compression. Byte estimates are not provider-reported token savings.

A same-content timestamp touch now reads/hash-checks the touched file but performs zero
parses/search-document rewrites; the baseline rewrote it. A real one-file edit still updates
one file. Ordinary unchanged indexing reads zero content bytes in both versions. Directory
and Git discovery remain O(project file count); no event-driven watcher was introduced.

Memory duplicate suppression stores one active record for ten identical submissions,
without merging distinct provenance or promoting hypotheses. Richer context metadata,
FTS state and preserved resolution receipts can increase database size; no unlimited
history-retention or leak-free claim is made. Per-process peak RSS includes prior corpus
work and harness objects; it is not isolated engine steady-state RAM.

## Existing routing policy measurements

[POLICY-MEASUREMENTS.json](POLICY-MEASUREMENTS.json) runs a controlled API task three
times per policy and a correction task once per policy. Standard versus single_task used
4 versus 3 fixture calls for the API task and 7 versus 6 for the correction task. Actual
patches, acceptance subprocesses and separate file-inspecting review fixtures passed;
the correction task retained its correction cycle. Four scripted approval grants were
needed in both modes: **no human-interaction reduction was demonstrated**. The policy
already existed; this phase measures it rather than inventing a new routing hierarchy.

The initial policy harness incorrectly requested `planned`; the engine correctly rejected
it. The harness was corrected to the supported `standard` name. That failed attempt is
retained separately and is not an application defect or a successful run.

## Current-source sustained local run

The guarded harness ran for **120.790 seconds**, with **96 workflows**, **76 completed**
and **20 intentionally blocked**. No unexpected failure occurred. Providers were fixtures;
SQLite, scoped effects, tests, indexing, retrieval, backup/reopen and controller continuity
were real. This is a 120-second Phase 5 regression soak, not a repeated Phase 4 15-minute
run, a live provider soak or a machine restart. Resource samples are retained in
[SOAK-EVIDENCE.json](SOAK-EVIDENCE.json). Backup storage was bounded to 32 MiB and the
minimum free-space floor remained enabled.

Real A/B/C token totals, cached input effects, actual costs, native session growth,
production idle CPU/RAM, IDE interference and real user effort remain unmeasured.
