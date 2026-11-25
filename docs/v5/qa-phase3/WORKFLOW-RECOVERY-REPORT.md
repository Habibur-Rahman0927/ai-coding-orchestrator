# Workflow, completion and recovery scope

Existing deterministic suites cover six delegation directions, distinct same-provider
sessions, actual command acceptance checks, correction budgets, plan dependencies,
duplicate/project leases, provider-call/token limits, malformed/no-progress results,
authorized failover, session collision, stale evidence and checkpoint reuse.

New native subprocess regressions prove cancel/pause stops approved commands, including
provider-requested tools, and prevents dispatch when already cancelled. Independent
review waited beyond the original child deadline and observed no delayed marker write.
Cancelled/paused uncertain actions require reconciliation rather than automatic retry.

Permitted local service suite: eight passed, including backend crash after a mocked
executor's real file effect; restart preserves unknown outcome and avoids duplicate
execution. This is a real process crash with a mocked provider, not a live API outage.
Completion requires trusted test records and reviewer evidence matching snapshots;
executor self-reports and MCP advisory reviews alone are insufficient.

Unverified: all crash injection windows, machine reboot, power loss, all migration paths, long silence/high-CPU soak, multi-day histories, live provider handoff,
and real provider quality. Multi-task execution is serialized by design; no claimed
parallel write execution. Broad stress/recovery labels remain withheld.

Additional stress: seven tests pass, including 12 repeated workflows/four corrections,
32 mock provider calls and 48 durable actions; separate projects progress concurrently
while same-project/duplicate starts remain serialized. A real quiet command completes.
Malformed usage after a real side effect stays uncertain with no automatic replay.
Eleven storage fault tests exercise killed writes, real SQLite page limits, backup
cleanup, corruption/schema refusal, transactional initialization and contention.
