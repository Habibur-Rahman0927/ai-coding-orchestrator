# V5 implementation and verification evidence

Date: 2026-11-25. Branch: `v5/universal-workspace`. Status: unpublished development
implementation. No commits, pushes, merges, publication, deployment, paid API calls,
global installation, credential changes, or client-project modifications were made.

## Recorded test runs

| Check | Result |
|---|---|
| Clean V4 baseline, native macOS ARM64 / Python 3.9.6 | 152 run: 145 passed, 7 skipped |
| Combined regression, native macOS ARM64 | 225 run: 217 passed, 8 skipped; 164.259 seconds |
| Combined regression, Debian 12 Linux ARM64 container / Python 3.11 | 225 run: 214 passed, 11 skipped; 50.521 seconds |
| Focused V5 suite after final recovery corrections, macOS | 75 run: 74 passed, 1 loopback restriction skip; 10.231 seconds |
| Focused V5 suite after final recovery corrections, Linux | 75 run: 74 passed, 1 missing JavaScript parser skip; 5.910 seconds |
| Final dashboard tests with permitted loopback sockets, macOS | 10 passed, including actual HTTP and JavaScriptCore syntax |
| Isolated temporary-prefix install | Installed workspace provider discovery and dashboard assets passed |
| Unsigned local artifact build | Passed; V5 package/assets included; no runtime database/token/bytecode included |
| Python 3.8 syntax parsing | All 11 workspace modules passed; not a Python 3.8 runtime claim |
| Immutable release preservation | `git diff --exit-code -- engine/releases` passed |

The macOS combined run skips six native Windows checks, one Linux-only check,
and the sandbox-restricted loopback check. The separate permitted
loopback run closes the HTTP gap. Linux skips native Windows/non-Linux checks,
one root-user permission check, and its missing JavaScript parser. The first Linux
attempt ran unittest as container PID 1, which the watchdog deliberately refuses;
the passing run used a shell parent, without changing the watchdog or its test.
Repository hygiene initially caught a synthetic private-key marker; the fixture
was corrected and the final combined runs passed the unchanged scanner.
The focused runs include all final source corrections after the combined runs,
including 21 workflow tests and both test-command crash boundaries.

## Implemented coverage

| Area | Implemented | Evidence boundary |
|---|---|---|
| Machine knowledge | Cached native OS/architecture/tool availability, memory/disk metadata, explicit refresh | Local only; no service/network/filesystem-wide discovery |
| Project memory | SQLite scopes, provenance, confidence, expiration, supersession, export/delete, backup/reopen | Persistence and project isolation tested; no cloud sync |
| Code intelligence | Explicit Git roots, exclusions, incremental stat/hash index, SQLite FTS fallback, Python symbols/imports | Other languages have text retrieval, not semantic parsing |
| Context | Task query retrieval, critical constraints, staleness checks, deduplication, source references, bounded payload, package reuse | Token figures estimated from bytes; no provider tokenizer guarantee |
| Providers | Codex/Claude CLI adapters, independent MiniMax HTTPS adapter, capability metadata and exact sessions | Controlled CLI/mocked HTTP tests; no live authenticated verification |
| Orchestration | Planning, bounded tasks/depth, provider-neutral delegation, separate reviewer sessions, correction loop | All six cross-provider directions tested with deterministic mocks |
| Completion | Engine-run approved tests, matching file snapshot, criterion-by-criterion reviewer evidence, persisted verified result | A provider's self-reported success alone cannot complete a workflow |
| Recovery | SQLite checkpoints, project leases, uncertain action gate, explicit failover, pause/resume/cancel | No automatic replay of uncertain external effects |
| Interface | CLI, loopback authenticated API, dashboard, project-bound stdio MCP | Real store/engine API tests; browser interaction and external MCP-client QA pending |
| Distribution | Existing recursive installer, isolated-prefix smoke test, unsigned local artifact build | No release/version publication or new signing ceremony |

The implementation deliberately uses serial execution inside each project lease.
Different projects may run concurrently. `max_concurrency` is an upper bound, not
a promise of parallel task execution inside one project. Planner/executor/reviewer
are engine stages; debugger/QA/research/documentation work is expressed through task
instructions rather than separate privileged provider types. Single-provider work
uses separate executor/reviewer sessions and retains the completion checks.
Arbitrary embeddings, all-language ASTs, automatic provider failover,
cross-machine path rebinding, and provider-enforced hard billing caps are not claimed.

