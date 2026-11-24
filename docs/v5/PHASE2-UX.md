# Phase 2 user experience and browser evidence

The dashboard now supports the normal local flow without copying a permanent
access token. Start it with:

```sh
python3 -B engine/orchestrator.py workspace start
```

The application opens a one-use sign-in window. The browser removes the bootstrap
fragment before requesting application data, exchanges it for an expiring HttpOnly
session, and retains a separate origin/port-bound request proof in session storage.
The proof supports refresh without putting the bearer token or provider key into
browser storage. Logout, rotation, or expiry requires a fresh sign-in. A manual
bearer-token fallback remains available for environments without browser launch.

## Setup and everyday use

The six-step wizard detects the environment and credential facility, distinguishes
local provider availability from live verification, configures only selected
providers, saves workflow defaults, previews/indexes an approved Git repository,
and offers the dashboard or a first task. Completed setup is persisted; reopen it
from Settings. Registering a project requires an explicit directory and shows a
bounded preview before indexing. No whole-machine or unrelated-project scan runs.

The provider screen inherits CLI defaults unless an application model override is
saved. MiniMax keys can be submitted to the selected OS credential facility or an
explicit session-only store; ordinary configuration never stores the key. Saving a
key is not a connection test. Live tests show their synthetic request plan and
require confirmation before provider usage. Historical verification is not a quota
or current-service guarantee.

The task form selects all three roles explicitly, uses the saved budgets, and
supports optional per-workflow model overrides. Single-task policy skips the
planning call but retains tests and independent review. It does not silently
replace a provider combination. Creating a workflow does not start it.

Permissions are presented as fields rather than requiring JSON authoring. The
confirmation still shows the exact scope. Controls reflect actual lifecycle state;
active/terminal runs cannot be started twice from the page. Pending agent requests
are visibly unapproved until the user approves or denies them. Handoff controls
require matching failover and destination authorizations.

Workflow updates poll every three seconds only while a runner is active, pause
fetching while the tab is hidden, and preserve form entries. The page shows actual
roles, verified task counts, health/blockers, event text, test/review evidence,
execution results and the context packages used by recorded actions. No invented
percentage progress is displayed. Significant state transitions produce in-app
notifications; desktop/browser notification permissions are not requested.

Chat is deliberately standalone and read-only. Each message requires explicit
project-sharing/provider-usage consent. Visible chunks are persisted and polled;
refresh resumes viewing the same conversation without dispatching another message.
Switching to orchestration requires a deliberate action and creates a workflow
without running it. Conversation answers are not verified implementation evidence.

## Real browser tests

`tests/browser/test_workspace_browser.py` runs installed Chromium through
Playwright against the actual HTTP server, SQLite store, indexing and workflow
engine. Only provider responses are deterministic mocks. It uses temporary Git
projects and fresh browser contexts; it does not reuse a personal browser profile
or send requests to a provider API. The workflow case applies a real scoped patch,
runs a real test program, and completes the independent-review gate.

Covered interactions:

- All six onboarding steps, preview before registration, indexing and persisted defaults.
- Bootstrap exchange, consumed-link replay refusal, refresh, expiry and logout.
- Provider configuration and explicit session-only credential save/remove with a fake key.
- Project registration error state, labelled editable controls, keyboard focus and mobile layout.
- Workflow role selection, structured permissions, real patch/test/review completion and refresh during execution.
- Active execution pause/resume/cancel, retry at an approval gate, and prevention of unapproved dispatch.
- Memory search, context inspection, stored session list, streaming standalone chat and exact session resume.
- No JavaScript page errors, no localStorage entries, and only the request proof in sessionStorage.

The suite is optional developer tooling, not an application runtime dependency.
Example isolated setup on a machine with Python 3.9+ and Chrome installed:

```sh
python3 -m venv /tmp/ccx-browser-tests
/tmp/ccx-browser-tests/bin/python -m pip install 'playwright==1.60.0'
/tmp/ccx-browser-tests/bin/python -B tests/browser/test_workspace_browser.py
```

No Playwright browser download is needed when Chrome is installed at its standard
macOS path. On other platforms set `CCX_BROWSER_EXECUTABLE` to an installed Chromium
executable. Set `CCX_BROWSER_ARTIFACT_DIR` to an existing approved directory to keep
screenshots; otherwise screenshots remain inside the disposable test fixture.

The development run uses actual macOS ARM64 Chrome. Native Windows, Intel macOS,
other browser engines, screen-reader auditing, external MCP-client interaction,
and paid-provider browser scenarios remain separate checks. These browser results
must not be described as live provider verification or full accessibility certification.

## Recorded result — 2026-11-25

The final real Chromium run completed **8 tests, 8 passed**, in **46.263 seconds**
on macOS ARM64. It includes explicit observation of a partial chat reply while the
agent is still responding, approval-request denial/approval, authorized role
handoff, and persistence of workflow-specific model overrides. Real CLI/API
adapter execution is patched to fail in the harness, so adding a browser test
cannot silently turn it into a billable provider test. Provider configuration and
credential tests use only a dummy session key; native credential stores remain
untouched. Desktop and 390-pixel mobile screenshots were captured and inspected.

Confirmed browser/UI corrections:

| Severity | Finding | Correction / evidence |
|---|---|---|
| Medium | The generic DOM helper converted omitted values to literal `undefined`, including unintended model overrides | Skip null/undefined value assignments; browser assertions require empty override fields and exactly the selected override in SQLite |
| Medium | Workflow creation previously hardcoded the planner to Claude | Explicit orchestrator selector populated from application defaults; browser checks choose roles and preserve them |
| Medium | `Unavailable` matched the old positive `available` status regex | Match positive states explicitly; unavailable/unknown states stay visibly distinct |
| Low | Old error notices remained visible after leaving their page | Clear transient notices on navigation; invalid registration and subsequent navigation tested |

The parent security review also required a separate browser request proof because
cookies are host-scoped across local ports. All frontend requests now include the
origin-scoped proof, including session recovery; refreshed-session, expiry, logout,
replay and storage-boundary browser checks pass after that correction. API-level
cross-port/cookie-only rejection is recorded in the security test report.
