# Context, memory and isolation

Nine new independent tests use three different temporary projects (PostgreSQL
backend, SQLite desktop, static frontend), Unicode/spaced paths and malicious
AGENTS instructions requesting another project's data. Search, export, context,
MCP workflow lookup and delegation enforce scope. Shared/global memory is not
silently added. Deleted memory cannot be returned by a newly constructed cached
context. Concurrent writes survive reopen and SQLite backup integrity checks.

Branch switching, renaming, deletion and untracked source changes invalidate stale
retrieval. Existing tests cover binary/secret/ignored/link exclusions, snapshots,
restart, supersession and expiry. Root rules and explicit user instructions now
remain whole; oversized required context fails rather than dropping constraints.
These checks pass locally with real SQLite/filesystem effects.

Context remains bounded retrieval with byte-based token estimates. Hierarchical
summaries, automatic model-aware compaction and unlimited memory are not established.
Provider-specific context windows and medium/long real native-session reconstruction
remain unverified. Actual killed uncommitted writes, SQLite capacity exhaustion, partial backup failure,
corrupt database refusal, schema rollback and contended writers now have passing tests.
No machine reboot or exhaustive corruption matrix was executed. Broad `V5_CONTEXT_INTEGRITY_VERIFIED` is withheld pending that scope.

Evidence: `context-after.log`, `context-memory.log`, `context-workflows.log`,
`independent-context-review.log`, final per-test report; sources store.py, mcp.py,
workflows.py and test_v5_phase3_context.py.

Storage checks also prove deleted successors do not resurrect superseded history,
including after clock rollback; unsupported schema opening preserves original bytes.
