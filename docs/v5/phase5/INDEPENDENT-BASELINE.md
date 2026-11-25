# Independent context and memory baseline review

Date: 2026-11-25. This is a separate read-only review context. Production files were not modified. The reviewer copied the baseline library into a disposable review directory before reproducing findings, so concurrent implementation changes cannot silently change the baseline under test.

Baseline `store.py` SHA256: `e34269d4da1e687f5d6b4ee8e49d2d7fbade5b8f51fb473481caa0377d0725da`. Python 3.12.3. All inputs were generated in an isolated Git project; no user repository, credential, provider process, or external model was used. [INDEPENDENT-BASELINE.json](INDEPENDENT-BASELINE.json) contains the observations. The reproducible script and frozen library remain privately under `/tmp/ccx-phase5-independent-baseline/`.

## Confirmed findings

| Requirement | Severity | Observed behavior | Minimal correction and verification |
|---|---|---|---|
| §7, §23: relevant-source recall | High when omitted evidence is required | With 130 generic files before `z_target.py`, query `shared exact_symbol` returns 100 files scoring one matched term. The target matches both terms but is absent because SQL applies `LIMIT 100` before Python relevance sorting. | Rank candidates before limiting, with deterministic ties. Assert the target is included when irrelevant/common matches exceed 100; test more than one insertion order. |
| §7, §8: filename/symbol retrieval | Medium | Query `z_target.py` returns no target although that indexed file exists. FTS indexes body rather than file path; current Python scoring also checks body alone. | Include exact path/symbol metadata in ranking without discarding scoped freshness/security checks. Test exact filenames, paths and existing symbol syntax. |
| §7: fallback correctness | High when FTS is unavailable and required evidence falls beyond the candidate window | With FTS disabled on the same fixture, even the specific query `exact_symbol` misses the target after the first 100 documents. | Apply matching/ranking before the limit in the fallback too. A fast path must not silently become a first-page-only search. |
| §3, §31: repeated retrieval overhead | Medium | Each of two identical context requests launches 102 `git check-ignore` subprocesses and rereads 100 files/4,790 source bytes. Both return the same persisted context-package ID. Observed latency was 165.626 and 173.058 ms. | Batch Git exclusion checks using NUL-delimited input. The cache currently deduplicates storage, not retrieval work. Do not remove current ignore, link, permissions, secret, or content-freshness checks to make the metric smaller. |
| §5: duplicate-memory accumulation | Medium | Twenty identical submissions with the same project/scope/kind/title/body create twenty distinct IDs and twenty stored records. | Transactional exact-semantic deduplication can reuse an existing active record. Keep distinct source hashes, scopes, evidence kinds, confidence, verification/expiry metadata and supersession relationships distinct; never overwrite history to merge uncertain claims. Test concurrent identical submissions and deletion/readdition semantics. |

The unranked SQL query has no explicit ordering contract. This fixture consistently returned the alphabetical early documents, but the review does not claim randomized results were observed. The defect is reproducible candidate loss before relevance evaluation, with unspecified tie/order behavior as an additional maintainability risk.

## Existing indexing behavior worth preserving

All 131 fixture files were initially indexed, reading 6,323 bytes in 56.507 ms. Repeated indexing read **zero source-content bytes**, reported all 131 unchanged, and took 23.991 ms. Thus this baseline already avoids rereading unchanged file contents during indexing. It still enumerates Git paths and validates per-file metadata; do not describe a future change as eliminating a full content rescan that was already absent.

These are one synthetic initial/repeat pair and two retrieval samples. They establish reproducible work counts and correctness failures, not statistically robust speedup percentages. Comparable before/after measurements should use identical source fixtures, explicit required references, repeated samples and recorded implementation digests.

## Benchmark review

`benchmark.py` labels byte/token estimates separately from provider-reported usage and does not invent cost savings. `compare_workflows` includes all existing planner/executor/reviewer action records, refuses mocked/incomplete runs, compares initial source hashes/models, and explicitly withholds native-provider comparison when inherited settings are not independently captured. Preserve those safeguards.

The lightweight context benchmark reports reference count and a descriptive quality string; it has no required-source ground truth. The confirmed missing-target fixture can therefore produce a smaller package without meeting the task's needs. Add expected required references/constraints and report misses independently of byte reduction. Missing required evidence must fail the quality result even when the package is smaller.

A source-review limitation remains in workflow comparison: matching objective, criteria, provider/model and source snapshot does not establish equivalent approved test commands, permissions, output limits or reasoning settings. Do not promote a live savings claim from those fields alone. This review did not fabricate live usage records to exercise that path.

## Correction review requirements

Before accepting measured improvements, independently check:

- Ranking and fallback recall beyond the old 100-candidate boundary, deterministic ordering and exact path/symbol matches.
- Batched Git checks retain project scope, current ignore behavior, unsafe-link refusal, stale-source exclusion and credential filtering.
- Duplicate-memory protection is atomic, preserves distinct evidence, and cannot resurrect deleted/superseded records or cross project scope.
- Required root/user instructions and acceptance criteria remain complete or explicitly fail their budget.
- Before/after measurements distinguish process-count/content-byte reductions from actual latency variance; real token/cost/provider claims remain blocked without comparable authorized live evidence.

No embeddings service, parser replacement, model-generated summaries, weaker review policy, or provider-session reset is justified by these findings.
