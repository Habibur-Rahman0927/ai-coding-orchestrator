# Independent Phase 6 integration review

The independent reviewer inspected actual CLI parsers, service control, installer
mutation paths, workspace backup, MCP dispatch and existing documentation. No
live provider calls or production-source edits were made by this reviewer.

Initial findings were an older global launcher without V5, ambiguous legacy
status/doctor commands, outer-parser interception of workspace help, outdated
browser token instructions and missing active-runtime exclusion during engine
mutation. Root implemented help forwarding and shared runtime locking; the
documentation now distinguishes legacy/global and checkout behavior.

Available workspace commands are projects, register, machine, index, search,
context, remember, export, forget, backup, benchmark, import-v4, providers,
dashboard, start, restart, stop, status, doctor, mcp, workflow and compare-usage.
`_serve` is internal. Top-level start/stop/restart/dashboard dispatch to V5;
top-level status/doctor remain V4. There is no workspace restore command or
dashboard backup/restore route. Recovery is a manual separate-copy procedure.

The revised lock uses the exact engine prefix, independent of database location.
CLI execution including MCP, service execution and direct WorkflowEngine.run
hold shared leases; upgrade/rollback/uninstall require exclusive access. POSIX
nested shared leases permit status/stop and multiple services. Windows code uses
shared LockFileEx semantics but was not independently run on native Windows.
Older already-running engines must be stopped before upgrade because they lack
the new lease. Imports occur before runtime lease acquisition; this review does
not assert a complete atomic module-loading protocol during concurrent startup.

Two active-workflow regressions passed independently. An additional isolated
installed-backend test checks a custom database, status while running, upgrade
and uninstall refusal with exit75, and successful mutation after stop. In this
reviewer's sandbox that test skipped because socket creation was denied. Parent
execution evidence is authoritative for any later permitted socket run. A
separate temporary-database CLI backup/status/stop probe succeeded; foreground
startup confirmed EPERM rather than an application failure. No live backend
acceptance is claimed from that blocked probe.

Remaining release limits include real MCP client compatibility, live provider
delegation and token efficiency, actual project acceptance, native platform
validation and authorized signed publication. Existing version metadata is not
an authorization to distribute modified V5 code as a new 4.3.0 release.
