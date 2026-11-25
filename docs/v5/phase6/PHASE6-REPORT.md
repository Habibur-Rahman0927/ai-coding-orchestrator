# Phase 6 integration and local candidate assessment

2026-11-25 · `v5/phase6-release-prep` · base `c933c04063b16d6c47b430f512fadd26b9d1e0a1` plus preserved, uncommitted Phase 3–6 work.

**A verified unsigned local evaluation artifact is prepared. Production and team
distribution readiness remain blocked.** No live provider call, client-project
pilot, real signing, publication, commit, push or global installation replacement
was performed. The user's later authorization covered disposable test keys only;
their temporary directories were deleted after testing ([cleanup](KEY-CLEANUP.json)).

## Concrete result

- Full regression: **384 discovered/executed, 375 passed, 9 required-host skips,
  zero failures, errors or discovery errors**, 148.615 seconds.
  [Machine-readable results](FINAL-REGRESSION.json), [log](FINAL-REGRESSION.log).
- Eight new regressions pass, including an actual installed backend that blocks
  upgrade/uninstall while running and permits them after shutdown.
  [Focused results](TARGETED.log), [installed lock evidence](INSTALLED-LOCK.log).
- Actual sandboxed Chrome 144: ten source dashboard groups and three lifecycle
  groups installed from the **verified extracted archive** passed. No dependency
  download or live provider use. [Dashboard](BROWSER.json), [artifact lifecycle](ARTIFACT-BROWSER.json).
- Deterministic archive: **88 members, 225,469 bytes**, exact manifest/checksum
  verification, byte-identical second build. [Artifact evidence](ARTIFACT.json).
- All **38 immutable V4 payload files unchanged** against the entry checkpoint.
  [Verification](IMMUTABLE-PAYLOADS.json). Prior work preserved in [entry inventory](ENTRY-STATE.json).

Local artifact: `dist/v5-local-evaluation/claude-codex-orchestrator-4.3.0.tar.gz`
and adjacent `SHA256SUMS`. SHA-256:
`334559ee507d9df2e8ade4abbd15a0c840fbd54fd94a3c424a625151986a3121`.
The engine version is still 4.3.0 and workspace version 5.0.0-dev. Generated
`RELEASE-INFO.json` says `local_evaluation_only` and `production_ready: false`.
This is not a new production 4.3.0 release or a full V5.0.0 release. Checksums
provide integrity, not publisher authenticity. No candidate signature exists.

## Release notes and corrected defects

1. **Active runtime/code mutation (high):** workflows and services did not hold
   the installer engine lock. Shared leases now cover workspace CLI/MCP, service
   and workflow execution; updates, rollback and uninstall require exclusivity.
   Custom database paths cannot bypass the engine identity. Old runtimes must be
   stopped before their initial upgrade. Startup imports are not an atomic version
   pin; conservative startup failure is possible during a mutation.
2. **Package evidence exposure:** the original builder included 202 audit/log
   members in a 302-member archive. Source installation and archives now share an
   explicit user-document allowlist. Runtime databases, sidecars, logs and known
   credential filenames are rejected case-insensitively. Independent review found
   and reproduced missed sidecars in the first fix; those cases are now covered.
   This is not a guarantee against arbitrary secrets disguised as ordinary source.
3. **Backup integration:** Settings can create a private online SQLite backup,
   display its SHA-256 and recovery instructions. Destination overrides are
   rejected. Actual browser testing reopened a separate copy, checked integrity
   and recovered project/workflow/user/verified memory. No restore button or
   automatic source/credential rollback is claimed.
4. **CLI help:** `workspace --help` now reaches the workspace parser. Legacy
   top-level `status`/`doctor` remain V4 commands; use `workspace status/doctor`.
5. User guides now distinguish development scope, bootstrap authentication,
   database recovery, update locking and source-only historical evidence.

Before-fix regressions and independent reproductions are retained beside this
report. One independent browser attempt missed a short-lived RUNNING state even
though the workflow completed. The final harness uses a private provider barrier
to observe RUNNING before and after reload, then releases it; it does not weaken
completion assertions. Failed attempt evidence is retained, not counted as a pass.

## Requirements and readiness matrix

Statuses use the requested vocabulary. A narrow automated result does not imply
live acceptance. No row below is VERIFIED_LIVE.