## Measured context performance

Run `python3 -B tools/benchmark_workspace.py`. The committed
[machine-readable result](BENCHMARK.json) uses 33 generated files and three exact
symbol queries. Repeating the full indexed corpus supplied 324,858 bytes; bounded
retrieval supplied 573 bytes, a **99.82% reduction for this synthetic fixture**.
Each query retained its target reference and the critical constraint. The repeated
index read zero source-content bytes for 33 unchanged files. Retrieval was about
1.5–1.9 ms per query in that recorded macOS run; timings vary by machine/load.

This deliberately sparse fixture is not a representative production savings rate.
There are no measured live input-token savings, cached-token savings, cost savings,
task-quality improvements, or reductions in human interventions. Those require
matched real-task/provider experiments. History replay may consume additional
provider context; the engine rejects oversized estimated requests rather than
claiming a verified model-aware compaction algorithm.

## Independent review and corrections

Codex implementation and reviewer sessions inspected source and tests. This is
separate-session review, not independent-provider/model judgment. Claude was not
used because of the stated usage limit. Confirmed issues and targeted corrections:

| Defect | Correction and regression coverage |
|---|---|
| Same-provider roles rejected or sessions could collide | Allow separate roles; require distinct actual review session and reject cross-role/session reuse |
| Workflow omitted retrieved task context | Attach bounded source-backed context and preserve objective/acceptance criteria |
| Missing usage could look like free execution | Explicit spending approval and conservative per-call reservations; label estimates/reservations |
| Role alone could authorize patches | Require explicit scoped patch approval; agent output cannot grant permissions |
| Uncertain external action could be replayed | Durable uncertain-action gate and explicit recovery; completed evidence is reused |
| Crash between test completion and evidence checkpoint could repeat a command | Stable scope/snapshot/attempt action identity, cached result reuse, and explicit retry authorization for uncertain outcomes |
| Snapshot/index could include excluded or unsafe paths | Casefolded exclusions, bounded ordinary-file reads, hard-link/link refusal, project exclusion propagation |
| Legacy source could belong to a different project | Bind state directory and manifest/record identity to the selected project |
| Database replacement/backup race | Revalidate storage paths and use exclusive destination creation |
| Malformed MCP params could terminate the server | Validate object params and tool argument schemas; test cross-project task spoofing |
| Saved provider settings differed across interfaces | Shared sanitized settings registry for dashboard, CLI and MCP |
| Synthetic private-key fixture triggered repository scan | Construct test marker in parts; retain the privacy scanner unchanged |

## Verification gates and remaining work

Native macOS ARM64 and a cached Debian-based Linux ARM64 container are available.
Linux tests use network-disabled containers, a read-only source mount, disposable
temporary state, and no host credentials. This does not establish all Linux distro
matrix targets. Native Windows and macOS Intel were unavailable. Cross-platform
adapters and mocked branches do not substitute for those native runs.

Actual upstream Codex/MiniMax execution requires explicit sharing/spending scopes
and a configured MiniMax model/key. No live call was made. Claude-dependent runs
remain pending until the stated usage limit allows them. Cancellation closes local
transports/processes; it cannot undo provider-side work or guarantee billing stops.
Native-agent file access is broader than controlled-tool filtering and needs its
own approval. Secret pattern filters cannot identify every possible secret.

Do not assign `BIDIRECTIONAL_AGENT_DELEGATION_VERIFIED`,
`AUTONOMOUS_WORKFLOW_VERIFIED`, or `UNIVERSAL_AI_WORKSPACE_V5_FULLY_VERIFIED` from
mocked tests. The final acceptance gate remains open for live providers, native
platforms, actual browser/client integration, and representative quality/billing
benchmarks. See the [durable checklist](CHECKLIST.md) and
[baseline audit](BASELINE-AUDIT.md).

Supported milestone labels: `PERSISTENT_INTELLIGENCE_READY` (restart/backup/recovery
tests), `CONTEXT_OPTIMIZATION_VERIFIED` (the bounded synthetic measurement above),
`UNIVERSAL_ORCHESTRATION_CORE_READY` (automated core tests with mocked providers),
and `V5_DASHBOARD_READY` (real backend routes and loopback HTTP; browser visual QA
still pending). These scoped milestones are not a fully verified release claim.
