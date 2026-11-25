# Durable V5 implementation checklist

Each phase must retain a runnable system and tests. No live verification is
inferred from deterministic mocks. Updated evidence belongs in RESULTS.md.

- [x] Phase 0: inspect Git and architecture; archive clean V4.3; dedicated V5 branch.
- [x] Phase 0: rerun current baseline and record actual result.
- [x] Phase 1: scoped SQLite memory, machine discovery, registration and recovery.
- [x] Phase 2: incremental index, retrieval, bounded context, measured benchmark.
- [x] Phase 3: Codex, optional Claude, independent MiniMax capability adapters (protocol tests; live pending).
- [x] Phase 4: provider-neutral delegation, review, correction, completion gates (mock providers and real temporary-file/test evidence).
- [x] Phase 5: checkpoints, authorized failover, leases, pause/resume/cancel.
- [x] Phase 6: functional authenticated local API/dashboard, CLI and agent interface.
- [ ] Phase 6: actual browser interaction and external MCP-client verification.
- [x] Phase 7: separate Codex-session review, privacy tests, synthetic benchmark and corrections.
- [ ] Phase 7: representative live quality, billing and human-intervention benchmarks.
- [x] Phase 8: portable packaging, isolated install, migration documentation.
- [ ] Phase 8: complete Linux distro matrix, Intel Mac and native Windows verification.
- [ ] Phase 9: explicitly authorized Codex/MiniMax live scenarios.
- [ ] Phase 9: Claude live scenarios after usage limits permit.

No automatic API costs, credential changes, commits, pushes or publication.

Checked implementation phases do not imply all optional/advanced capabilities or
live acceptance scenarios are complete. Exact scope and limitations: RESULTS.md.
