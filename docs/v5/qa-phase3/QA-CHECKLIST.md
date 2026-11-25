# Phase 3 durable execution checklist

Date: 2026-11-25. Delivery branch `v5/phase3-qa`, based on `c933c04`.

- [x] Independently inspect branch, clean entry worktree, V5 source and prior claims.
- [x] Run baseline before source changes; preserve failures/skips and environment issue.
- [x] Create requirements-area matrix with evidence limits.
- [x] Separate security review context; reproduce ten confirmed defect groups.
- [x] Fix confirmed defects and add 53 meaningful regressions.
- [x] Verify three-project isolation, freshness, concurrent writes and required context.
- [x] Verify actual cancellation/pause subprocess cleanup and no delayed side effect.
- [x] Run permitted real loopback startup/crash/restart tests with mocked providers.
- [x] Exercise all six deterministic delegation directions and same-provider ownership.
- [x] Measure synthetic retrieval, local service resources and indexing scale.
- [x] Run actual stdio MCP discovery/retrieval without provider calls.
- [x] Full regression: 334 run, 325 passed, nine host-specific skips.
- [x] Independent correction review and immutable V4 byte comparison.
- [x] Preserve source patch, changed-file hashes, machine reports and pilot plan.
- [ ] Actual browser journeys: Playwright installation declined; installed-Chrome
  fallback failed inside sandbox and escalation did not complete.
- [ ] Live providers/six directions/real token efficiency: explicit budget and credentials required.
- [ ] Native other platforms and real credential vault CRUD.
- [x] Storage interruption, disk-full, schema failure, corruption and bounded workflow stress.
- [ ] Exhaustive crash-transition matrix and multi-day soak.
- [ ] Real user intervention and quality measurement.
- [ ] Controlled real-project pilot: gates unresolved; no client work authorized.

The unchecked local coverage is not mislabeled as an external blocker. No blanket
Phase 3 completion or readiness claim. No release/commit/push/deployment performed.
