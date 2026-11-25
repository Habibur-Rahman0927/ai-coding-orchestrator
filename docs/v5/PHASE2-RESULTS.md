# V5 Phase 2 — measured implementation status

Date: 2026-11-25. Branch: `v5/universal-workspace`. Baseline commit: `6fde991`.
The worktree was clean at entry; HEAD was archived outside the repository before
editing. The fresh baseline ran 227 tests: 219 passed, 8 skipped. Existing V4
release payloads and provider authentication were preserved. No commits, pushes,
publication, deployment, startup-service registration or global installation were
performed. Test installs and browser profiles were disposable.

The user explicitly chose **no live tests** during this phase. Implementation and
mock verification continued; no billable provider requests were sent. A native
Codex executable and local authenticated login were detected, which is not a live
connection claim. Claude was absent from the inspected PATH. MiniMax live
configuration remains a user-controlled secure setup step.

## Regression results

| Environment / check | Observed result |
|---|---|
| Clean native macOS baseline | 227 run: 219 passed, 8 skipped |
| Native macOS ARM64 / Python 3.9.6 full regression | 279 run: 266 passed, 13 skipped; 176.279 seconds |
| Ubuntu 20.04 / Python 3.8 full regression | 279 run: 268 passed, 11 skipped; 58.757 seconds |
| Ubuntu 24.04 / Python 3.12 full regression | 279 run: 268 passed, 11 skipped; 61.655 seconds |
| Final focused V5 suite, macOS | 129 run: 123 passed, 6 skipped |
| Final focused V5 suite, each Ubuntu image | 129 run: 128 passed, 1 skipped |
| Actual Chrome browser interaction suite | 8 passed |
| Installed-engine browser onboarding/restart/uninstall | 1 passed; 4.550 seconds |
| Permitted local service and security tests | 8 passed; includes real controlled backend crash |
| Final auth/setup/chat/MCP freshness regression | 9 passed |

The full macOS suite ran under the filesystem/socket sandbox: skips comprise six
native Windows cases, one Linux-only case, and six loopback-dependent cases. The
separate permitted local service/browser runs cover those socket checks. Linux
containers ran offline with source mounted read-only, no credentials, and temporary
state; skips are six Windows cases, three non-Linux cases, one root-permission case
and the missing JavaScript parser. Chrome/JavaScript checks ran separately on macOS.
The first Ubuntu attempts lacked the test suite's `make` dependency; adding it to
the disposable images fixed that environment failure without application changes.
Final focused V5 runs include the last MCP evidence-freshness regression after the
full runs; exact counts and source digest are in PHASE2-EVIDENCE.json.

## Implemented and connected

| Deliverable | Implementation / evidence |
|---|---|
| Onboarding | Persistent six-step wizard; environment/credential facilities, truthful provider states, defaults, bounded project preview, registration/indexing; reopen from Settings |
| Startup | `start`, `stop`, `restart`, `dashboard` aliases; legacy status/doctor retained; one lifetime lock per database, authenticated health, existing-instance detection, safe alternative port, explicit background mode |
| Browser authentication | 60-second single-use bootstrap; short credential removed from history, 8-hour HttpOnly/SameSite session, origin/port-bound tab proof on every API request, expiry/logout/rotation, no public bind |
| Credentials | macOS Keychain / Windows Credential Manager / Linux Secret Service adapters; explicit environment or process-memory alternatives; no plaintext fallback; add/replace/remove forms |
| Provider diagnostics | Cheap cached summary separated from local CLI checks and explicitly authorized synthetic live-test plans; historical verification tied to configuration/credential revision |
| Workflows | Dependency checks, provider-call/context/continuation budgets, conservative failure classification, no-progress detection, exact sessions, scoped approval reuse, optional planner skipping, per-workflow model overrides |
| Failover | Explicit role handoff and automatic use of an already approved destination for classified failures; sharing/cost/native-access gates remain required; executor session preserved |
| Recovery | PID plus birth-identity ownership; dead/reused owner reconciliation, uncertain-action review, no automatic replay, durable test-action evidence; live but late owners are diagnosed rather than stolen |
| Context | Incremental refresh at workflow boundaries, task-relevant instructions/memory, error/correction records, verified completion memory and context inspection |
| Dashboard | Real task/approval forms, pending-request approve/deny, polling visible events, state-aware controls, sessions, context/results/usage, redacted doctor, restrained in-app notifications |
| Standalone chat | Explicit per-message consent, filtered context, streamed visible output, exact sessions, persisted messages, no implicit orchestration or tool execution, deliberate conversion to workflow |
| MCP | Real stdio initialize/tool discovery/project-memory round trip; per-command native Codex configuration resolution; advisory review/correction/approval requests cannot grant permissions or mark work verified |
| Usage comparison | All-role reported usage including retries/review/correction; separate missing/estimated/cached data; comparability checks; no actual savings claim without matched live runs |
| Distribution | Existing recursive library packaging and signing machinery retained; temporary-prefix browser onboarding, restart and safe uninstall passed; no version republished |

First-run defaults are preferences, not blanket grants. A configured fallback
creates permission requests rather than silently approving new sharing/spending.
The optional single-task policy removes a planning call but keeps tests/review;
it does not automatically infer task risk or override an explicit agent combination.
Native model reasoning/speed choices remain inherited where no verified override
contract is available. Model availability and subscription quotas are not invented.

## Actual browser and installation evidence

