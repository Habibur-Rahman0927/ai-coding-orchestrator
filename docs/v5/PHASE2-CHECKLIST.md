# Phase 2 durable implementation checklist

Baseline: clean `v5/universal-workspace` at `6fde991` (prior V5 implementation
committed by the user). Archived HEAD outside the repository before changes.
Fresh native macOS baseline: 227 run, 219 passed, 8 skipped, 153.444 seconds.
Existing project releases remain immutable. No commits/publication authorized.

- [x] Stage 1: inspect actual source, preserve baseline, rerun current tests.
- [x] Stage 2: persisted wizard, owned startup/shutdown, browser authentication,
  credential facilities, project preview and application defaults.
- [x] Stage 3: separate local diagnostics, authorized live-test preview/action,
  exact session resume checks and honest connection status.
- [ ] Stage 3: real authorized Codex/MiniMax workflows (spending and MiniMax
  credentials required; user explicitly deferred live requests in this session).
- [x] Stage 4: dependencies, failure classification, bounded continuation,
  authorized role handoff, crash/replay and approval tests.
- [x] Stage 5: automatic index checkpoints, persisted context, all-role reported
  usage comparison; real token-savings measurements remain separately gated.
- [x] Stage 6: practical task/approval controls, explicit standalone conversations,
  live activity, sessions, context inspection and redacted diagnostics.
- [x] Stage 7: actual isolated Chrome/Playwright tests with deterministic providers.
- [x] Stage 8: independent source/security review, fixes, measured resources,
  targeted tests and complete regression.
- [x] Stage 9: isolated installation, artifact hygiene, Ubuntu 20.04/24.04 checks,
  team instructions and truthful release readiness.
- [ ] Native Windows, Intel macOS and WSL2 checks on real environments.
- [ ] Claude live scenarios once available; all six actual provider combinations.

Implementation, automated mock testing and actual live-provider evidence are
reported separately in PHASE2-RESULTS.md. No machine-reboot claims from mere
application-restart tests; no token-savings claims from byte estimates.
