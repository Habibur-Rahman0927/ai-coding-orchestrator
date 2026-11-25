# Phase 4 actual browser QA

Date: 2026-11-25. Assessed checkout: `v5/phase4-pilot`, based on `c933c04063b16d6c47b430f512fadd26b9d1e0a1`, with uncommitted QA changes.

## Current evidence

The final real-browser run passed **8 grouped scenarios** in **21.390 seconds**, exit code **0**, with **zero JavaScript page exceptions**. It used installed **Chrome 144.0.7559.109**, CDP protocol **1.3**, native Linux and Node's built-in modules. No third-party browser dependency was installed or downloaded. Chrome's sandbox remained enabled.

The final run followed the workflow pause/resume correction and strengthened session-expiry assertion. Expiry verification waits for removal of the stored browser proof and records the actual `/api/auth/session` 401 response. A prior preliminary run passed in 24.887 seconds; its weaker expiry wait and pre-correction source state are retained separately rather than substituted for final evidence.

The pause/resume browser group observes RUNNING/PAUSED/READY/CANCELLED transitions and intentionally cancels the resumed run. It does **not** independently establish successful provider completion after pause; that behavior is covered by separate targeted engine regression tests.

Machine-readable records: [final result and source hashes](BROWSER-QA-EVIDENCE.json), [sanitized execution log](BROWSER-QA-LOG.txt), [preliminary result](BROWSER-QA-PRELIMINARY.json), [attempt history](BROWSER-ATTEMPTS.json), and [installed-Chrome CDP smoke result](BROWSER-SMOKE.json).

## Reproduction and boundaries

```sh
node tests/browser/test_workspace_cdp.cjs --smoke --report=/tmp/ccx-browser-smoke.json
node tests/browser/test_workspace_cdp.cjs --report=/tmp/ccx-browser-qa.json
node tests/browser/test_installed_workspace_cdp.cjs --report=/tmp/ccx-installed-browser.json
```

The harness uses Chrome's private remote-debugging pipe. It creates a fresh browser profile and launches `cdp_workspace_fixture.py` with a temporary Git project and private SQLite database. The backend, authentication, rendered dashboard, indexing, scoped file patch and acceptance subprocess are real. UI clicks use CDP mouse input; fields dispatch normal input/change events. Native form validation and control visibility are checked.

All providers are deterministic fixtures. Both real CLI and MiniMax adapter execution methods are patched to fail, and the registry factory remains pinned to the same offline fixture across credential changes. Page HTTP requests are restricted to loopback. Only a disposable session-memory credential is submitted; no OS vault or actual provider account is changed. Browser bootstrap credentials and session proofs are not included in evidence reports.

The default sandbox initially prevented Chrome startup; the root agent subsequently ran the concrete harness with approved local-process permissions. The declined Playwright dependency installation was not retried; Chrome sandbox controls were not bypassed.

## Observed scenarios

| Group | Actual assertions |
|---|---|
| Bootstrap and setup | Bootstrap fragment removed, HttpOnly cookie unavailable to page JavaScript, six setup steps, preview before registration, actual registration/indexing, persisted setup after refresh; zero provider calls during setup |
| Provider controls | Model configuration, fake session-only credential save/remove, cleared credential input, absence of credential in rendered text, offline registry preserved |
| Workflow and correction | Unapproved Run blocks dispatch; sharing/patch/exact-command approvals; actual `bad` to `good` file patch; actual Python acceptance command exit 0; separate fixture reviewer rejection followed by correction and approval; completion survives refresh; context/results inspection |
| Memory and context | User instruction saved and retrieved through search; instruction included in assembled context; provider session screen opened |
| Pause/resume/cancel | Active Run, Pause, Resume and Cancel controls; final CANCELLED status; no completion claim for cancelled work. Successful resumed provider completion requires separate engine evidence |
| Standalone chat | Missing consent refused; actual visible partial reply and completed reply; refresh during response; second message retains the same fixture session; no localStorage data and only browser proof in sessionStorage |
| Error/accessibility/layout | Invalid project preview displays error and creates no project; rendered form controls have labels; 390-pixel layout has no horizontal overflow; keyboard focus moves; diagnostics control produces report |
| Logout/replay/expiry | Logout persists across refresh; consumed bootstrap refused; expired session returns login after actual authentication rejection and expired-proof removal |

The correction reviewer is a deterministic test double that deliberately requests changes once. This verifies the UI/engine correction path, not an upstream AI model's ability to identify defects. The frontend acceptance workload uses the same browser harness in `--frontend-project=<isolated fixture>` mode; its independent before/after results are recorded in [workload evidence](WORKLOAD-EVIDENCE.json).

## Installed CLI browser lifecycle

A separate installed-product smoke passed **3 grouped scenarios in 8.203 seconds**, exit code **0**, on the same installed Chrome version with its sandbox enabled and zero JavaScript exceptions. See [installed lifecycle evidence and source hashes](INSTALLED-BROWSER-EVIDENCE.json) and [sanitized log](INSTALLED-BROWSER-LOG.txt).

The helper ran the repository installer with explicit temporary `--prefix` and `--bin-dir` paths. It started the resulting launcher against a temporary database, imported inspection/control code from the installed `prefix/lib`, and completed actual browser onboarding, project preview, registration and indexing. It then stopped and restarted the installed backend and authenticated through a fresh bootstrap; setup completion and the registered project remained available in the dashboard. Finally, the installed uninstall script removed the temporary launcher while retaining the SQLite database and project registration; `PRAGMA integrity_check` returned `ok`.

This installed-backend scenario did not replace provider adapters with fixtures, configure credentials, create workflows, request live diagnostics or request any provider operation. The real database contained **zero provider action records** before and after restart. No user installation, actual provider session or client project was modified. Product installation here means a local copy of reviewed source into a disposable prefix, not a package-manager installation or download.

The first installed-helper attempt failed because its inspection import assumed `prefix/engine/lib`; the installer actually flattens libraries into `prefix/lib`. Correcting that test path required no product change. Both the failed attempt and successful rerun remain in installed lifecycle evidence.

## Attempt history and findings

The first six attempts are preserved as failures in `BROWSER-ATTEMPTS.json`; they are not counted as passes. Harness corrections addressed inaccessible-name matching, navigation/render timing, hidden form controls, refresh sequencing, registry replacement after credential changes, and query-bearing URLs rejected by the server. The registry-replacement attempt stopped at the production cost-approval gate with zero provider calls; the canonical-path rejection occurred before bootstrap handling. Neither required weakening a production security control.

Browser preflight also reproduced a product defect: a cancelled read-only planner result remained cached across pause/resume, causing a subsequent run to block without calling the provider. The engine correction was applied before the final browser run. Its targeted regressions retain recovery requirements for uncertain side effects; the browser status-control case does not replace those engine tests.

Expected HTTP errors include invalid-project 400, consumed-bootstrap 401 and expired-session 401. The application also returns 403/401 for unhandled `favicon.ico` requests; no JavaScript exception or failed tested workflow resulted. This is a minor resource/appearance limitation, not a failed authentication bypass.

## Unverified scope

The primary suite covers the source backend with offline provider fixtures; the separate installed suite covers onboarding, restart persistence and CLI uninstall against an actual temporary installation. Live Codex/Claude/MiniMax execution, actual OS-vault CRUD, multiple-browser-tab races, other browser engines, screen readers, full accessibility compliance, exhaustive approval denial/failover controls, browser controls for backup/restore/update/uninstall, reconnection to a failed running workflow and native macOS/Windows browser behavior remain unverified here. No actual client repository was used. Do not infer live-provider or full daily-use readiness from these results.
