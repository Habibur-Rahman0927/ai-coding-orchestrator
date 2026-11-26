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
  sharing/file scopes and optional usage limits. Approval also authorizes the AI
  to choose and run commands for this project task. Commands execute on your machine
  from the project directory; that directory is not a process sandbox.

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

Open **Settings** in the Ask composer to change **Model** and **Reasoning effort**.
Settings starts collapsed; its summary shows your selection. **Done** returns focus
to the message box. The conversation has its own scroll area so the composer stays
within reach. Provider default
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

## Extension-style chat and task teams

The Chat page has a compact project/agent toolbar, New chat and History, one
scrolling conversation/activity pane, and a persistent composer at the bottom.
Cmd+Enter (Mac) or Ctrl+Enter sends the current composer; Enter inserts a newline.
Model and effort stay in Settings. Access details and task results can be expanded.

For implementation, choose Build and describe the outcome in the same composer:

- **Auto team** uses the selected agent to implement, run approved tests and review
  in a separate session. After approval, the engine advances the steps itself.
- **Custom team** selects a review agent and optional implementation/review models.
  For example, Codex can implement and MiniMax review, or two different Codex models
  can implement/review. Blank model fields keep provider defaults. Custom model
  access must be supported by the selected provider/account.
- **Plan subtasks** adds a planner that divides the objective into bounded tasks.
  The engine runs each task sequentially with the approved team and separate
  sessions. The implementation model is also used for planning when explicitly set.

Review task displays the chosen team, models, tests and permissions before
Approve & start. Editing the team invalidates that preview. Additional permissions
and unknown execution outcomes still require inspection. This is engine-managed
planning/execution/review, not unrestricted recursive or parallel native CLI
sub-agent spawning. Native provider capabilities and limits still apply.

Team choices stay in the current tab; the accepted workflow records the exact
providers and model overrides durably. Existing Ask model/effort preferences remain
scoped to chat and are not silently reused as Build permissions or settings.

## Compact Build confirmation

Build shows the outcome and selected team in a compact confirmation card.
There is no manual command form. The AI chooses commands needed for implementation
and proposes verification checks. The engine runs those checks and records their
exit codes, then a separate reviewer checks the files and adequacy of verification.
Expected-outcome editing and advanced workflow settings stay collapsed.

New tasks default to no cumulative workspace token, cost, time or provider-call
limit. Optional usage limits lets you choose a preset or custom limits. Provider
charges and quotas still apply; model context, per-call deadlines and loop/retry
safeguards remain. Existing tasks retain their limits. For a stopped task, edit
Usage limits in Tasks, or choose Remove usage limits & resume when budget-exhausted.
Saving limits alone never starts a task. Numeric reservations are not provider billing caps.

If the project has no test setup, the AI can choose another relevant check.
Documentation-only work can use file/diff review with an explicit reason and
no automated tests. The result labels this as review-only; it never says tests
passed when no tests ran. Missing or malformed verification plans trigger a
correction instead of silently completing the task. Older tasks and Advanced
workflows keep their existing exact-command approvals.

For explanations or “what is done / what remains”, use Ask. The confirmation card's
“Just ask · no file changes” retains the prompt and switches modes without sending
it or granting execution permissions.

## Live activity

Each chat answer now includes an Activity timeline: indexing, context preparation,
provider wait, visible command/tool activity when exposed by the provider, response
arrival and completion/failure. The bounded timeline is stored with the answer and
survives reload. Build progress also displays observed provider activity.

This is telemetry, not private reasoning or proof of successful execution.
Tasks show live provider text, command activity, output and recorded exit codes.
MiniMax consumes SSE text/tool streams; Claude partial text events and Codex
visible message updates are supported. Availability depends on what the provider
emits. Reasoning blocks are not displayed, and recognizable secrets are withheld.
The frontend polls active work every 350 ms; this is not an exact mirror of a
provider's extension.

Chat opens at the latest message and follows incoming responses while you are
near the bottom. Scrolling up pauses following; Jump to latest resumes it.

## Chat and task views

Chat shows the selected conversation. Project tasks are available through the
**Tasks** tab above Chat (no separate sidebar destination), with project, status and title filters; old, active or cancelled tasks never
automatically replace the conversation. Starting an approved Build or recovering
its accepted request opens that specific task. the **Chat** tab returns to the
conversation without cancelling any background work.

Chat, Tasks and the Advanced workflow browser have separate selection state.
The Tasks list is scoped to the selected project. Cancelled and completed workflow states take priority over unfinished task
steps when showing progress. Markdown pipe tables render as horizontally scrollable
tables with text-only cells; raw HTML remains inert.

The task view stays within the window: its toolbar and tabs remain visible while
the task pane follows new output. Scrolling up pauses following; Jump to latest
returns to the newest output and resumes following. Chat drafts and conversations
remain separate from task progress when switching tabs.

Token-budget input fields are omitted from the UI; existing configured/default
values are retained. Chat and task progress show per-call token telemetry:
reported input/output counts when available, otherwise a clearly labelled estimate
of visible output (UTF-8 bytes / 4). The displayed tokens/second and tokens/millisecond
are averages over provider-call elapsed time, including waiting/tools, not
instantaneous throughput. Hidden reasoning, tool output and unreported input are
not estimated. Waiting for usage means unknown, not zero. Finished call averages
freeze at the recorded finish time.

## Reading and controlling live work

The task pane prioritizes a single readable timeline of visible agent messages,
commands, command output and file-change events. Output blocks expand naturally
rather than using small nested vertical scroll boxes. Older activity is available
with Show earlier activity. Structured plans are rendered as readable task titles
and descriptions, with the original structured response expandable.

Status, Pause and Cancel stay above the scrolling output. Live file changes can
be expanded to inspect the filtered diff, refreshed approximately every three
seconds while running; concurrent external edits may also appear.

In the approval card, Advanced task options includes both Reviewer and Reviewer
model (provider default, suggested models, or a custom model ID). Changing provider
resets the reviewer model. Editing a model regenerates the proposal before approval.
Cancel closes an unsubmitted preview and keeps the prompt; it does not invoke any
agent. Once a task is running, Cancel task stops that task through the existing
cancellation endpoint.
