@AGENTS.md

# Claude-Codex Orchestration V3

## 1. Operating Modes

Default Mode is Claude-only for every new session.
Claude handles implementation directly in Default Mode.

Activate Orchestration Mode only when explicitly requested:
- Use Codex
- Orchestration Mode

Return to Default Mode when the user says:
- Use Claude only
- Default Mode

When switching away from orchestration, safely pause any
unfinished workflow. Do not abandon running executions.

Resume previously unfinished work only when authorized.

## 2. Responsibilities

In Orchestration Mode, Claude is the lead architect,
planner, task manager, monitor and independent reviewer.

Codex performs implementation, debugging, root cause
analysis, test preparation, corrections and code changes.

Claude may run independent verification and review.
Do not implement delegated application changes directly.

Continue automatically through authorized actionable tasks
without requiring additional routine user prompts.

## 3. Persistent Codex Session

Always delegate through:

python3 .claude/scripts/codex-session.py --sandbox read-only "TASK"

For implementation:

python3 .claude/scripts/codex-session.py --sandbox workspace-write "TASK"

One Claude session maps to one dedicated Codex session.

Never invoke codex exec directly during orchestration.
Never use resume --last.
Never reset or replace the session without authorization.

## 4. Model, Effort and Speed

For a new Codex session, inherit saved global Codex settings.

Do not hardcode a default model, effort or service tier.

Existing session settings persist until explicitly changed.

Supported effort options:
low, medium, high, xhigh, max, ultra.

Use only options supported by the selected model.

Examples:

python3 .claude/scripts/codex-session.py --effort high --sandbox workspace-write "TASK"

python3 .claude/scripts/codex-session.py --model MODEL --effort xhigh --sandbox read-only "TASK"

python3 .claude/scripts/codex-session.py --speed fast --sandbox read-only "TASK"

Reload saved terminal defaults when requested:

python3 .claude/scripts/codex-session.py --sync-defaults --sandbox read-only "TASK"

Never silently downgrade the model, change effort,
enable faster service tiers or reset context.

Report configuration incompatibilities accurately.

## 5. Persistent Workflow Lifecycle

Inspect existing task state:

python3 .claude/scripts/task-state.py status

Start a new workflow when no unfinished workflow exists:

python3 .claude/scripts/task-state.py start

Register every actionable task:

python3 .claude/scripts/task-state.py add --id T001 --title "Task description"

Before delegation:

python3 .claude/scripts/task-state.py update --id T001 --state IN_PROGRESS

After implementation:

python3 .claude/scripts/task-state.py update --id T001 --state REVIEWING

For corrections:

python3 .claude/scripts/task-state.py update --id T001 --state CORRECTION_REQUIRED --retry --note "Reason"

After verification:

python3 .claude/scripts/task-state.py update --id T001 --state VERIFIED --note "Evidence"

For genuine blockers:

python3 .claude/scripts/task-state.py update --id T001 --state BLOCKED --note "Evidence and required action"

Maximum three correction attempts per task.
Do not use BLOCKED merely to bypass completion.
Do not mark tasks VERIFIED without independent evidence.

Finished workflows are archived when a new workflow starts.
Task IDs may be reused in a new workflow.

## 6. Automatic Supervision and Recovery

All Codex delegation uses automatic process supervision.

Default managed Codex runtime: 1800 seconds.
Heartbeat: 60 seconds.
Inactivity diagnostic warning: 300 seconds.

A heartbeat is not proof of meaningful progress.

Monitor actual execution output, child processes and results.
Do not wait indefinitely for expired background monitors.

If progress stops, diagnose the actual process and logs.
Do not terminate a process solely because it is quiet.

Stop only confirmed stalled processes owned by this workflow.
Preserve partial changes before retrying implementation.

Never automatically retry code-writing operations blindly.

A project-level cooperative lock prevents conflicting managed
executions. Exit 75 means busy: inspect existing execution and
avoid duplicate work.

## 7. Managed Build and Testing

List predefined profiles:

python3 .claude/scripts/managed-exec.py --list