| Area | Current status / evidence | Remaining limitation and release impact | Required action |
|---|---|---|---|
| Machine knowledge | VERIFIED_AUTOMATED — schema, machine/store tests | Native multi-machine transfer unverified | Execute on intended hosts |
| Project registration/isolation | VERIFIED_AUTOMATED — full suite, actual Chrome project preview/index | Generated approved repositories only; no client pilot | Authorize specific project copy |
| Indexing/retrieval | VERIFIED_AUTOMATED — store/context/source freshness tests | Real large-repository corpus pending | Provide approved workload |
| Persistent intelligence | VERIFIED_AUTOMATED — restart, backup, dedup and verified receipt tests | Semantic contradiction resolution and broad skill promotion absent | Define measured follow-on scope |
| Context continuity | MOCK_TESTED — exact sessions, fresh Store, restart and scoped context | Native provider switching and machine reboot unverified | Native client acceptance |
| Token efficiency | SYNTHETIC_BENCHMARKED — Phase 5 16/24→24/24 required-context recovery | Real comparable token savings BLOCKED; prepared bytes are not tokens | Authorize bounded provider usage |
| Human interaction | SYNTHETIC_BENCHMARKED — four scripted approvals per policy/task | No measured reduction in real human work | Run controlled user comparison |
| Provider adapters | MOCK_TESTED — Codex, Claude, MiniMax contracts and permission tests | Live auth/model/version support unverified | Budget and secure provider configuration |
| Six delegation directions | MOCK_TESTED — all-six-directions regression | Every live direction BLOCKED | See provider matrix below |
| Native agent/MCP integration | MOCK_TESTED — bound MCP/tool/protocol tests | Actual native clients not accepted | Configure and verify intended clients |
| Autonomous execution | MOCK_TESTED — real local patch/command effects, fixture agents | No real-model quality or client pilot claim | Authorized bounded live task |
| Review/correction | MOCK_TESTED — independent fixture rejection, correction and acceptance | Real reviewer effectiveness unmeasured | Equivalent live evaluation |
| Completion enforcement | VERIFIED_AUTOMATED — tests/evidence and no false completion after cancellation | Same-user commands are not OS-sandboxed | Review approved command scope |
| Approval management | VERIFIED_AUTOMATED — scopes, revocation, fail-closed checks | Actual human effort unmeasured | None for local fixture scope |
| Recovery/failover | MOCK_TESTED — unknown action reconciliation, pause/restart/cancel | Live provider interruption/failover unverified; no blind replay | Verify native provider recovery |
| Global CLI/install | VERIFIED_AUTOMATED — isolated source/archive install and help/start | Ubuntu x86_64 only; actual user's legacy launcher not replaced | Choose intended installation scope |
| Daily-use experience | PARTIALLY_IMPLEMENTED — onboarding/chat/workflows/settings | No real daily-use pilot, native clients or all browser edge cases | Controlled pilot authorization |
| Dashboard/browser | VERIFIED_AUTOMATED — 10 real Chrome groups | Polling/streaming observed; backend disconnect, explicit duplicate-click/retry and full accessibility acceptance incomplete | Complete remaining browser scenarios |
| Browser authentication | VERIFIED_AUTOMATED — bootstrap, expiry/logout, second-tab refusal | Second authenticated tab coexistence not claimed | Broader multi-tab acceptance |
| Credential management | MOCK_TESTED — references, redaction, session-only browser fixture | Real Windows/macOS credential-vault lifecycle unverified | Native host/provider setup |
| Security | VERIFIED_AUTOMATED — regression and independent source review | No remaining confirmed high/critical in reviewed local scope; native/platform/live boundaries pending | Close broader release checks |
| Performance | SYNTHETIC_BENCHMARKED — current idle sample; Phase 5 indexing/context/soak | No long-duration current-source stress, IDE overhead or large history measurement | Approved representative workload |
| Cross-platform support | PARTIALLY_IMPLEMENTED — adapters and Linux execution | Nine required-host skips; Windows/WSL2/macOS/Ubuntu20.04 current-source acceptance missing | Run native matrix |
| Backup/recovery | VERIFIED_AUTOMATED — SQLite hash/private copy/reopen/browser | Database only; recovery manual; source/credentials excluded | Retain originals and inspect uncertain actions |
| Migration/backward compatibility | VERIFIED_AUTOMATED — preserved V4 immutable files, lifecycle/import regressions | Not a real user's production database migration | Backup and test intended data copy |
| Update/rollback | VERIFIED_AUTOMATED — signed local artifacts, failure restoration, engine leases | Test trust only; remote production channel not exercised | Establish independent signer trust |
| Uninstall | VERIFIED_AUTOMATED — archive-installed launcher removal and data retention | Native platforms pending; other active older runtimes uncooperative | Stop all runtimes first |
| Team distribution | BLOCKED — deterministic clean local archive exists | No trusted candidate signature, native matrix or licensing decision | Approve scope, license, signer and release procedure |

## Provider and platform boundaries

