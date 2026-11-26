# Daily use

AI Orchestrator is a local workspace for a solo developer: choose a project,
write a request, watch the work, and inspect the result. One connected provider
is enough. A different reviewer provider or model is optional.

## Open and connect

Run `orchestrator open` from a terminal after installing, or use
`python3 -B engine/orchestrator.py open` from the checkout. The managed local
service opens an authenticated browser. Closing the browser does not cancel work.

Choose a local Git repository and a provider. Existing Codex/Claude login stays
with the CLI; MiniMax uses its configured API credential. Local detection does
not prove authentication or available quota. No paid connection test runs during
setup. Use Connection help when a provider is missing.

## Send a request

Workspace contains Chat and Tasks. Chat is the main work surface; Tasks is the
project's searchable work list, not another task-creation form.

Coding is the initial mode. On the first coding Send, choose **Allow project &
send** to save access for the displayed repository and providers. This allows
future explicit coding requests to share project context, edit files, and run
agent-chosen commands using your provider allowance. CLI permissions still apply;
the working directory is not a process sandbox. Existing projects are not trusted
automatically. A new provider or changed repository/exclusions needs fresh access.

After setup, coding takes one Send. Choose **Ask · no changes** for a read-only
question; Ask does not acquire write permission. You can instead select **Review
this task only** on the access card for a one-task approval without saving access.
Cancel on that card closes the preview without running a provider.

Open the small Settings control beside the composer for model, reasoning effort,
reviewer/model, optional planning and workspace usage limits. Settings are saved
per project and provider. Provider defaults apply when no override is selected.
Workspace caps are off by default; provider quotas, model context limits and
execution safeguards remain. Estimates/reservations are not provider billing caps.

Use **Project access → Revoke project access** in composer Settings to block
future direct starts, including queued requests under that grant. Revocation does
not stop an already executing task; use its Cancel control to stop it deliberately.

## Conversation and follow-ups

Coding requests, visible agent activity and results stay in their conversation.
Send a follow-up from the same composer. It receives bounded conversation and
prior verification references, not an invented continuation of another provider's
native session. Switching providers keeps the conversation while preserving
separate provider-native read-only sessions. Provider context/session limits still apply.

Each project restores its conversation and agent. Unsent drafts and agent choices
are stored in the private local workspace database; they can therefore appear in
workspace backups. Drafts are not sent to a model until Send. Do not put credentials
in the composer. Project switching never copies another project's draft/context.

Task links open older work; **Open conversation** returns from Tasks to its original
conversation. Older unlinked workflows remain available in Tasks and Developer
tools; no conversation relationship is guessed.

## Queue and recovery

Only one admitted coding task writes to a canonical repository at a time. Further
requests queue, including follow-ups submitted while work is running. They do not
interrupt or inject text into the active provider session. Different repositories
can use the existing four-runner capacity.

Queued work is persisted. Before its first execution, the engine rechecks project
access/provider configuration and captures a fresh comparison baseline. Cancel a
queued task to prevent it from running. Paused or unresolved work holds that
repository's queue until resumed, resolved or cancelled.

Reload/reconnect inspects persisted request identity rather than resending. Work
that was admitted before a crash is not automatically replayed. Inspect its
changes and use the existing recovery/Resume controls. A task whose outcome is
unknown must be reconciled before retry. The queue is admission for dashboard
workflows; it does not isolate an external editor or another process changing the
same repository.

## Read progress and results

The main timeline shows provider-visible updates, commands, output and file-change
notifications. Long command output expands on request. Updates fetch only new or changed events; stable events retain their
DOM nodes during updates. Latest output follows automatically while you are at
the bottom; scrolling up pauses following. Use Jump to latest to return.

Pause/Cancel stay available while work runs. A quiet period means no new visible
provider output, not proof that the model is idle. Private model reasoning is not
available. Token meters distinguish reported usage from visible-text estimates;
rates are elapsed-time averages, not instantaneous billing speed.

Results include changed files, a filtered diff, test/review evidence and completion
limitations. Review-only work is labeled as having no automated tests. Changes
from other tools may appear in a comparison; the diff is not proof of authorship.
Existing edits are shown separately. Completed task comparisons are saved so later
tasks do not change earlier results. If project scope changes, the saved comparison
is hidden rather than exposing newly excluded content. No automatic commit, push or blanket rollback
is performed. Inspect the evidence before committing through your usual Git tools.

## Settings and advanced tools

Primary navigation is Workspace, Projects and Settings. Settings → Developer tools
contains Providers, Memory, Context, Sessions, Workflows, Approvals, Activity and
Help. Existing deep links remain valid. These tools are optional for daily work.

Settings also offers appearance, diagnostics and private database backups. Backups
do not include repository files or provider credentials. See [Operations](OPERATIONS.md)
for recovery. For updates, stop the service, upgrade from your reviewed checkout,
and reopen. See [installation](../../README.md#installation).

## Validation status

Automated offline tests exercise saved access, idempotency, queue persistence,
revocation, project isolation and browser flows with deterministic providers. They
do not certify live Codex/Claude/MiniMax behavior or provider billing. Any paid live
evaluation requires separate explicit authorization. This remains a development
candidate; see [release scope](RELEASE-CANDIDATE.md).
