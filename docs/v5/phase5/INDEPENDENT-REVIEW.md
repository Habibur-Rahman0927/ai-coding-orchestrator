# Independent review of Phase 5 corrections

Date: 2026-11-25. The reviewer made no production changes. Four focused regression tests were added to `tests/test_v5_phase5_context.py`; all other work was source review, isolated fixtures, and retained evidence. The reviewed production digests and test logs are recorded in [INDEPENDENT-REVIEW.json](INDEPENDENT-REVIEW.json).

## Findings and corrections

The independent baseline reproduced missing required candidates beyond the first 100 rows, absent exact-filename retrieval, repeated per-file Git subprocesses, and duplicate active memory records. The implementation now ranks before candidate limits, adds path/symbol metadata, batches fresh Git exclusion checks, and deduplicates exact active memory identities under an immediate transaction. It retains per-source security and content-hash freshness validation.

Review found and drove three additional corrections:

1. A suffix filename such as `a.py` was incorrectly labelled an exact match inside `data.py` and could outrank the requested file. Path-boundary matching now prevents this.
2. If FTS first became available after indexing without it, the newly created search table was empty. Transactional backfill now restores existing indexed documents without rereading unchanged source files.
3. If a previously populated FTS table survived a period without FTS support, changes made during fallback were missing when FTS returned. A durable dirty marker now triggers transactional rebuild and is cleared only after success.

Focused tests reproduce both availability transitions, exact-path ranking, and duplicate-row avoidance on reopening. Storage error handling still propagates real failures rather than treating them as an absent optional module.

## Memory, role and source-reference boundaries

Exact memory reuse includes project, scope, kind, title, body, source/hash, confidence, verification time, expiry and supersession metadata. It does not merge hypotheses into verified records, refresh expiry, or reactivate superseded/deleted records. Concurrent identical submissions are serialized; historical observations remain available in storage rather than being overwritten.

Optional planner/reviewer priority changes selection under a tight budget while mandatory root/user rules remain first. The independent regression requires architecture context for the planner and test context for the reviewer under the same constrained package, while retaining the same critical requirement and root restriction. Exact duplicate critical strings are included once. No semantic summary substitutes for source evidence.

Separated query symbols receive separate source windows with original line references. Source hashes are freshly checked; ignored, unsafe and stale files remain excluded. These are lightweight lexical/metadata heuristics, not a claim of perfect semantic retrieval or unlimited context.

## Usage and dispatch review

The request envelope reserves output and a safety allowance against an explicitly configured local estimate. It does not claim to observe opaque native session history or infer every model's context window. Missing input/output usage is estimated separately from reported components; reported zero remains zero. Cached and reasoning tokens remain separate metadata. Role totals and repeated scoped-read counts are based on recorded actions; native file reads and human effort remain unknown.

Workflow comparison now requires a matching recorded permission/verification/output contract as well as its existing source/model/task checks. Mocked runs, incomplete usage and unverified inherited native settings still prevent real efficiency claims. No provider request, billable benchmark or fabricated live usage was used during this review.

## Verified error-resolution receipts

Successful completion supersedes an engine correction observation with a source-bound verification receipt. The receipt says that completion gates passed; it does not certify the original model diagnosis as a true root cause. Original observations remain stored. Unfinished corrections remain observed/unresolved, and later source changes invalidate receipt freshness.

The independent fault scenario interrupts final indexing **after** a resolution receipt is written but **before** completion. The workflow becomes `BLOCKED`, and the receipt is stale for retrieval while completion is unconfirmed. Explicit resume then completes without further provider calls: four before resume and four afterward. Exactly one active resolution remains, with its original observation retained as a second historical error row. See [LEARNING-INDEPENDENT-FAULT.json](LEARNING-INDEPENDENT-FAULT.json).

## Verification evidence

| Independently executed suite | Result |
|---|---:|
| Phase 5 context, including reviewer-added cases | 13 passed |
| Existing memory | 10 passed |
| Phase 3 context integrity | 9 passed |
| Phase 3 storage faults | 11 passed |
| Phase 5 usage fidelity | 6 passed |
| Phase 5 verified learning | 2 passed |
| Existing workflow behavior | 21 passed |
| Phase 2 reliability | 21 passed |
| **Total** | **93 passed; no failures or skips** |

The original 131-file reproduction now retrieves the required target through both FTS and fallback search, and twenty identical active-memory submissions produce one record. Repeated context requests dropped from 102 to three Git policy-check subprocesses while retaining the same 100 source reads and 4,790 content bytes. Two observed latency samples changed from 165.626/173.058 ms to 28.206/27.806 ms. These are a small synthetic comparison at the recorded candidate digests, not a general speedup guarantee or real token-saving result. [INDEPENDENT-AFTER-SAMPLE.json](INDEPENDENT-AFTER-SAMPLE.json) identifies that intermediate measurement separately from the final reviewed digests.

Approved within this assessed local scope. Real provider continuity, actual token/cost savings, native platform coverage and sustained production retrieval quality remain separate evidence requirements. The root agent's broader quality dataset and final regression report remain authoritative for their respective executions; this review does not relabel those as independently rerun.
