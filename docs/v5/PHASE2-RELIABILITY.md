# Phase 2 workflow and context reliability

The engine continues to own authority and completion. A provider's text, MCP
request, submitted review, or failed command cannot grant permissions or mark a
task verified. Immutable V4 payloads are not modified.

## Execution controls

Workflows add bounded `max_provider_calls`, `max_context_tokens`, and
`max_continuations` budgets. Legacy databases receive safe defaults. The existing
task/depth/time/token/cost/tool/correction limits remain active. Known incomplete
responses and malformed planner/reviewer output may continue within the same
session; repeated output on the same file snapshot stops as no progress. Unknown
network/timeout effects remain uncertain and require explicit recovery rather than
automatic replay. Authentication, usage limits, context limits, permission denial,
configuration problems, cancellation and incomplete output have separate categories.

An explicit `single_task` execution policy skips the planner call, preserving the
selected executor and reviewer, trusted tests and final evidence requirements. It
does not claim that chat output is verified implementation. `model_overrides` maps
individual roles to model identifiers without modifying provider/application
defaults. Unsupported native reasoning/speed overrides are not invented.

Task dependencies are explicit same-workflow IDs. Dependencies must have completed
implementation before a dependent task runs; the final tree must still pass tests
and review. New tasks can depend only on existing tasks, preventing cycles by
construction. Task creation/delegation remains transactionally bounded.

Planner/reviewer role handoff requires a user-created `failover` scope identifying
the role and destination. Existing executor sessions, files and evidence remain
intact. A usage/authentication failure may select a preapproved destination only
when sharing, spending and native-access gates already permit it. Otherwise the
workflow stops at a recoverable checkpoint. Automatic transitions are depth-bounded.
Unknown outcomes must be reconciled before any handoff. No subscription limit is
bypassed and no new provider is silently authorized.

Lease records include the runner PID and native process birth ticks, never its
command line or environment. Startup and pre-dispatch reconciliation distinguish
a matching live owner from a dead/reused PID. Dead owners are cleared immediately;
unfinished actions become uncertain and require recovery. A live CLI runner is
not displaced when the dashboard restarts or a heartbeat is delayed. If native
identity cannot be checked, the engine waits for lease expiry and then pauses or
requires recovery rather than replaying work. Unresolved actions also block new
workflows in the same project while the interrupted workflow remains nonterminal.
Explicitly cancelled workflows cannot resume and do not permanently lock a project
after their owner exits. This is application/process recovery evidence, not
a claim of a physically tested machine restart.

## Durable knowledge and inspection

Incremental indexing runs at workflow start, after executor completion and after
verified completion, never as a continuous full-project scan. Unchanged file bodies
are not reread by the indexer. Root AGENTS.md/CLAUDE.md are included as untrusted
references when permitted, indexed and fresh; they cannot grant capabilities.
Observed corrections carry a thirty-day retrieval expiry. Completion records
include actual test/review evidence and resolved correction counts. Replaying a
completed final checkpoint reuses identical verification memory.

Visible provider events are persisted through the provider callback, bounded to
64 events per action and 2,000 characters per text event. Recognizable secrets are
redacted. Opaque reasoning/history is never copied into visible event records.
The internal transcript remains separate for exact provider continuation.

`context_report` returns per-action context references, omissions, payload size,
budget and usage accounting. `action_results` returns visible result fields, not
opaque transcripts. Workflow status exposes exact role sessions, provider-call
counts, pending requests and active/idle/recovery health. Session collision checks
cover workflow/task/role identities and standalone chats, including transactional
result persistence and initial resume.

## Native agent interface

The project-bound MCP bridge additionally exposes task inspection, execution
results, advisory review submission, bounded correction requests, verification
inspection and approval requests. `verify_task` reads engine evidence; it cannot
write a verified state. `submit_review` records untrusted advisory text, not an
independent-review completion grant. `request_approval` queues a request and grants
nothing. Cross-project and cross-workflow task IDs are rejected.

## Usage comparison

`usage_report` includes every planner/executor/reviewer action, including failures,
continuations, reviews and corrections. Missing provider counts remain missing;
partial totals are labelled. Cached/reasoning counts are separate fields and are
never subtracted as eliminated tokens. Cost reservations are not billed savings.

An explicit `full_index` context mode supports a controlled repeated-context
baseline; it refuses oversized payloads rather than silently truncating the
baseline. Normal workflows use `retrieved`. `compare_workflows` checks distinct
successful runs, modes, objectives, criteria, provider/model selections, initial
source snapshots, live-vs-mock provenance and complete reported input/output usage.
Inherited native reasoning/speed settings require additional comparison evidence;
that uncertainty prevents a verified savings label. No real provider benchmark
was executed in these tests, and no billing or real-token improvement is claimed.

## Verification

`tests/test_v5_phase2_reliability.py` exercises bounded continuation/no progress,
call caps, failure classification, authorized handoff with exact executor-session
preservation, advisory MCP boundaries, dependencies, incremental indexing,
instructions, model/policy overrides, bounded/redacted events, all-role usage
aggregation, explicit baseline budgets, approval reuse and chat/workflow session
isolation. Providers are deterministic mocks; files, SQLite and approved test
subprocesses are real. Existing workflow regressions retain crash-boundary coverage.