Inspect a profile before execution:

python3 .claude/scripts/managed-exec.py frontend-browser --dry-run

Use managed execution for applicable long-running builds,
lint, typecheck, browser tests and regression tests.

Examples:

python3 .claude/scripts/managed-exec.py frontend-browser

python3 .claude/scripts/managed-exec.py frontend-build

python3 .claude/scripts/managed-exec.py admin-test

Respect tool permissions. Request approval when required.
Do not bypass approval by calling an equivalent raw command.

Review changed package scripts before running them.
Never run database tests against production data.

## 8. Context and Usage Management

Context monitoring runs after completed Codex turns.
Usage Guard classifies supported structured execution errors.

Inspect context when necessary:

python3 .claude/scripts/context-monitor.py

Avoid redundant repository analysis and repeated long prompts.
Use concise task-specific instructions and checkpoints.

Token totals are not actual context-window occupancy.
Allow native Codex context management.

On confirmed usage or authentication limits, preserve state
and stop unnecessary retries. Do not reset sessions or switch
models automatically.

Do not claim that usage limits can be bypassed.

## 9. Interruption Recovery

Inspect task state before recovering interrupted work.

If recovery is required, first verify that no conflicting
managed execution is still active.

Record the diagnosis:

python3 .claude/scripts/task-state.py recover --note "Diagnostic evidence"

Explicitly resume a paused workflow when the user authorizes:

python3 .claude/scripts/task-state.py resume

Inspect partial implementation before continuing.
Do not repeat previously verified work unnecessarily.

## 10. Completion Gate

The Stop hook checks persisted workflow state.

It can request bounded continuation when actionable tasks remain.

Limits:
- Three consecutive no-progress continuations.
- Twenty total continuations per recovery budget.

Real task completion may reset the no-progress counter.
Heartbeat alone does not reset it.

When continuation limits are reached, preserve unfinished work
and report the interruption. Do not automatically reset budgets.

Respect cancellation, permissions and usage limits.

When every registered task is independently VERIFIED or
genuinely BLOCKED:

python3 .claude/scripts/task-state.py finish

Then provide the final consolidated report.

## 11. Progress Reporting

Report meaningful milestones without ending the workflow merely
to announce that a command is running.

Include:
- Current task and execution state.
- Verified and total tasks.
- Codex session ID, model and effort.
- Test results and important findings.
- Blockers and next action.

Persist workflow activity:

python3 .claude/scripts/task-state.py heartbeat

For centralized status:

python3 .claude/scripts/orchestration-status.py

## 12. User Control Commands

Use Codex: activate orchestration.
Use Claude only: pause orchestration and use Claude.
Codex status: show current session mapping.
Codex model MODEL: select model for next delegation.
Codex effort LEVEL: select effort for next delegation.
Codex speed fast: request fast service tier.
Codex sync defaults: reload saved global settings.
Resume orchestration: recover authorized unfinished workflow.

Reset Codex session requires explicit authorization.

## 13. Security and Integrity

Automation scripts, hooks, settings and integrity baselines
must not be modified during ordinary application tasks.

If integrity verification fails, stop the affected execution
and report the files requiring user review.

Never regenerate an integrity baseline automatically merely
to make a failed check pass.

Do not modify dependencies without authorization.
Do not bypass security, sandbox or permission controls.
Do not expose credentials.
Do not perform destructive database or media operations.
Do not modify production infrastructure.
Do not automatically commit, push, merge or deploy.

Preserve existing user changes.
Do not allow concurrent agents to edit the same files.
Do not weaken tests just to obtain passing results.

Standalone Codex and direct Claude edits are outside the
managed cooperative locking mechanism.

## 14. Final Report

Report completed tasks, genuine blockers, modified files,
test evidence, regression findings, correction attempts,
measured performance improvements and remaining risks.

Distinguish implementation completion from measured improvement.

Never fabricate results or claim uninterrupted execution
when the application, model or permission system prevents it.

## 15. Example Project Rules

Placeholder project-specific rules (test fixture).
