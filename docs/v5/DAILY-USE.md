# Start working with V5

This is a local development candidate, not a signed production release. Live
providers, native platforms and real team adoption still need acceptance.

From an already reviewed source checkout, install for your own user:

```sh
./install.sh
```

Python 3.8+ and Git are required. The installer preserves unrelated launchers and
refuses an occupied installation unless you deliberately upgrade. It downloads no
dependencies or services. There are no third-party Python runtime packages to
isolate. Use trusted system installers for missing Python/Git; no sudo is run.
For downloaded releases, first follow [signature verification](../TEAM-INSTALL.md).
The current development artifact is unsigned.

With the installer-selected bin directory on PATH:

```sh
orchestrator open
```

`open` starts the managed background backend if needed, reuses an existing instance
and opens an authenticated browser. It returns the terminal promptly. Without
installation, use `python3 -B engine/orchestrator.py open` from this checkout.
To stop: `orchestrator stop`. No OS service is registered. An older global launcher
may not support `open`; select the intended source explicitly.

Choose one agent, then preview/register a project or skip it for now. Existing
Codex/Claude sign-in remains with those tools. Detected is not authenticated.
Providers contains secure MiniMax configuration, local diagnostics and explicitly
authorized live tests. No live test runs automatically.

In Chat, choose a project and describe the task:

- **Solo:** a read-only conversation with one selected agent. Start the
  conversation, then explicitly authorize sharing and send.
- **Collaborate:** implementation and independent review with two selected agents.
  Choose a preset, say what must pass, review the exact plan, create it, then grant
  the required scoped permissions and run it.
- **Auto:** your question preset uses Solo; other presets use collaboration. It
  does not choose an unapproved provider, invent rankings or infer a budget.

Quick fix and Review and test skip planning but keep tests and review. Feature
development includes planning. Review and test is an execution workflow, not a
read-only audit: grant only the operations you intend. Use Solo for read-only
questions. Spending defaults remain zero; real calls need configuration and consent.

“Use MiniMax to implement…” and “Use Codex and MiniMax together” are checked against
explicit provider selections. Ordinary provider references grant no permission.
“Continue the previous task” opens saved work for inspection; it never retries
unknown effects or restarts completed work automatically.

Projects offers search, favorites and recent projects. Switching restores only
that project's conversations, without triggering a full index. The last project
and its preferred agent persist in the private database. Sensitive-file exclusions
remain in effect when context is prepared for a task.

Advanced tools exposes Memory, Context Inspector, Sessions and usage. Settings
offers light/dark/system appearance, backup, diagnostics and advanced workflow
defaults. Help explains approvals, recovery and updates. Use Tab/Shift+Tab and the
skip link; browser/IDE shortcuts are not overridden.

Closing the browser does not cancel background work. Return to inspect progress,
or use Pause/Cancel deliberately. Chat responses are not verified implementations.
Completed workflows expose tests and review evidence; failures remain failures.
See [Operations](OPERATIONS.md) for backup recovery and signed updates. A lost
connection leaves a request's outcome unknown: inspect saved state before retrying.

## Small team evaluation

Each developer uses their own local installation, accounts, projects and private
data. Do not share databases, credentials or session files. Share reviewed code and
non-sensitive recommended workflow choices only. No cloud server, Docker, Redis
or PostgreSQL is required.

Before a real pilot, authorize project copies, provider combinations/models and
maximum calls/spend or subscription allowance. Complete live-provider, native-host,
recovery and trusted-signature gates for that scope. Automated fixture results
support local evaluation, not V5_TEAM_PILOT_READY or actual adoption. No real team
feedback or real token savings have been measured.

macOS/Windows launcher code exists; current native acceptance remains pending.
Use [Cross-platform guidance](../CROSS-PLATFORM.md) for paths and PowerShell syntax.
Documented commands are not proof those hosts were tested.
