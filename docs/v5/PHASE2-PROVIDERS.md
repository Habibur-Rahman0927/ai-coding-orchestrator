# Phase 2 credentials and provider diagnostics

## Credential boundaries

Only application-owned MiniMax credentials are managed. Codex/Claude authentication
remains in their native CLIs. No account login, logout, credential copying, or real
credential write was performed during implementation.

The provider configuration accepts `credential_mode`:

- `os`: macOS Keychain via Security.framework, Windows Credential Manager via
  `CredReadW`/`CredWriteW`, or Linux Secret Service via `secret-tool`.
- `session`: explicitly selected process memory, shared by interfaces using the
  same database in that process. A backend restart discards it.
- `environment`: explicitly configured `api_key_env` variable name. The launching
  environment owns its value; removing an application credential cannot unset a
  variable in a parent shell. Unset it there and restart if removal is intended.

The OS credential namespace includes the selected database identity so separate
application stores do not accidentally share credentials. The database stores only
mode/presence metadata and a revision timestamp. Availability checks do not read
OS secrets or claim that the vault is unlocked. OS access may request normal
system authorization. Failure never falls back silently to plaintext storage.

Add/replace/remove requires an explicit authenticated-user action. Native framework
calls keep secret values out of process arguments. Secret Service receives the
secret over stdin, with stderr suppressed. Secrets are never returned by status,
written to SQLite, or included in diagnostics. OS storage adapters have automated
mock tests; actual macOS vault writes/removal, Windows vault operations, and Linux
Secret Service integration still need their native, explicitly authorized checks.

## Diagnostics

`Diagnostics.local(provider)` distinguishes missing executable, configuration,
local authentication, compatibility, historical verification, and usage restriction.
Native status output is reduced to states/version; it is not retained or displayed.
The actual local inspection found Codex `0.171.0-alpha.13` and an authenticated
native login, no Claude executable on this PATH, and no MiniMax configuration in
an isolated clean test database. None of those is a live connection verification.

Claude's current [official CLI reference](https://code.claude.com/docs/en/cli-reference)
confirms the adapter's restricted/safe modes and denied unattended permissions.
The diagnostic requires at least 2.1.259 because the permission-prompts control
was introduced there. Older installations are reported as incompatible rather
than silently dropping security flags. Installed Codex exec/resume/login help was
inspected locally; native defaults are inherited and no permission bypass is used.

MiniMax uses the fixed independent HTTPS endpoint documented by its
[official OpenAI-compatible API](https://platform.minimax.io/docs/api-reference/text-openai-api).
An explicit model is required. No model discovery or remaining subscription quota
is invented. Provider usage normalization preserves original counters and adds
input/output/cached-input/reasoning fields where those are reported.

## Explicit live-test contract

`Diagnostics.plan(provider, resume=False)` explains the exact test. A normal test
makes one request in a new temporary Git repository; optional exact-session resume
makes two. It sends a fixed diagnostic prompt, no registered-project content, no
file tools, and a small output request. Native CLI access is a separate consent
because upstream configuration/managed behavior is outside controlled tools.

`Diagnostics.live` requires a provider-specific confirmation, exact maximum call
count, and native-access consent for CLI providers. It must only be exposed to a
trusted human route, never an agent/MCP approval tool. Output caps are requested
where supported; CLI quota/cost cannot be guaranteed by this wrapper.

Cheap dashboard summaries use a five-minute redacted local cache and historical
verification metadata; they spawn no CLI process and read no OS secret.

Records contain statuses, actual session identifiers, reported usage, timestamps,
and visible event types. They exclude model text, opaque reasoning, credentials,
and raw native diagnostics. Successful mocked tests never earn the live verified
badge. A changed provider config/credential revision invalidates its verification
fingerprint. A historical successful test does not guarantee current quota or
service availability.

Error categories include authentication, usage limit, network, context limit,
permission denial, timeout, cancellation and incomplete output. Category messages
are fixed/redacted; ordinary provider content cannot grant additional permissions.
The optional event callback emits only normalized visible events, excluding opaque
transcript/history, and callback failure cannot grant authority or change outcomes.

## Recorded checks

- Credential/diagnostic tests: 16 passed on macOS; mocked vaults/transports.
- Existing provider/tool tests: 18 passed, including real supervised mock processes.
- Actual local version/auth-status inspection: completed, no model request.
- Live authenticated model calls, native credential CRUD and billing: not tested.
