# Phase 5 optimization report

Date: 2026-11-25. Branch: `v5/phase5-context`. **Measured local improvements implemented;
Phase 5 and production release readiness remain incomplete.** No live provider request,
client-project modification, commit, push, merge, publication or deployment occurred.
All 38 immutable V4 files are unchanged. Final repository hygiene (4/4) and unsigned
local packaging validation passed; no artifact was published. Phase 3/4 work was preserved in the verified
[entry checkpoint](ENTRY-STATE.json) before modification.

## Observed outcome

- Full regression: **376 tests, 367 passed, 9 host-specific skips, no failures/errors**,
  196.824 seconds. Source hashes remained unchanged during execution.
- Synthetic required-context recovery: **16/24 → 24/24 complete cases**, or **22/30 →
  30/30 required elements**. Critical constraints remained present in every case.
- Broad-query Git policy checks are batched while source freshness checks remain. Exact
  paths, ranked symbols and separated excerpts recover formerly missing evidence.
- Ten identical active memory submissions now retain one record. Same-content touches
  avoid parsing/search rewrites. Verified correction receipts preserve original observations.
- Existing single_task routing avoids one planning call on each measured task while
  retaining actual test/review gates. Scripted approvals remained four in both modes.
- Current-source controlled soak: **120.790 seconds, 96 workflows**, 76 completed and
  20 intentionally blocked; no unexpected failures. Providers were deterministic fixtures.
- Actual Chrome: **8/8 dashboard groups** and **3/3 installed lifecycle groups passed**
  on final source; [BROWSER-REPORT.md](BROWSER-REPORT.md) records scope and evidence.

These are local mechanisms and synthetic measurements. They do not establish live
model quality, native cross-provider continuity, real token savings or less human work.
Some queries are slower and some packages larger because previously omitted evidence is
now included. [MEASUREMENTS.md](MEASUREMENTS.md) preserves those trade-offs and raw data.

## Requested deliverables

| Deliverable | Evidence and status |
|---|---|
| 1. Baseline | [BASELINE.json](BASELINE.json), [INDEPENDENT-BASELINE.md](INDEPENDENT-BASELINE.md) |
| 2. Phase 4 pending status | Phase 4 status below; local passes do not close live/platform gates |
| 3. Memory lifecycle | [IMPLEMENTATION.md](IMPLEMENTATION.md); exact dedup, safe supersession and verified resolution receipts |
| 4–5. Retrieval/code intelligence | Existing AST symbols/dependencies plus ranked FTS/path metadata and original-line excerpts; implementation report |
| 6–7. Quality dataset/results | [evaluate_context.py](../../../tools/evaluate_context.py), BASELINE/OPTIMIZED/COMPARISON JSON; generated ground truth |
| 8. Compression | Exact snippet/critical duplication only; required-source recall tested; no model summaries or real-token claim |
| 9–10. Incremental transfer/session policy | [PROVIDER-AND-SESSION-BOUNDARIES.md](PROVIDER-AND-SESSION-BOUNDARIES.md); exact session behavior retained, no unsafe delta/rotation assumption |
| 11–12. Routing/delegation/review | [POLICY-MEASUREMENTS.json](POLICY-MEASUREMENTS.json); existing policy measured, actual acceptance and mock review/correction preserved |
| 13–14. Tokens/total usage | Synthetic prepared-byte and call measurements; improved all-role accounting. Real A/B/C benchmark BLOCKED |
| 15. Human interaction | Four fixture-issued approvals per policy/task; actual human effort NOT MEASURED, reduction NOT DEMONSTRATED |
| 16. Resources | [MEASUREMENTS.md](MEASUREMENTS.md), [SOAK-EVIDENCE.json](SOAK-EVIDENCE.json) |
| 17–18. Inspector/analytics | Role selection, source reasons/lines, exclusions, reported/missing role totals and prepared bytes; browser evidence |
| 19. Security/privacy | [INDEPENDENT-REVIEW.md](INDEPENDENT-REVIEW.md), [ACCOUNTING-INDEPENDENT-REVIEW.md](ACCOUNTING-INDEPENDENT-REVIEW.md), preserved full regression |
| 20. Platforms | Ubuntu x86_64 actual execution; nine required-host skips; other native platforms pending |
| 21–22. New/final tests | 25 added tests; [FINAL-REGRESSION.json](FINAL-REGRESSION.json) and log |
| 23. Changed files | [CHANGED-FILES.json](CHANGED-FILES.json), measured against preserved Phase 5 entry |
| 24–25. Blockers/trade-offs | This report, provider boundary report and measurements |
| 26. Release assessment | NOT READY; mandatory provider/pilot/native evidence remains outstanding |
| 27. Phase 6 priorities | Priorities below |

