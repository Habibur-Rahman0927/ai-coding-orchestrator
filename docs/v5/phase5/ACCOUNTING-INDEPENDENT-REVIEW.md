# Independent usage and comparison review

Date: 2026-11-25. Review scope: the Phase 5 changes to `providers.py` usage normalization, `workflows.py` request accounting/envelope/contract hash, and `benchmark.py` role analytics and workflow comparison. The reviewer compared actual source against the retained Phase 4 baseline, reproduced defects offline, and added focused comparison tests. The reviewer did not edit production code or invoke a live provider.

Result: **approved within the documented measurement limits**, after two confirmed comparability defects were corrected. [Machine-readable review, source hashes and test inventory](ACCOUNTING-INDEPENDENT-REVIEW.json) identifies the uncommitted working-tree implementation; this is not a clean-commit or live-efficiency certification.

## Confirmed defects and corrections

| Severity | Reproduction | Correction and independent verification |
|---|---|---|
| MEDIUM | Baseline executor used model A and reviewer used model B; optimized run swapped those models. Comparing only the set of provider/model pairs incorrectly returned `comparable=true` and `optimization_verified=true` for synthetic reduced usage. | Comparison now binds role/provider/model assignments. The new regression rejects the swap and withholds token reduction. [Before-fix evidence](ACCOUNTING-COMPARISON-BEFORE.json) |
| MEDIUM | Two actual offline workflows with nominal output limit 1500 dispatched different limits after total-budget clipping: full-index 1351 versus retrieved 1500. Their contract hashes were identical. | Contract hashing now includes the actual dispatched output limit. The regression executes both fixture workflows, verifies successful completion, observes different output caps, and requires distinct hashes. [Before-fix evidence](ACCOUNTING-CONTRACT-BEFORE.json) |

The before-fix JSON files contain **synthetic defect demonstrations**, not real provider observations. In particular, their historical `optimization_verified=true` result demonstrates a rejected bug; it is not a current efficiency claim.

## Accounting assessment

- Reported input/output zeroes remain reported zeroes. A missing input or output component uses a local estimate only for that missing component; reports distinguish reported, mixed and estimated accounting.
- Nested cache and reasoning fields are retained as metadata. Cache reads are never subtracted from input/output totals or described as eliminated tokens.
- The Claude normalizer handles uncached input, cache-read input and cache-creation input as disjoint fields. It only constructs a total when all required fields are present; partial cache evidence leaves total input unknown. These checks use synthetic provider-shaped events, not a live cache experiment.
- Missing cache/reasoning fields stay unknown rather than becoming measured zeroes. Native cache reuse, cache pricing and inherited provider behavior have not been verified by these tests. No cache feature was enabled.
- The request envelope checks estimated prompt/history input plus reserved output and safety space before dispatch. UTF-8 bytes divided by four is a local estimate, not an exact tokenizer count or guaranteed provider context-window bound. Native history occupancy and unobserved adapter/system overhead remain explicitly unknown.
- Role aggregates retain all recorded planner, executor and reviewer actions, including correction/retry activity, with missing-usage counts. Journaled requests can include uncertain or pre-transport failures. The final fields are therefore `context_bytes_prepared` and `observable_history_bytes_prepared`, **not proven wire-byte counts**.
- Comparison refuses incomplete usage, mocked runs, missing contracts, mismatched source/objective/criteria/provider assignments and unknown native reasoning/speed settings. Cost savings remain unset; no price schedule or paid benchmark was supplied by this review.

The comparer remains deliberately conservative: varying recorded contracts within a run can prevent comparability even when a human might explain the variation. This is preferable to silently declaring equivalent output or permission settings.

## Independent verification

| Suite | Executed | Passed | Evidence |
|---|---:|---:|---|
| New comparison regressions | 4 | 4 | [Log](accounting-comparison-independent.log) |
| Phase 5 usage fidelity | 6 | 6 | [Log](accounting-usage-independent.log) |
| Provider adapter regressions | 18 | 18 | [Log](accounting-providers-independent.log) |
| Phase 2 reliability regressions | 21 | 21 | [Log](accounting-reliability-independent.log) |

Each command used `python3 -B -m unittest discover -s tests -p <suite> -v` and exited 0. The four new comparison tests cover role/model swaps, matching contracts without cache subtraction, missing/different contracts, and real offline dispatch-cap clipping. Logs were checked for recognizable credentials and personal-home paths before being saved.

This report does not assess Phase 5 memory learning changes or replace their separate independent review. It does not establish live token efficiency, upstream billing limits, cost savings, full provider compatibility or unlimited context retention.
