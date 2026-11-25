# V5 local workspace development guide

V5 extends the existing engine; it does not migrate or replace V4 runtime state.
The workspace package identifies itself as `5.0.0-dev`. The distribution keeps the
existing engine version until a separately reviewed release. Do not publish this
branch as another 4.3.0 release.

## Run from the checkout

Python 3.8+ and Git are required; SQLite and the HTTP server use the standard library.
No Node build, cloud account, or package installation is needed for the dashboard.

```sh
python3 -B engine/orchestrator.py workspace --help
python3 -B engine/orchestrator.py workspace register /absolute/path/to/approved/repository
python3 -B engine/orchestrator.py workspace projects
python3 -B engine/orchestrator.py workspace index PROJECT_ID
python3 -B engine/orchestrator.py workspace context PROJECT_ID 'task or symbol' --budget 2000
python3 -B engine/orchestrator.py workspace dashboard --port 8765
```

Registration is explicit and indexing is limited to that Git project. Repeat
`register` with `--exclude 'private/*'` to set project exclusions. Global machine
knowledge is local and is not automatically included in provider context.
The default database is `workspace-v5/workspace.sqlite3` under the platform's
native engine data directory. Override it with `workspace --database PATH ...`.
The database and its backups contain private project knowledge; protect them as
local development data. Do not commit or distribute them.

The server prints a loopback URL and the location of a private token file. Paste
the token into the page. The token is not embedded in the URL or served HTML.
See [dashboard/API details](../V5-DASHBOARD.md).

## Workflows and authorization

```sh
python3 -B engine/orchestrator.py workspace workflow create PROJECT_ID \
  'Implement the requested change' --criterion 'Specified tests pass' \
  --orchestrator codex --executor minimax --reviewer codex \
  --budgets '{"max_cost":1,"max_tasks":8,"max_retries":2}'
python3 -B engine/orchestrator.py workspace workflow status WORKFLOW_ID
python3 -B engine/orchestrator.py workspace workflow run WORKFLOW_ID
```

Unapproved runs stop at an approval gate. Provider discovery/probe performs no
authenticated network request. Configure MiniMax's explicit model and environment
variable **name** in Providers, and supply the key only to the process environment.
See the [provider configuration and capability guide](../V5-PROVIDERS.md).

Inspect exact workflow approval scopes in the dashboard before approving. Sharing,
spending, native-agent access, native writes, controlled patches, and exact test
commands are separate decisions. The CLI's `workflow approve ... --yes` is a human
control, never an agent tool. A spending approval requires both a total and a
conservative per-call reservation; reservations are not provider-enforced billing
limits. A positive workflow spending budget is also required. An approved command
can do whatever that program permits; its process supervisor is not a filesystem
sandbox. Do not approve unfamiliar commands.

Pause/cancel is persisted and observed by the active runner. A crashed in-flight
call is marked uncertain and is not automatically replayed. Inspect its checkpoint
and actual project changes before granting recovery. Failover requires an explicit
destination approval and fresh sharing/spending permissions. Separate sessions are
required when executor and reviewer use the same provider. Reviews must identify
the tested file snapshot and provide evidence for every acceptance criterion.

## Agent-native access

Start `workspace mcp --project PROJECT_ID` as a stdio MCP server from an explicitly
configured client. It exposes project-bound context, memory search, provider
discovery, workflow/task creation, task delegation and execution controls. It does not expose human
approval grants. The bridge supports newline JSON-RPC and protocol `2025-11-25`;
compatibility with external MCP clients has not been live verified. No client
configuration or existing agent session is modified automatically.

## Backup, import, recovery and rollback

`workspace backup /new/private/path/backup.sqlite3` uses SQLite's online backup
API and refuses an existing destination. Stop active runners before recovery,
retain the old database, and open a backup with `workspace --database BACKUP ...`.
Recheck project paths after moving machines. Registration IDs are path-derived;
relocated project rebinding is not automatic.

`workspace import-v4 PROJECT_ID /selected/legacy/state/directory --yes` imports
only bounded allowlisted session/task metadata. It never edits V4 source state,
imports logs, or grants V5 permissions. Inspect the import result. Existing V4
runtime session mappings remain authoritative for V4 commands. This is a knowledge
import, not a converter for resuming a V4 execution as a V5 workflow.

To stop using V5, stop its dashboard/runners and use the unchanged V4 commands.
Retain the separate database for recovery. Existing installer backup/rollback
mechanisms still apply to the engine; neither updating the engine nor uninstalling
its executable should be treated as permission to delete workspace knowledge.

## Installation and team distribution

The existing installers package the recursive `engine/lib` tree, including the
workspace and its static dashboard. Evaluate installs using an isolated prefix
and bin directory first; the [team installation](../TEAM-INSTALL.md),
[update](../TEAM-UPDATE.md), and [signed release](../RELEASING.md) procedures remain
the distribution mechanisms. Never include a local SQLite database, provider
credentials, dashboard token, or live transcript in a release.

No global installation, signing key creation, publish, or account setup is
performed by this implementation task. Release signing and native Linux/Windows/
Intel-Mac acceptance remain separate gates in [RESULTS.md](RESULTS.md).

## Reproduce checks

```sh
python3 -B -m unittest discover -s tests -p 'test_v5_*.py' -v
ORCH_TEST_RELEASE=4.3.0 python3 -B -m unittest discover -s tests -v
python3 -B tools/benchmark_workspace.py
```

Loopback tests explicitly skip when the environment denies socket binding.
Provider tests use controlled subprocesses/mocked HTTP and never require API keys.
