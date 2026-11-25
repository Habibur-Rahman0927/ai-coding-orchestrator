# Independent architecture review

The standard-library architecture is proportionate to a local development tool.
SQLite owns durable project/workflow state; WorkflowEngine owns approvals, budgets,
leases and completion; adapters normalize provider behavior; MCP is project-bound;
the authenticated loopback server and buildless dashboard expose those controllers.
Do not rewrite these stable boundaries solely to change frameworks.

Confirmed duplication had security consequences: store and tools used incompatible
secret recognizers and unsafe duplicate file readers. The correction introduces a
small shared security module. Cancellation was not propagated across the engine/tool
boundary; targeted propagation now uses the existing owned process supervisor.

`store._source_stale` imports workflow snapshot logic lazily while workflows imports
store helpers. This runtime dependency cycle works in current tests, but snapshot
policy could later move into a neutral module if maintenance justifies it. No rewrite
was made. Snapshot/indexing/tool path policies still need coordinated review.

State uses short SQLite transactions and a project execution lease. Process identity
includes birth identity; unknown actions require reconciliation rather than blind
replay. Tests substantiate local duplicate-execution and recovery scenarios, not
power-loss atomicity or all failure windows. Store initialization and audit writes
can be separate transactions; targeted disk-full, partial-backup and schema-failure rollback now pass.

Resource bounds exist for file sizes, output, tools, provider calls, context packages
and conversations. Histories/checkpoints are retained rather than silently deleted.
Index content reads are incremental but Git discovery and metadata traversal remain
O(file count). Search checks current content hashes. Full-scale throughput, multi-day
soak and large-history growth are not established.

Permissions must remain backend-owned; inspected MCP advisory reviews and approval
requests cannot grant capabilities or mark tasks verified. Same-provider distinct
sessions are tested, but do not provide independent model-level assurance.
