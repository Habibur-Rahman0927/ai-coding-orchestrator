# Phase 4 local validation and pilot gates

Date: 2026-11-25. Branch: `v5/phase4-pilot`. Baseline: `c933c04` plus preserved
uncommitted Phase 3 work. **Phase 4 remains incomplete; a real-project pilot is blocked.**
The verified entry archive and its manifest are in [ENTRY-STATE.json](ENTRY-STATE.json).
Nothing was committed, pushed, released or deployed. No unrelated project was modified.

Final offline regression: **351 tests, 342 passed, 9 host-specific skips, zero failures
or errors**, in 181.813 seconds. Actual Chrome dashboard: **8/8 groups passed**.
Temporary installed-product Chrome lifecycle: **3/3 groups passed** in 8.203 seconds;
onboarding, actual backend restart and uninstall preserved project/database state.
Generated workloads: **A–G passed**, with deterministic providers and actual local
effects. Actual soak: **900.309 seconds, 655 workflows**, 511 completed and 144
intentionally blocked. These results do not close the live-provider gates. Final repository hygiene passed
4/4 and unsigned local packaging validation passed after retaining the evidence;
no artifact was published.

## Evidence and deliverable map

| Requested deliverable | Evidence / status |
|---|---|
| 1. Implementation checklist | [CHECKLIST.md](CHECKLIST.md) |
| 2. Phase 3 pending closure | [ENTRY-AND-BLOCKERS.md](ENTRY-AND-BLOCKERS.md), final regression and browser reports |
| 3–5. Live providers, six directions, native interface | [LIVE-PROVIDER-AND-NATIVE-REPORT.md](LIVE-PROVIDER-AND-NATIVE-REPORT.md); BLOCKED |
| 6, 9. Workloads and correction | [WORKLOAD-REPORT.md](WORKLOAD-REPORT.md), [WORKLOAD-EVIDENCE.json](WORKLOAD-EVIDENCE.json); MOCK TESTED, actual local effects |
| 7–8. Context and automatic memory | [RESOURCE-AND-CONTEXT-CONTINUITY.md](RESOURCE-AND-CONTEXT-CONTINUITY.md); fixture continuity only, no live cross-provider claim |
| 10. Long-running execution | [SOAK-REPORT.md](SOAK-REPORT.md); actual 900.309 seconds, mock providers |
| 11–12. Human interaction and tokens | Workload accounting and [PRODUCT-VALUE.md](PRODUCT-VALUE.md); real comparative measurements BLOCKED |
| 13. Provider failover/recovery | Recovery scope below and final regression; live interruption NOT TESTED |
| 14. Browser QA | [BROWSER-QA-REPORT.md](BROWSER-QA-REPORT.md); actual installed Chrome, offline providers |
| 15. Real project | BLOCKED; no intended-provider live verification or client-workspace authorization |
| 16. Resources | Soak/context resource report; measurements limited to controlled fixtures |
| 17. Platforms | Ubuntu x86_64 local tests; other native platforms NOT TESTED in this phase |
| 18. Defects | Artifact correction below and [PAUSE-RESUME-DEFECT.md](PAUSE-RESUME-DEFECT.md) |
| 19. Final regression | FINAL-REGRESSION.json and final test log |
| 20. Remaining limitations | This report and live-provider report |
| 21. Changed files | CHANGED-FILES.json, compared with preserved entry state |
| 22–23. Product value and Phase 5 | [PRODUCT-VALUE.md](PRODUCT-VALUE.md) |

## Confirmed artifact defect

Severity: medium (release/update packaging blocked). Entry regression ran 319 tests
with one failure and one class setup error, preventing another 15 methods from running.
Six Phase 3 logs retained placeholder home paths rejected by the release builder.
The reproduction and original bytes are retained in the checkpoint. Redaction now uses
`<workspace>/`; a new regression rejects home paths even with placeholder usernames in
logs. Release security checks were not weakened. Four hygiene tests and fifteen update
tests passed after correction. [Independent review](ARTIFACT-INDEPENDENT-REVIEW.json)
verified the exact substitutions and unchanged release builder.

Browser automation failures are retained separately. Navigation races, hidden controls,
a fixture registry reset after credential changes, and rejected query-bearing URLs were
test-harness defects; they must not be reported as application bugs or successful runs.

## Recovery and platform boundaries

The applicable offline suite includes actual child-process cancellation/timeouts,
backend-process crash with unknown action reconciliation, malformed responses, explicit
handoff controls, session ownership, and checkpoint-based recovery. Workload G reopens
fresh controller/provider fixtures without replaying its patch. Browser refresh and exact
mock chat-session continuation exercise the real dashboard. These are not live provider
usage-exhaustion, authentication-failure, network-loss or context-limit demonstrations.
No provider usage restriction was bypassed and no fallback was silently selected.

Ubuntu x86_64 is the current host. Installation, process supervision, backup and update
contracts run in the local regression suite. The main dashboard CDP journey runs the source
server with an isolated database. A separate actual installed-launcher browser check
passed onboarding, project registration/indexing, backend restart and safe uninstall
with database integrity preserved. It dispatched no provider workflow and does not
establish live installed-workflow behavior. Playwright installation was previously declined and was not attempted.
No current native Windows, WSL2, Intel/Apple Silicon macOS, real OS-vault CRUD or physical
machine reboot is claimed. Historical reports are not substituted for current execution.

## Measurement limits and authorization needed

Actual model input/output/cached/reasoning tokens, provider-priced cost, comparable
standalone/memory-assisted/orchestrated runs, independent model review quality, and
reduced human effort remain unmeasured. Fixture calls and scripted approvals are counted
explicitly; they are not human interaction savings. Context byte/estimate reductions are
not provider token savings. The 15-minute soak does not stand in for 30/60-minute or live
provider runs, nor prove absence of leaks under arbitrary workloads.

To unblock live verification, specify allowed providers and maximum calls plus spend or
subscription allowance. For MiniMax, identify a secure credential reference and model;
do not paste a key. Codex reports locally authenticated, Claude is absent, and MiniMax
is unconfigured in the disposable environment. A pending question is not authorization.
Real-project work additionally needs the approved directory/copy and bounded task after
the intended provider/platform gates pass.

No `V5_PILOT_ENTRY_READY`, `V5_NATIVE_AGENT_INTEGRATION_VERIFIED`,
`V5_CONTEXT_CONTINUITY_VERIFIED`, `V5_AUTONOMOUS_DEVELOPMENT_VERIFIED`,
`V5_TOKEN_EFFICIENCY_VERIFIED`, `V5_MINIMAL_INTERACTION_VERIFIED`,
`V5_REAL_PROJECT_PILOT_PASSED`, `V5_PHASE_4_COMPLETE`, or `V5_FULLY_VERIFIED`
is issued. Local mechanism evidence is useful preparation, not proof of daily live-model
product value.