| Direction | Offline contract | Live status / missing prerequisite |
|---|---|---|
| Codex → MiniMax | MOCK_TESTED | BLOCKED: authorized calls/spend, secure MiniMax reference and model |
| MiniMax → Codex | MOCK_TESTED | BLOCKED: same prerequisites and native continuity |
| Codex → Claude | MOCK_TESTED | BLOCKED: Claude setup/availability and budget |
| Claude → Codex | MOCK_TESTED | BLOCKED: Claude setup/availability and budget |
| Claude → MiniMax | MOCK_TESTED | BLOCKED: both provider prerequisites and budget |
| MiniMax → Claude | MOCK_TESTED | BLOCKED: both provider prerequisites and budget |

Provider discovery is not authentication. Earlier local discovery found Claude
unavailable; no new live probe or account configuration was performed. MiniMax
does not require Claude. MCP server availability does not verify a native client's
initiation, context transfer or tool permission behavior.

Current execution host: Ubuntu 24.04 x86_64, Python 3.12.3, Chrome 144. Native
Windows, WSL2, Intel/Apple Silicon macOS, Ubuntu 20.04 and actual reboot acceptance
were not performed. Simulated platform tests and historical results do not close
these gates. Use FINAL-REGRESSION.json for each of the nine exact skip reasons.

## Resources and earlier-phase evidence

The exact archive installed in 0.214 s; its empty backend started in 0.301 s.
A five-second Linux /proc sample observed 38,891,520 bytes RSS at both ends and
zero additional CPU ticks at OS accounting resolution. Database size was 196,608
bytes, no SQLite sidecars at measurement, and health-based stop took 0.016 s.
This is one short empty-backend sample, not a zero-CPU guarantee or sustained-load
measurement. [Raw measurement](RESOURCE.json).

Phase 3 security/cancellation/storage corrections remain in the working tree and
full regression. Phase 4 recorded 342 passes/9 skips, seven isolated workloads and
a 15-minute fixture soak. Phase 5 recorded 367 passes/9 skips, retrieval corpus
improvements and a 120.790-second, 96-workflow fixture soak (76 completed,
20 expected blocks). Those older source measurements are explicitly historical:
[Phase 4](../phase4/PILOT-REPORT.md), [Phase 5](../phase5/PHASE5-REPORT.md),
[indexing/context measurements](../phase5/MEASUREMENTS.md).
Phase 6 does not claim a new sustained stress test, real token A/B/C comparison,
real human-effort reduction, or authorized real-client pilot.

## Independent review and delivery map

Separate reviewer sessions examined integration and security and added backup/tab
browser acceptance. See [security review](SECURITY-REVIEW.md) and
[integration review](INTEGRATION-REVIEW.md). Sandbox-blocked reviewer socket checks
are distinguished from primary permitted loopback runs. Signed tests passed
15/15 independently and in the full suite. Source snapshots and changed-file
inventory accompany this report.

| Requested deliverables | Location / outcome |
|---|---|
| 1–5 consolidation, pending closure, matrix, architecture, CLI/dashboard | This report, source inventory, existing ARCHITECTURE.md and integration review |
| 6–7 global install and launchers | Actual artifact lifecycle; native exclusions above |
| 8–10 providers/delegation/native integration | Matrices above; live gates BLOCKED |
| 11–14 persistence/tokens/autonomy/human measurements | Full regression, browser evidence, Phase 5 measurements; live comparisons BLOCKED |
| 15–18 browser/security/resources/platforms | BROWSER.json, SECURITY-REVIEW.md, RESOURCE.json, matrix |
| 19 real pilot | BLOCKED on project/provider authorization |
| 20–23 migration/backup/update/rollback/uninstall | Full regression, targeted tests and exact artifact lifecycle |
| 24–27 regression/inventory/artifacts/checksum/signature | FINAL-REGRESSION.json, CHANGED-FILES.json, ARTIFACT.json; no real signature |
| 28–34 docs/notes/limits/blockers/recommendation/commands/publishing | This report, OPERATIONS.md, RELEASE-CANDIDATE.md, TEAM-INSTALL/UPDATE and RELEASING guides |

## Recommendation and next gates

Use this artifact only for local evaluation on the verified Linux host scope,
with explicit approvals and backups. Do not distribute it as a trusted production
release. Full readiness labels, including V5_FULLY_VERIFIED,
V5_TOKEN_EFFICIENCY_VERIFIED and V5_PRODUCTION_RELEASED, are not issued.

Remaining blockers require a bounded provider budget and secure configuration,
authorized project copy, real native platform/client acceptance, representative
performance and user comparison, remaining browser scenarios, a deliberate version
and licensing decision, independent release trust, and explicit publication
approval. No guessed budget, credentials or client directory was used.

Exact checkout daily commands and manual recovery:
[OPERATIONS.md](../OPERATIONS.md). Isolated installation commands:
[TEAM-INSTALL.md](../../TEAM-INSTALL.md). Future signed publishing procedure,
requiring approval after all release gates: [RELEASING.md](../../RELEASING.md).
Do not execute the publishing procedure against this development artifact.