## Acceptance scenario interpretation

| Scenario | Actual evidence / remaining limit |
|---|---|
| A. Fresh context | Fresh Store/controller retrieves decisions; native independent agent sessions remain unverified |
| B. Provider switch | Existing deterministic handoff/session/permission regressions pass; live transfer blocked |
| C. Small source change | One-file edits remain incremental; same-content touch avoids parse/FTS rewrite |
| D. Critical constraints | Tight-budget tests retain complete rules or fail explicitly; mandatory criteria preserved |
| E. Related tasks | Scoped read/prepared-context telemetry implemented; real repeated-discovery savings unmeasured |
| F. Multi-agent efficiency | Policy fixture call counts measured; no live conventional-versus-optimized benchmark |
| G. Simple routing | Explicit single_task avoids planner, keeps review/tests; no unverified automatic routing |
| H. Complex verification | Existing bounded planning/review/correction and adversarial evidence tests pass |
| I. Stale knowledge | Source/branch/deletion/exclusion tests plus FTS availability-transition fixes pass |
| J. Solution reuse | Verified resolution references require current source/evidence; no blind historical fix application |
| K. Resource stability | 120-second local soak and bounded context/backup retention; not unlimited stability |
| L. Human interaction | Synthetic approval count unchanged; real reduction not demonstrated |
| M. Project isolation | Generated foreign marker rejected; existing scoped APIs/MCP/security tests preserved |
| N. Real token efficiency | BLOCKED on provider usage authorization/configuration and equivalent measured runs |

## Outstanding Phase 4 and Phase 5 boundaries

Phase 4's actual local results were inspected, not assumed: 342 passed/9 skipped,
8 source-dashboard and 3 installed browser groups, seven engine workloads, and a
15-minute fixture soak. Phase 5 does not relabel that old soak as current-source evidence.
Native provider initiation, six live directions, intended-provider recovery, real-project
pilot and real user/token comparisons still have no authorization/evidence.

The pending usage question requires allowed providers, maximum calls and spend or
subscription allowance. MiniMax additionally needs a secure credential reference and
model. No key should be pasted. Claude availability must be checked before selected
live combinations. No further client directory may be registered without authorization.

No Windows, WSL2, Intel macOS, Apple Silicon macOS, real OS-vault lifecycle or machine
reboot was executed in Phase 5. Simulated platform tests are not native verification.

No optional embedding service, Tree-sitter migration, hierarchical model summary,
automatic session rotation, semantic contradiction engine, broad reusable-skill promotion,
new three-tier routing UI, or automatic approval weakening was introduced. The measured
lexical retrieval defects did not justify those costs/risks. Existing explicit policies,
approvals, persistent sessions and verification gates remain. These omissions are not
claimed as implemented requirements; broader automation needs its own measured baseline
and safe adapter support. The local request envelope is estimated, not an exact provider
window or financial guarantee.

## Release assessment and Phase 6 priorities

1. Obtain a small explicit provider budget; run equivalent live single-agent/context/
   multi-agent tasks with the same tools, permissions, model settings and test contract.
   Retain every role's input/output/cache/reasoning usage and missing-data markers.
2. Verify the intended native provider combination and platform before authorizing a
   small real-project copy. Close actual native session/recovery/credential gates.
3. Expand the quality corpus with authorized real tasks and repeated measurements. Tune
   role preferences only from misses; keep critical constraints and acceptance intact.
4. Measure long-history memory/database latency and actual idle/IDE overhead. Preserve
   historical evidence; do not turn the short soak into an unlimited-retention claim.
5. Validate packaging/upgrade/rollback and team distribution on each intended platform,
   then request explicit release authorization. No release is authorized by this report.

No broad `V5_PHASE_5_COMPLETE`, `V5_TOKEN_OPTIMIZATION_VERIFIED`,
`V5_MINIMAL_HUMAN_INTERACTION_VERIFIED`, `V5_RELEASE_CANDIDATE_READY` or
`V5_FULLY_VERIFIED` label is issued. Narrow automated evidence is recorded with its
source hashes and limitations instead of implying all mandatory acceptance scope passed.