Eight Chrome/Playwright scenarios passed on native macOS ARM64, using fresh browser
profiles, the real backend/SQLite/filesystem, and deterministic provider fixtures.
They cover wizard persistence, once-only bootstrap, expiry/logout, proof storage,
configuration/credential forms, project preview/indexing, actual patch/test/review
completion, refresh during execution, pause/resume/cancel/retry, structured scope
approval/denial, role handoff, model overrides, memory/context, standalone streaming
and exact conversation resume. Real adapter execution is explicitly forbidden by
the browser harness. There were no JavaScript page errors. Desktop/mobile layouts
and basic keyboard labels/focus were inspected; this is not a full accessibility
certification.

A separate **installed-engine browser scenario passed**: install into a fresh
temporary prefix, launch its installed CLI, complete the wizard against a temporary
Git project, refresh, restart, confirm setup persistence, uninstall, and verify
knowledge remains. It does not alter the actual user installation.

The eight local service/security cases passed with permitted loopback sockets,
including a real process crash after a mocked implementation wrote a marker.
Restart marked the outcome `RECOVERY_REQUIRED`; the marker stayed at one, proving
that implementation was not dispatched twice. No machine reboot was performed.

Reproduction and detailed browser scope: [PHASE2-UX.md](PHASE2-UX.md).
Native MCP configuration resolution and stdio evidence: [PHASE2-MCP.json](PHASE2-MCP.json).
Actual agent-initiated MCP delegation still requires a live provider request and
was not run; global MCP configuration was not changed.

## Security review and confirmed corrections

Separate Codex sessions reviewed source and test evidence; no independent provider
review was available. [The review report](PHASE2-SECURITY-REVIEW.md) records the
high-severity cross-port cookie and session-ownership findings, their root causes,
corrections and tests. Additional confirmed fixes include:

- Prove service identity by HMAC challenge **before** sending its local control
  bearer to a possibly reused port; validate the returned loopback browser URL.
- Reject FIFO/non-regular/hardlinked service state and locks, and reject
  group/world-readable bearer metadata; use database-specific fallback paths.
- Resolve human approval requests atomically and idempotently; model requests
  alone do not grant capabilities.
- Preserve secure credential mode when changing a model; invalidate stale
  verification on credential replacement/removal.
- Fix optional browser fields becoming literal `undefined` model overrides.
- Reconcile proven-dead process ownership immediately after a controlled crash,
  while preserving a live CLI runner even if its heartbeat is late.
- MCP verification distinguishes recorded success from a current matching file
  snapshot; a later file edit returns stale/unverified without deleting history.

OS credential availability was detected, but real native vault CRUD was not
performed. Mocked OS APIs do not prove unlocked Keychain, Windows ACL behavior or a
running Linux Secret Service. No credential was written to a real OS vault.
Browser proof protects cross-port cookie disclosure; it is not protection against
a compromised same-origin script or hostile browser extension. Native CLI and
approved-command access remain broader than filtered project tools.

## Measured local resources and usage limits

[PHASE2-PERFORMANCE.json](PHASE2-PERFORMANCE.json) records a short real local sample
with 101 generated source files and mocked providers. It measures startup, idle
CPU, process peak RSS, initial/repeated indexing, context latency, static HTTP
latency, mock workflow duration/CPU, checkpoint reads and database growth. The
recorded repeat index read **zero source-content bytes**. These are observations,
not before/after optimization improvements or live-agent performance claims.

Real token optimization remains **not tested** because live requests were deferred.
The comparison implementation includes all agents and refuses a savings label for
mocked/incomplete/mismatched evidence. Cached tokens are not counted as eliminated.
Spending reservations are not upstream-enforced hard billing limits.

## Readiness and remaining limits

`V5_USER_EXPERIENCE_READY` is supported for the tested local macOS/Chrome onboarding
and controls. It is not a claim that real upstream providers or every platform
have passed. Recovery/completion/approval behavior passed automated scenarios with
real local effects and mocked providers; broader daily-development reliability
remains unverified through actual provider execution.

Withheld labels: `V5_LIVE_PROVIDER_INTEGRATION_VERIFIED`,
`V5_BIDIRECTIONAL_WORKFLOW_VERIFIED`, `V5_TOKEN_OPTIMIZATION_VERIFIED`,
`V5_AUTONOMOUS_WORKFLOW_RELIABILITY_VERIFIED`, `V5_DAILY_USE_READY`, and
`V5_FULLY_VERIFIED`. Live implementation/review/correction across all six provider
directions, native Windows, Intel macOS, WSL2, actual OS-vault CRUD, machine-reboot
recovery and representative live quality/billing measurements remain outstanding.
No CI workflow was executed or external account connected for those checks.

The team distribution mechanism is prepared and isolated installation is tested;
production release approval still requires a unique reviewed version, remaining
platform/provider acceptance and signing. Start with [PHASE2-START.md](PHASE2-START.md)
and the [durable checklist](PHASE2-CHECKLIST.md).

Other explicit scope limits: MiniMax currently uses non-streaming HTTP responses
normalized into events; native CLI events and browser streaming were mock-tested.
Live dashboard updates use bounded polling rather than a WebSocket service.
Conversation growth is bounded and a fresh context-backed conversation can be
started explicitly; automatic model-aware transcript compaction is not claimed.
No autonomous risk classifier silently selects a provider combination or reduces
an explicitly requested review policy.
