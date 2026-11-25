# Requirements coverage matrix

Scope: Phase 1 `CHECKLIST.md`, Phase 2 `PHASE2-CHECKLIST.md`, and supplied Phase 3
request sections. Status applies only to the observed evidence column; limitations
remain requirements, not waived work. VERIFIED_AUTOMATED may include real local
filesystem/process effects with mocked provider responses; it never means upstream
provider verification. No row is VERIFIED_LIVE for provider execution.

| Requirement | Reference | Classification | Source / tests | Observed evidence | Remaining expected behavior / next check |
|---|---|---|---|---|---|
| Installation | §3,31,32 / P1 phase8 | VERIFIED_AUTOMATED | ccx_install.py; test_distribution, test_portable_install | Disposable prefixes, signed/tampered archives, unrelated launcher preservation pass | Native non-Linux lifecycle blocked |
| Startup/shutdown | §16,18 / P2 stage2 | VERIFIED_AUTOMATED | service.py; test_v5_service | Real loopback lifetime lock, start/stop/restart and duplicate startup pass | Other OS process supervision blocked |
| First-run setup | §27,28 / P2 stage2 | PARTIALLY_IMPLEMENTED | onboarding.py, web/app.js; test_v5_phase2 | Persisted setup/defaults backend tests pass | Actual wizard browser rerun blocked |
| Browser authentication | §22,27 / P2 stage2 | VERIFIED_AUTOMATED | auth.py, server.py; test_v5_server, test_v5_phase2 | Expiry, bootstrap replay, proof/origin and authenticated HTTP checks pass | Actual browser cookie/storage behavior blocked |
| Credential management | §24 / P2 stage2 | MOCK_TESTED | credentials.py; test_v5_credentials | Disposable mocked vault and secret refusal tests pass | Native vault CRUD not executed; Linux secret-tool absent |
| Machine intelligence | §7 / P1 phase1 | VERIFIED_AUTOMATED | store.py; test_v5_memory | Bounded local tool availability and cached machine snapshot pass | Runtime removal/reinstall combinations not exhaustive |
| Project registration | §7 / P1 phase1 | VERIFIED_AUTOMATED | store.py; test_v5_memory, test_v5_phase3_context | Explicit Git roots, spaced/Unicode fixtures, isolation pass | Project relocation lifecycle incomplete coverage |
| Incremental indexing | §7,29 / P1 phase2 | VERIFIED_AUTOMATED | store.py; test_v5_memory, test_v5_phase3_context | Rename/delete/branch freshness, exclusions, zero repeated content reads pass | Still traverses metadata; 50k-file/stress bounds not exercised |
| Persistent memory | §8,9 / P1 phase1 | VERIFIED_AUTOMATED | store.py; test_v5_phase3_context | Concurrent writes, reopen, backup, deletion and three-project scope pass | Killed writes/disk-full/schema rollback pass; machine reboot and exhaustive corruption matrix not executed |
| Context optimization | §10,11 / P1 phase2 | PARTIALLY_IMPLEMENTED | store.py; test_v5_phase3_context | Required rules preserved; budget failure and stale exclusion pass | Hierarchical summaries/model-specific limits/automatic compaction not established |
| Provider adapters | §13 / P1 phase3; P2 stage3 | MOCK_TESTED | providers.py; test_v5_providers | CLI arguments, HTTP/events, cancellation and missing configuration contracts pass | Live authentication/execution require budget/credentials |
| Multi-agent orchestration | §14,15 / P1 phase4 | MOCK_TESTED | workflows.py; test_v5_workflows | Six routing combinations and distinct same-provider sessions pass | Live delegation/reviewer quality blocked |
| Workflow management | §16 / P2 stage4 | VERIFIED_AUTOMATED | workflows.py; test_v5_workflows, test_v5_phase3_cancel | Leases, budgets, dependencies, pause/cancel and actual subprocess effects pass | No parallel write support; full stress/soak not executed |
| Review/correction | §17,35 / P1 phase4 | MOCK_TESTED | workflows.py; test_v5_workflows | Real test commands plus deterministic approve/reject and bounded correction pass | Real model detecting controlled defect not verified |
| Approval policies | §21,22,23 / P1 phase4 | VERIFIED_AUTOMATED | workflows.py, mcp.py; test_v5_phase2_reliability | Scoped grants, denial, idempotent resolution, advisory-only MCP pass | Live human-intervention counts unavailable |
| Recovery | §18,19 / P2 stage4 | VERIFIED_AUTOMATED | service.py, workflows.py; test_v5_service | Controlled backend crash, unknown outcome and no duplicate replay pass | All fault windows/reboot/native other OS not tested |
| Provider failover | §20 / P2 stage4 | MOCK_TESTED | workflows.py; test_v5_phase2_reliability | Approved destination handoff preserves executor state/session | Real network/exhaustion handoff blocked |
| CLI | §30,32 / P1 phase6 | VERIFIED_AUTOMATED | cli.py, orchestrator.py; test_v5_cli, test_cli_portable | Temporary engine CLI paths and existing V4 commands pass | No real user-global install performed |
| MCP | §30 / P1 phase6 | VERIFIED_AUTOMATED | mcp.py; test_v5_mcp, verify_workspace_mcp.py | Actual stdio initialize/list/retrieve and scope refusals pass | Native agent-initiated workflow blocked |
| Dashboard | §27,28 / P2 stage6 | BLOCKED | server.py, web/*; tests/browser/* | Backend controls pass; no Phase3 browser execution | Playwright install declined; run actual interaction suites |
| Usage analytics | §12 / P2 stage5 | MOCK_TESTED | benchmark.py; test_v5_phase2_reliability | Estimate/reported separation and comparable-run guards pass | Real repeated A/B and cost/quality evidence blocked |
| Backup/restore | §8,26,32 / P1 phase1 | VERIFIED_AUTOMATED | store.py, ccx_install.py; memory/distribution tests | SQLite backup integrity and isolated recovery pass | Partial backup failure and disk-full rollback pass; interrupted restore matrix incomplete |
| Update/rollback | §32 / P1 phase8 | VERIFIED_AUTOMATED | ccx_distribution.py; test_self_update | Signed/tampered update, failure and rollback fixtures pass | No publication/global user update |
| Team distribution | §31,32 / P1 phase8 | VERIFIED_AUTOMATED | tools/build_release.py; test_distribution | Packaging/signature/lifecycle fixtures pass | Release promotion withheld |
| Cross-platform | §31 / P1 phase8; P2 stage9 | PARTIALLY_IMPLEMENTED | ccx_platform.py, ccx_windows.py; platform tests | Native Ubuntu24 execution passes; nine host-specific skips | Ubuntu20, macOS variants, Windows, WSL2 not verified here |

## Confirmed findings

Per-finding observed/expected behavior, severity, correction and evidence are in
SECURITY-FINDINGS.md (S1–S10 plus T1). All confirmed findings are corrected in this branch; the original
c933c04 implementation fails their preserved reproductions. No unjustified skips
hide those defects. No missing feature was added to inflate scope.

## Remaining local coverage gaps (not external blockers)

The broad request is larger than this completed local audit: every crash transition; exhaustive corrupted-record/schema upgrade combinations; multi-day
silence/CPU/large-history soak; all test-quality mutations; and every representative
A–J end-to-end workload were not executed. These are NOT TESTED, not passed or
unavailable-platform excuses. Some advanced context features are not established by
source/tests. Full Phase 3 QA completion is therefore withheld even though the
available regression suite and confirmed corrections pass.

Scenario coverage: A/E use mock implementation/review with actual patch/test effects;
C/I local restart/crash fixtures; D mock authorized failover; F/H isolation/security
fixtures; B actual frontend feature journey blocked on browser; G real interventions
unmeasured; J synthetic retrieval only, live matched A/B blocked.
