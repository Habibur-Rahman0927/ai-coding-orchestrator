# Browser QA — BLOCKED

Chrome is installed, but Python Playwright is not. `python3 -m venv` failed because
ensurepip is unavailable. The user declined the proposed isolated Playwright install.
That action was not retried or bypassed. No actual Phase 3 browser interaction result
is claimed; Phase 2 browser reports remain historical claims.

API/auth/service tests are separate evidence and cannot replace browser journeys.
Normal unittest discovery does not include tests/browser. Required next action:
authorize isolated Playwright installation or provide an existing approved environment,
then run both tests/browser/test_workspace_browser.py and test_installed_workspace.py
with CCX_BROWSER_EXECUTABLE pointing to the installed Chrome and fresh profiles.
Use deterministic providers first; paid browser scenarios require separate budget.

Wizard, navigation, keyboard/mobile layout, duplicate clicks, reconnect, error states,
streaming and all operational controls need that rerun after these hardening changes.
`V5_BROWSER_QA_PASSED` is withheld.

## Dependency-free fallback probe

A separate review context attempted installed Chrome through its built-in DevTools
pipe, keeping Chrome sandboxing enabled and using a disposable profile. The restricted
launch failed before any CDP response (`setsockopt: Operation not permitted` in crashpad).
An escalated launch request did not complete and the waiting review turn was interrupted;
this is not a completed browser test or evidence of an application failure. No harness
files, browser interaction results, installation or download resulted from that probe.

Alternative next action: permit installed Chrome/local backend execution outside the
restrictive process/socket sandbox while retaining Chrome's own sandbox, then implement
and run CDP interaction checks. The existing full Playwright suites still require an
approved dependency environment. No security feature was disabled to make Chrome run.
