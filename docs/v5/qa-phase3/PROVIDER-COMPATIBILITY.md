# Provider and delegation evidence

| Direction | Deterministic contract | Live implementation/review/correction |
|---|---|---|
| Codex → Claude | Passed | BLOCKED |
| Claude → Codex | Passed | BLOCKED |
| MiniMax → Codex | Passed | BLOCKED |
| Codex → MiniMax | Passed | BLOCKED |
| MiniMax → Claude | Passed | BLOCKED |
| Claude → MiniMax | Passed | BLOCKED |

Existing six-direction test verifies role/delegation routing, real local test commands
and completion with a mock registry; it is not a live planning/implementation exercise.
Same-provider distinct executor/reviewer sessions, correction, bounded continuation,
exact session ownership and approved failover have deterministic coverage. Session IDs
in fixtures are synthetic UUIDs; there are no live workflow/session IDs to report.

Local executable presence: Codex 0.167.0, Claude absent. Offline `codex exec --help`
and `codex exec resume --help` confirmed JSON/config/exact-session arguments without
starting a provider session. Presence is not authentication or
integration. MiniMax credentials were not inspected or exercised. No account quota
or pricing inferred. Real calls and all six live combinations need explicit usage
budget, selected models and per-project sharing permission.

Official contracts checked 2026-11-25: Codex exposes exec/resume and JSON events
([CLI reference](https://developers.openai.com/codex/cli/reference)); Claude supports
print/resume and structured output ([CLI reference](https://code.claude.com/docs/en/cli-reference));
MiniMax documents OpenAI-compatible chat completions and complete tool/reasoning history
([API reference](https://platform.minimax.io/docs/api-reference/text-openai-api)).
Documentation confirms interfaces, not compatibility of the installed executable or
account. Adapter tests use deterministic streams/HTTP fixtures; MiniMax implementation
is non-streaming HTTP normalized to events. Model availability remains configuration.

Real stdio MCP initialization, discovery of 16 tools and project-memory retrieval
passed without provider execution; no human-approval tool is exposed. Per-command
Codex config resolution passed. Native agent-initiated MCP work remains blocked.
Evidence: `mcp.json`, final provider/workflow/MCP per-test outcomes.
