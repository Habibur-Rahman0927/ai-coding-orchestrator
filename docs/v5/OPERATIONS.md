# V5 local operations

These commands run from the development checkout. An installed launcher from this
same source can replace `python3 -B engine/orchestrator.py` with `orchestrator`.
An older global launcher may not contain V5. Read the [candidate scope](RELEASE-CANDIDATE.md).

## Start and inspect

```sh
python3 -B engine/orchestrator.py open
python3 -B engine/orchestrator.py workspace status
python3 -B engine/orchestrator.py workspace doctor
python3 -B engine/orchestrator.py dashboard
python3 -B engine/orchestrator.py restart --background
python3 -B engine/orchestrator.py stop
```

`open` starts or reuses a background service and opens the browser. For `start`,
omitting `--background` starts a foreground service. No OS service is installed.
Use `--no-browser` for headless operation. Top-level `status` and `doctor` retain
V4 meanings. Workspace status and doctor inspect V5. `--version` reports the CLI
version, not V5 readiness. Lifecycle commands accept `--database PATH`; ordinary
workspace commands accept it before the subcommand. Select the same database for
start, status and stop. Port conflicts fall back to an available loopback port.

Browser startup exchanges a single-use bootstrap fragment for a session and
removes that fragment from history. If browser opening fails, use the private
fallback token file reported at startup. Reopen through start after expiry;
never put a permanent bearer in a shared URL.

## Projects and MCP

```sh
python3 -B engine/orchestrator.py workspace register /absolute/approved/project
python3 -B engine/orchestrator.py workspace projects
python3 -B engine/orchestrator.py workspace index PROJECT_ID
python3 -B engine/orchestrator.py workspace context PROJECT_ID 'task or symbol'
python3 -B engine/orchestrator.py workspace mcp --project PROJECT_ID
```

The last command is a stdio server for an explicitly configured MCP client, not
an HTTP endpoint. Configure the client to launch Python with the absolute checkout
controller path and arguments `workspace`, optionally `--database`, its absolute
path, then `mcp`, `--project`, and the registered ID. It is project-bound and does
not expose human approval grants. Client-specific configuration and protocol
compatibility require actual client verification; no native session is modified
automatically. Provider discovery is not authentication or live connection proof.

## Backup and manual recovery

```sh
python3 -B engine/orchestrator.py workspace backup /new/private/backup.sqlite3
```

This uses SQLite's online backup API, returns a SHA256 digest and refuses an
existing destination. It backs up workspace database records, not project source,
OS credential stores, native provider authentication or provider-owned sessions.
There is no workspace restore command or dashboard restore control.

For recovery, stop every service and direct runner using the affected database.
Retain the original database and its associated SQLite files together. Preserve
the backup unchanged; make a separate private working copy, verify its digest
against the backup and check SQLite integrity before use. Then select the copy:

```sh
python3 -B engine/orchestrator.py workspace --database /private/recovery.sqlite3 projects
python3 -B engine/orchestrator.py start --database /private/recovery.sqlite3
```

Recheck registered paths and credentials before running workflows. Project IDs
are path-derived; moving machines does not automatically rebind source paths.
Inspect uncertain actions and actual source state before granting recovery;
opening an old database does not undo source changes or external provider work.

## Update, rollback and removal

Engine `self-update`/`self-rollback` and project `update`/`rollback` are separate.
Use [team update instructions](../TEAM-UPDATE.md) for provenance configuration,
preview, verified backups and explicit application. Remote update checks can
contact the configured release service. No remote check is required for local
evaluation. Project updates must not be mistaken for a V5 database migration.

Current V5 runtime entry points hold a shared engine lock. Upgrade, rollback and
uninstall require the exclusive lock and refuse while that runtime is active,
including custom databases. Stop services, MCP processes and direct runners
before mutation. Older runtimes do not know this lock: explicitly stop them before
the first upgrade. Native Windows locking still requires native acceptance.

Keep workspace knowledge and credentials separate from application removal.
Uninstalling engine code does not authorize deleting project sources, native
provider sessions, workspace databases or verification history.
