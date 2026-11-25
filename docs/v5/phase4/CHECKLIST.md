# Phase 4 implementation checklist

Date: 2026-11-25. Local preparation progressed; mandatory live/pilot gates remain open.

- [x] Preserve all Phase 3 work and verify a recoverable local archive.
- [x] Create dedicated `v5/phase4-pilot` branch without committing.
- [x] Verify all 38 immutable V4 payload files byte-for-byte unchanged.
- [x] Reproduce and fix release artifact path defect; independently review.
- [x] Run actual Chrome dashboard QA: eight groups, offline providers.
- [x] Run all seven generated development workloads through WorkflowEngine.
- [x] Verify scoped patches, actual commands, mock review/correction, durable memory.
- [x] Complete actual 15-minute deterministic soak with resource measurements.
- [x] Bound future soak backup storage and reject optimized assertion-disabled runs.
- [x] Correct cancelled planner/reviewer resume; regression and independent review.
- [x] Record local provider availability without live calls or credential changes.
- [x] Complete final offline regression: 351 tests, 342 passed, 9 host-specific skips, zero failures/errors.
- [x] Report product value, measured limits and Phase 5 priorities.
- [ ] Receive explicit provider usage budget and secure MiniMax configuration.
- [ ] Verify actual supported native-agent interfaces and intended live combinations.
- [ ] Run matched real-provider token/quality/human-interaction comparisons.
- [ ] Verify live interruption/recovery and independent native-session continuity.
- [ ] Complete unavailable native platform checks and machine-restart validation.
- [x] Verify installed-launcher onboarding, actual backend restart and safe uninstall in Chrome.
- [ ] Complete broader browser/accessibility and live installed-workflow coverage.
- [ ] Run longer/live soaks when selected scope and provider budgets permit.
- [ ] Authorize a specific real-project copy/task after all applicable entry gates pass.
- [ ] Complete controlled real-project pilot and Phase 4 readiness assessment.

Completed boxes are deliberately scoped to their stated local/mock evidence. They do
not grant broad completion labels. No commit, push, deployment, paid-provider use or
client-project modification occurred.
