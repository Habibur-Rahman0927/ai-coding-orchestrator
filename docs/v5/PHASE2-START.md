# Start and use the Phase 2 workspace

This is an unpublished V5 development checkout. It preserves V4 commands and
project payloads. Python and Git are required; no Node build, Docker, Redis or
PostgreSQL is needed for everyday local use.

## Open the workspace

From the checkout:

```sh
python3 -B engine/orchestrator.py start
```

After a normal engine installation the equivalent command is `orchestrator start`.
The single backend serves the dashboard and opens the browser. A short-lived,
single-use bootstrap is exchanged for a browser session; copying a token is no
longer the normal path. Starting again detects the same database's existing
instance and opens it. If the requested port is occupied, startup chooses an
available loopback port and prints the actual URL.

If an older manual `workspace dashboard` process is still running, stop that old
terminal with Ctrl+C first. The new lifecycle manager does not kill unknown or
legacy processes just because they occupy a port.

```sh
orchestrator start --background
orchestrator workspace status
orchestrator stop
orchestrator restart --background
orchestrator workspace doctor
```

Background mode is explicit and creates no login item, launch agent, Windows
service, or scheduled task. Omit `--background` for a foreground process. Use
`--no-browser` for headless use. Existing top-level `status` and `doctor` keep their
legacy meanings; workspace health uses `workspace status` and `workspace doctor`.
All lifecycle commands accept an explicit `--database` to select isolated state.

If automatic browser opening is unavailable, startup prints the private fallback
token-file path. Copy that exact path, not an example containing `...`.
Browser logout/expiry requires reopening through `start`; Settings can rotate
browser authentication and invalidate the current bearer/session credentials.
No permanent bearer token goes in a URL. The one-time fragment is removed from
history immediately; the origin-scoped tab proof survives refresh in
sessionStorage, and is cleared on logout. Provider API keys are never stored in
browser storage.

## First-run wizard

1. Review local platform/tools and credential-storage capabilities.
2. Discover installed providers. Installation alone does not prove authentication.
3. Configure only the providers you want to use. One provider is sufficient.
4. Choose default roles, context/execution budgets and optional fallback.
5. Preview an explicitly chosen Git project, its technologies/instructions and
   excluded paths, then register/index it.
6. Open the dashboard, start a task or review configuration.

Completed setup persists and can be reopened from Settings. Defaults are
preferences, not permission grants. A selected fallback creates an approval
request; data sharing, spending and native access remain separately authorized.

## Provider setup

Codex and Claude retain their existing native CLI authentication and defaults.
Use **Check local setup** for version/authentication diagnostics. This does not
consume model tokens or prove that an upstream request will work. Unsupported
Claude versions fail closed; Claude unavailability does not block other providers.

For MiniMax, select an explicit model, then choose one of:

- **OS storage:** macOS Keychain, Windows Credential Manager, or a detected Linux
  Secret Service client. OS prompts/locked stores may require user interaction.
- **Session only:** explicitly keep the key in this backend process's memory;
  restarting the backend loses it.
- **Environment:** provide the key to the backend's named environment variable.

There is no plaintext-file fallback. The UI can replace/remove workspace-owned
credentials without displaying the stored key. It does not copy native Codex or
Claude credentials. See [provider details](PHASE2-PROVIDERS.md).

**Test live connection** previews the isolated test, potential usage/cost, native
access and number of calls before confirmation. It is distinct from discovery.
The development user explicitly deferred live tests; no such requests were run
as part of this phase.

## Tasks, conversations and approvals

Use **Chat** for an explicitly authorized standalone, read-only conversation.
Messages persist and reuse exact sessions. Chat output is not verified code, and
ordinary messages never silently create multi-agent workflows. Native CLI access
has broader filesystem visibility than filtered project context; its own sandbox
remains in place. Each message's confirmation explains the sharing/usage scope.

Use **Workflows** to define an objective and acceptance criteria, assign roles and
choose budgets. The optional single-task policy skips planning while retaining
tests and review. Workflow model overrides do not change application/provider
defaults. The Approval Center uses named fields for providers, command arguments,
spending reservations, patches and recovery decisions; normal use needs no JSON.
Approving a request validates the exact scope; denying it grants nothing.

Activity shows real stages/events, not invented progress percentages. Pause,
resume, cancel, retry, context/results inspection and exports use the backend.
Unknown execution outcomes cannot be blindly retried. A displayed spending
reservation is not a provider-enforced hard billing cap. Native CLIs do not
provide a verified per-turn token/cost limit.

## Recovery and updates

Back up with `orchestrator workspace backup /new/private/backup.sqlite3` before
upgrading. The schema additions retain existing project memories, tasks and
session identifiers. Stop the service gracefully before replacing the engine.
After a crash, inspect recovery state and actual files before authorizing retry.
Opening the browser again does not restart a workflow.

Use the existing [team installer](../TEAM-INSTALL.md), [update/rollback guide](../TEAM-UPDATE.md)
and [release signing process](../RELEASING.md). New modules and static assets are
included by the existing recursive library packaging. Keep databases, credentials,
session histories and service metadata out of artifacts. Removing the engine is
not permission to delete knowledge or OS credentials; remove a workspace-owned
key explicitly in Providers if desired.

The engine version has not been republished or retagged. A reviewed unique release
version, native platform acceptance and release signing are still required before
team production distribution. See measured results (source checkout: `docs/v5/PHASE2-RESULTS.md`; omitted from packages).
