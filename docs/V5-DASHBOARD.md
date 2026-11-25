# Local V5 dashboard

The dashboard is a buildless interface to the V5 SQLite workspace, project index,
memory, provider registry, and durable workflow engine. It uses Python's standard
library HTTP server. No Node installation, public hosting, authentication service,
or remote database is required.

Start it from a trusted source checkout or an installed engine:

```sh
orchestrator workspace dashboard --port 8765
# Source checkout:
python3 -B engine/orchestrator.py workspace dashboard --port 8765
```

Use `python` instead of `python3` when that is your Windows Python command.
The server prints its loopback address and the location of a private token file,
`dashboard-PORT.token`, next to the workspace database. Read that file locally
and paste the token into the dashboard login form. The token is not included in
the URL, console output, HTTP logs, HTML, or browser storage. It stays in the
tab's memory until disconnect or reload. A normal server shutdown removes its
matching token file. If an unclean shutdown leaves a token file, verify that its
server is no longer running before removing that stale file and restarting.

To use an isolated workspace database:

```sh
orchestrator workspace --database /absolute/private/directory/workspace.sqlite3 dashboard --port 8765
```

## Working screens

| Screen | Implemented operations |
| --- | --- |
| Overview | Actual project, workflow, provider, runner, and machine summaries |
| Projects | Register an explicit Git root with optional exclusion patterns; build its index; open memory or context |
| Memory | Add a user instruction, search scoped knowledge, inspect/delete records, export project memory |
| Context | Assemble relevant knowledge with a token budget and critical instructions; download the result |
| Workflows | Create objective/criteria/budgets; add tasks; delegate; run/pause/resume/cancel; inspect evidence and usage |
| Approvals within a workflow | Grant exact JSON scopes as the user; inspect and revoke approvals |
| Checkpoints within a workflow | Load the persisted chronological record |
| Providers | Discover local availability; select models; configure an API-key environment-variable **name**; save preferences; run a nonbillable availability check |
| Activity & usage | Inspect recorded workflow events, token/cost totals, and budgets |
| Settings | Inspect fixed connection boundaries; refresh local machine discovery; disconnect |

Provider preferences are shared by the dashboard and callers of
`ccx_workspace.settings.registry_for(store)`. Credentials are not settings:
the dashboard never accepts an API-key value. Availability checks do not claim
successful authentication or a live model invocation.

A workflow with a zero cost budget cannot make a live provider call. Set a
positive budget deliberately when creating it, then grant the relevant sharing,
cost, and native-access scopes. Cost scope includes both a maximum total and a
conservative per-call reservation (`max_cost` and `max_call_cost`). Native Codex workspace writes require their own
approval; scoped file patching also requires an `operations` approval. Execution and review use distinct role sessions, including when they use the same provider. A command
approval names the exact argument list, working directory, and timeout; model
output cannot create that approval. See the workflow guide for engine rules.

The UI refreshes when an action completes or you choose Refresh. A selected
running workflow polls every three seconds, updating status, task evidence, and
events without replacing approval or task forms. The screen reports connection
failures and retries; hidden tabs pause polling requests. Manual Refresh status
is also available. Pause/resume are persisted
control changes; use Run when ready to start/resume execution. Usage shows
recorded totals and identifies missing reporting; it is not a billing estimate.

## HTTP boundaries

- Bind is restricted to IPv4 loopback. No LAN or wildcard address is accepted.
- Every API operation requires the random bearer token, including reads.
- Host must match localhost/127.0.0.1 and the actual port. Foreign origins,
  duplicate origins, cross-site requests, URL query parameters, and CORS preflight
  are refused. No wildcard CORS is emitted.
- Mutations require a JSON object, a single Content-Length, and at most 64 KiB.
  Chunked requests are refused. Connections time out after 15 seconds; at most
  32 HTTP handler threads and four dashboard workflow runners are admitted.
- Only the three fixed static assets are served. No arbitrary filesystem route
  exists. Content Security Policy excludes external scripts and frames; dynamic
  project content is inserted with text nodes rather than HTML parsing.
- Access logs are disabled, and unexpected exceptions return a generic error
  rather than prompts, credential values, or private exception details.
- The token file and database remain under protected per-user filesystem policy.
  Authentication does not protect against another program already running with
  the same user's full filesystem privileges.

## Verification and limits

Run:

```sh
python3 -B -m unittest discover -s tests -p test_v5_server.py -v
```

The tests exercise the real HTTP parser against in-memory transport, backed by
the real Store and WorkflowEngine, without live provider calls. They cover
authentication, origins, body limits, static routing, persistent preferences,
project knowledge operations, workflow controls, and approval scope handling.
JavaScript syntax is checked using an installed Node executable or macOS
JavaScriptCore.

The restricted sandbox initially refused loopback listening with `Operation not
permitted`; the actual socket test was explicitly skipped in that run. A later
authorized run on the MacBook passed all ten tests, including a real authenticated
loopback HTTP request. Browser rendering and an end-to-end browser session have
not been visually verified. Browser verification remains required. No dashboard was
published, no remote service was created, and no live provider call was made.
