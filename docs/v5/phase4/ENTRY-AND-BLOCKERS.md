# Phase 4 entry state and external gates

Date: 2026-11-25. Dedicated branch: `v5/phase4-pilot`, based on `c933c04` plus
preserved uncommitted Phase 3 changes. No commit, push, merge, publication or deployment.
ENTRY-STATE.json records all files and the verified recovery archive. All 38 immutable
V4 payload files match the committed baseline. Phase 3 work has not been discarded.

The initial full regression exposed an artifact packaging defect: six retained Phase 3
logs contained placeholder absolute home paths that the release builder rejects.
The update suite's setUpClass error prevented 15 further test methods from executing;
319 tests ran, with one failure, one setup error and nine host-specific skips. This is
not a passing 334-test run. Original evidence is preserved in the entry checkpoint.
Only those checkout prefixes were replaced with `<workspace>/`; test outcomes and
traceback line numbers were retained. A new hygiene test rejects home paths in logs,
even placeholder usernames. The release guard was unchanged. The 15-case update suite
and four hygiene tests passed after correction. Final full results are recorded separately.

## Provider authorization

No live-provider budget was supplied in the Phase 4 request. A provider-specific
usage/budget question is pending; elapsed time is not authorization. No provider call
may occur until an explicit response is received. Native Codex 0.167.0 responds and
reports locally authenticated status. That is not successful model execution.
Claude is absent. MiniMax is unconfigured in the deliberately fresh pilot environment;
no claim is made about uninspected user configuration elsewhere.

Exact user actions for live work: authorize providers plus maximum calls/spend; identify
a secure MiniMax credential reference and intended model if using MiniMax. Never paste
keys into chat. Generated fixtures may be shared only under that explicit authorization.
No actual client directory is registered or modified. A real-project pilot also requires
explicit workspace/task authorization after all applicable entry gates pass.

## Browser and platform scope

Installed Chrome's dependency-free CDP smoke test passed with its own sandbox enabled,
using a disposable profile and permitted process/socket execution. No Playwright package
was installed and the previous installation refusal was respected. Full actual dashboard
and frontend journeys are reported separately; smoke alone is not browser QA completion.

Native host: Ubuntu24.04 x86_64/Python3.12. Other native platforms, real OS-vault CRUD,
and actual machine reboot remain unavailable/not executed. No current remote CI, container
or prior macOS report is silently counted as a current native pass.

## Scope labels

Local engine dogfood uses deterministic providers with actual filesystem, test-process
and SQLite effects. Context and correction mechanism results do not establish native
model quality, token savings, independent-provider judgment or reduced human effort.
Real comparisons and real-project acceptance remain gated by explicit live authorization.
