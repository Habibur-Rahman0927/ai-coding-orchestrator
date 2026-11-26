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

Chat is the home screen. Primary navigation is Chat, Projects and Settings;
Providers, Workflows, Approvals, Memory, Context, Sessions and usage remain under
Advanced tools, with existing deep links preserved.

If needed, connect one agent and preview/register a Git project directly in Chat.
Provider setup offers installation/login instructions and a local Check again
action. Existing Codex/Claude sign-in remains with those tools. Installed is not
live-verified; no paid test, installer or login command runs automatically.
MiniMax keeps its secure credential configuration. Registration returns directly
to Chat without a separate onboarding completion page.

## Ask or Build

Choose a project and agent, then write in the single composer:

- **Ask** is the default. **Send** creates a conversation when necessary and sends
  the first message in one action. The notice beside Send explicitly describes
  sharing and provider usage; each send authorizes that message only. It does not
  authorize implementation. Native CLI access may exceed the filtered context.
- **Build** uses **Review task → Approve & start**. Preview is local and free of
  model calls. One approval card shows the project, editable acceptance criteria,
  exact test commands, sharing/file scopes and total/per-call usage reservations.
  Initial reservations are zero; set them explicitly before live work can start.
  They control the engine, not a guaranteed native CLI billing cap.

Build defaults to direct implementation, tests and a separate review session with
one selected provider. It does not require a second provider account. Separate
sessions are not different models. Advanced task options let you select a second
reviewer or enable multi-step planning. Existing test/review completion gates are
unchanged; the interface never calls an unverified implementation complete.

The last approved command configuration and usage values become suggestions for
that project, not permission grants for future tasks. Each new task still needs
Approve & start. A package.json test script can suggest `npm test`; review it as
untrusted repository code before approval. When no command is known, fill the
executable and one argument per line in the same card. Preview never executes a
command or guesses a no-op test. Additional permission scopes require explicit
approval and appear beside progress.

Task previews expire after 15 minutes. Edits to the task card automatically
produce a new local preview. Project content, exclusions or provider settings
changing before start require another review. Double-clicks and repeated requests
with the same submission identity do not launch duplicate work. Request identities
are saved before launch; after an ambiguous restart, inspect rather than rerun.

## Progress, recovery and preferences

Progress and results appear in Chat: Working → Testing → Reviewing → Done or
Needs attention. Use Pause/Cancel explicitly. Completion shows test/review evidence,
changed files and a bounded text diff against the task's starting state. Existing
changes are listed separately. Changes made concurrently by another person/tool
cannot be attributed to the agent; sensitive, binary and oversized diffs are omitted.
Older workflows without a recorded task baseline say so rather than inventing one.

The selected project, agent and conversation persist privately. Switching projects
restores only that project's conversations, without a full index. Ask/Build defaults
to Ask in a new browser session. Unsaved composer drafts stay in tab memory; errors
preserve them while the tab remains open. Reload restores saved work, not unsent text.
Only opaque pending-request IDs (not source or credentials) go into session storage
so reload can inspect a lost response without resending it. If the server has no
conclusive record, the UI asks you to inspect before deliberately starting anew.

Projects still offers search, favorites and recent projects. Settings contains
appearance, backup, diagnostics and advanced defaults. Use Tab/Shift+Tab and the
skip link; browser/IDE shortcuts are not overridden. Closing the browser does not
cancel background work. See [Operations](OPERATIONS.md) before recovery or upgrades.

## Local validation

The task coordinator has offline tests for atomic approval, stale proposals,
duplicate starts/messages, separate-session review and bounded result comparison:

```sh
python3 -B -m unittest discover -s tests -p test_v5_easy_tasks.py -v
```

Optional Playwright tests use installed Chrome with fresh profiles, temporary
projects and mocked providers:

```sh
python3 -B -m unittest discover -s tests/browser -p test_easy_workspace.py -v
```

Submission-click acceptance is **one** for Ask (formerly create + checkbox + send)
and **two** for a configured Build (formerly review + create + separate permissions
and run). Counts exclude typing, choosing Ask/Build, initial provider setup, and
first-time test/usage configuration. This is interaction evidence, not measured
real-world productivity or token savings. Live provider acceptance remains separate.

## Chat answers, models and effort

Ask renders headings, bold text, lists, inline code, code blocks and HTTP(S) links.
Raw HTML and executable links stay inert text. The prompt includes a bounded
inventory of indexed text files, manifest/README excerpts and retrieved context.
It asks for answers in the user's language with file references, and for explicit
uncertainty when evidence is incomplete. This improves grounding; it does not
verify model claims. “Context supplied” shows excerpts sent, not proof of citation
accuracy. Excluded, sensitive, binary and oversized files are not part of this index.

Use **Model** and **Reasoning effort** beside the Ask composer. Provider default
keeps the provider's configuration. Model choices include the configured model,
local Codex model-cache names when available, and Claude aliases. **Custom model**
accepts an exact model ID. The list does not guarantee account access. Effort
support depends on the model and installed CLI; higher effort may take longer
and consume more allowance. MiniMax effort is disabled because this adapter does
not expose an equivalent setting. No model discovery request is sent to providers.

Selections are saved when sending and restored with the conversation. Each answer
records its requested settings; these are not a claim about the actual model
returned upstream. Changing options keeps the exact conversation session and does
not silently create a new one. These controls apply to **Ask**; Build continues to
use its separately reviewed workflow configuration. Unsaved selections stay in the
tab. Account authentication and provider defaults are not modified.

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
