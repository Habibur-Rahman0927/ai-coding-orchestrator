# V5 provider adapters and project tools

Provider execution is a separate engine boundary. Installing, discovering, configuring,
or probing an adapter does not authenticate, send a prompt, or incur an API charge.
Workflow sharing, spending, command, and native-agent approvals belong to the trusted
engine/user; an agent response can never grant those approvals.

## Configuration

The registry accepts a mapping keyed by `codex`, `claude`, and `minimax`:

```json
{
  "codex": {},
  "claude": {},
  "minimax": {
    "model": "YOUR_EXPLICIT_MODEL_IDENTIFIER",
    "api_key_env": "MINIMAX_API_KEY",
    "endpoint": "https://api.minimax.io/v1/chat/completions"
  }
}
```

Supply the actual MiniMax key through the named environment variable in the process
that starts the workspace. Do not put its value in JSON, project files, prompts,
command-line arguments, logs, or the dashboard. The adapter never changes credentials
or saved CLI preferences. Optional CLI `model` overrides apply only to that request;
omitting them preserves the CLI's configured choice. No model name is assumed for
MiniMax, and pricing is not inferred from model names.

MiniMax calls its own official API directly, independently of Claude. The fixed HTTPS
origin/path is allowlisted, TLS verification is enabled, and HTTP redirects are rejected.
The implementation uses the standard-library HTTPS client without a global SDK or pip
installation. The [official MiniMax model invocation guide](https://platform.minimax.io/docs/guides/text-generation)
and [OpenAI-format guide](https://platform.minimax.io/docs/api-reference/text-openai-api)
document the endpoint and request format used here. Documentation was consulted on
2026-11-25; no live authenticated requests were made during implementation.

## Capability boundaries

| Adapter | Session behavior | Local execution | Limits |
|---|---|---|---|
| Codex CLI | Exact UUID resume; never `--last` | Explicit `native_agent_access`; read-only sandbox by default, separate `native_agent_write` approval for workspace-write | Native file access does not pass through the controlled secret filter; no verified per-turn token/cost cap |
| Claude CLI | Exact UUID resume | Advisory: native tools removed, strict empty MCP configuration, safe/restricted mode, permission prompts denied | Requires an upstream CLI supporting these flags; older versions fail rather than dropping safeguards |
| MiniMax API | Engine-owned local UUID and full saved transcript; no fabricated server-side session | Structured tool requests returned to engine; adapter executes no tools | Non-streaming HTTP response normalized into events; token/output/time bounds; no automatic retries |

Both CLI adapters require explicit `native_agent_access`. This acknowledges that
upstream authentication, managed settings, and native process behavior are outside
our scoped-tool implementation. Codex's native sandbox is retained, never bypassed.
Its read-only mode is not a secret-denial mechanism. Claude's current restrictions
follow the [official CLI reference](https://code.claude.com/docs/en/cli-reference).
No adapters silently select permission bypass flags or alter saved preferences.

CLI execution goes through the existing 4.3.0 process supervisor, including Unix
process groups and native Windows Jobs. Timeout/cancellation requests trigger owned
process cleanup. A cleanup timeout is a failure, not a successful cancellation claim.
On Windows, use native CLI executables where arguments contain quotes; arbitrary npm
`.cmd` shims cannot safely represent every prompt/configuration argument.

MiniMax cancellation closes the client transport. It cannot revoke a request already
received by the service or guarantee that billing stops. Its socket operations have a
bounded timeout; a cancelled in-flight worker may take that timeout to finish. CLI
budgets must likewise not be advertised as hard spending limits. The engine must
keep provider-call approval and accounting separate from estimated costs.

## Events and internal transcript

`ProviderRegistry.invoke(id, request)` returns status, visible output, exact session
ID, usage, tool requests, normalized events, and sanitized errors. Status is one of
`completed`, `failed`, `cancelled`, `timeout`, or `tool_calls`.

MiniMax also returns `message` and `history` for **internal transcript replay only**.
Keep the complete provider assistant message, including opaque reasoning fields and
tool-call IDs, followed by matching `role: tool` responses. This follows MiniMax's
multi-turn protocol. Never render opaque reasoning fields in the dashboard/event
stream. Resuming a local MiniMax session without its saved transcript fails instead
of silently starting over. A response/tool call is not proof that a command ran or
that a patch was applied; only trusted local execution supplies that evidence.

## Controlled project tools

`ScopedTools(project, allowed_operations, approved_commands)` exposes only:

- `list_directory`, `read_file`, and literal `search` within the selected project.
- `patch` with an exact expected SHA-256 and one unique old-text match; new files
  require `sha256: "absent"` and empty `old` text, and publish atomically without overwrite.
- `run_command` by a user-approved command name; model arguments cannot replace
  its argv, timeout, or project-relative working directory.
- `git_diff` for existing permitted files, with external diff/text conversion
  disabled. Deleted and sensitive files are deliberately excluded.

Every call checks operation authorization. Paths reject traversal, Windows device
names/alternate streams, symlinks/junctions/reparse points, foreign ownership, and
unsafe writable paths. Reads reject hard links, non-regular files, oversized files,
known credential paths, and recognizable secret content. Search/file/output counts
are bounded. Atomic patches preserve file security metadata and reject stale input.

These are conservative filters, not a universal secret detector: an arbitrary secret
hidden in an innocently named source file may be unrecognizable. Command approval
is approval of the exact program and arguments, including their behavior; the
process supervisor contains lifetime but is **not an OS filesystem sandbox** for
that approved program. The engine must describe this scope before granting command
or native-agent access. No tool can approve sharing, costs, other commands, or itself.

## Verification

`python3 tests/test_v5_providers.py` exercises controlled protocol responses, no-key
configuration, redirect rejection, exact session construction, tool-call handoff,
full MiniMax transcript continuation, active cancellation/timeout under the actual
process supervisor, path/secret denial, stale patches, and exact command approval.
The tests never call a paid API or require Claude/Codex authentication. Passing mocks
verify adapter behavior, not upstream account access or real model capabilities.
