# Provider usage, caching and session boundaries

Date: 2026-11-25. No live provider request was authorized or made for Phase 5.
The usage-budget question remains pending. Local authentication is not permission to
consume a subscription. Live A/B/C token benchmarks, six-direction provider collaboration,
real user effort and real-project pilot acceptance remain blocked as in Phase 4.

## Official capability review

OpenAI documents nested cached-input usage and distinguishes cache reads/writes from
ordinary input; these counts are not eliminated tokens. The normalizer now retains
nested input-cache and output-reasoning counts when provided. This API documentation
is not proof of a particular Codex CLI session's effective cache policy or occupancy.
[OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)

Anthropic documents separate uncached, cache-read and cache-creation input counts.
For Claude results carrying those fields, normalization retains the components and sums
them into total input only when all components exist. Incomplete totals remain unknown.
No application cache-control option was added to the native Claude CLI.
[Anthropic prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)

MiniMax documents its OpenAI-compatible transport and conversation-history requirements.
The reviewed page did not establish an application-controlled cache mechanism. No cache
parameter, model window, model migration or pricing assumption was invented.
[MiniMax OpenAI compatibility](https://platform.minimax.io/docs/api-reference/text-openai-api)

No provider prices or subscription quotas were inferred. Cache parsing tests use synthetic
usage objects, not observed live cache hits. The tests do not establish real cost savings.

## Request and accounting changes

A configurable `max_request_tokens` (default 32768) bounds the application's estimated
prompt/transcript plus requested output and `context_reserve_tokens` (default 128).
This is a user-configurable local envelope, not a provider-advertised window. Native system
instructions, tool overhead and native history may be opaque. The dispatch journal records
observable prompt/history bytes, output reservation and the estimate's limitations.
An oversized envelope pauses further dispatch with a clear budget reason; no requirement
is silently dropped and no native session is reset.

Input/output components are handled individually. A missing input count no longer becomes
zero merely because output usage was reported. Missing components use explicit local
estimates for workflow accounting; exact reported zero remains reported zero. Cached and
reasoning counts are retained separately and never subtracted from total input/output.
Nonfinite usage is not accepted as a valid reported count.

The usage report groups actual journaled calls by role, counts approval/recovery events,
and reports prepared context/history bytes and scoped read duplication. Prepared bytes
are not proven wire transmission. Native reads/occupancy and actual human effort remain
unknown. Per-role complete totals stay null when any relevant count is missing; partial
reported totals and missing-call counts remain visible.

Comparability now requires recorded permission/verification/output-limit contracts and
matching actual role/provider/model assignments. A nominal output budget is insufficient:
the contract includes the dispatched cap after budget clipping. Missing/incompatible
contracts withhold reduction claims. Native reasoning/speed settings still prevent a
strict live comparability label until independently recorded. Different routing policies
are measured as synthetic mechanisms, not silently called equivalent live configurations.

## Deliberately retained session behavior

Exact project/workflow/task/role/provider sessions and explicit handoff approvals remain.
No `resume --last`, cross-provider native-transcript copying, automatic rotation, native
session deletion, or local-cache-as-provider-memory assumption was introduced. Stateless
requests still receive necessary context. Local package ID reuse is not token elimination.
Incremental transfer and session rotation are deferred until adapter acknowledgements and
observable occupancy support a safe measured policy. No summarization/model/embedding
calls were added to indexing, retrieval, monitoring, or memory maintenance.

To unblock live measurement: authorize providers, maximum calls and spend/subscription
allowance. For MiniMax, specify the model and secure credential reference; never paste
keys. All six directions remain unverified live; Claude availability and each intended
native platform require separate checks. Client-project work additionally needs explicit
workspace/task authorization after applicable entry gates pass.
