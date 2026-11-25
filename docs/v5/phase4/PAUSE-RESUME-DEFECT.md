# Cancelled planner/reviewer checkpoint blocked Resume

Severity: **HIGH** — broken pause/resume user journey. Discovered during Phase 4 real-browser preflight; reproduced independently with deterministic providers and actual workflow persistence.

## Reproduction and cause

Start an empty workflow, pause while its planner call is waiting, and let the provider return `status=cancelled`. The worker exits `PAUSED`. Reopen the controller, Resume, and Run. Before correction the result becomes `BLOCKED` with `Provider cancelled`; the planner call count remains one.

`_invoke` durably records a returned provider response as a completed action even when its response status is cancelled. Pause leaves this action unconsumed. The subsequent run replays that cached cancelled response instead of continuing planning. The same condition affects reviewer calls.

Five initial regression cases failed: scoped planner/reviewer continuation, and explicit uncertainty handling for cancelled executor, changed-source planner and native-access planner calls. Original failing log is `/tmp/ccx-phase4-resume-before.log`; the retained copy uses a relative workspace marker only.

## Targeted correction

`WorkflowEngine.resume` now reconciles completed, unconsumed cancelled responses in its transaction:

- A planner/reviewer call is eligible for a new attempt only when its recorded operations are limited to scoped read-only tools and its before, after and current project hashes all match.
- Its original action is retained and marked consumed with a checkpoint. Provider sessions, usage accounting and call budgets remain intact. The explicit Resume permits a new call through the normal authorization/budget gates.
- Executor calls, native-agent access, mismatching snapshots or insufficient scope evidence become `UNCERTAIN`. Existing explicit recovery approval is required before any retry. A cancellation response is not proof that unknown side effects are safe to repeat.

No runtime history is deleted, no provider permission is added, and no immutable release payload is changed. The correction does not claim that broad native-agent cancellation can resume automatically without reconciliation.

## Verification scope

`tests/test_v5_phase4_resume.py` covers successful planner/reviewer continuation, no repeated implementation, retained call accounting, budget exhaustion after a cancelled call, and recovery refusal for executor/native-access/changed-source uncertainty. Fixtures reopen Store/WorkflowEngine before resuming and use actual SQLite state.

The test provider only waits for the engine cancellation signal and returns a deterministic cancellation result; no paid provider or native agent runs. Real-browser coverage complements these engine tests but does not independently establish live-provider cancellation behavior.

Observed results after correction: 6/6 new tests passed (6.765 seconds); 21/21 workflow tests passed (6.108 seconds); 21/21 Phase 2 reliability tests passed (3.252 seconds); 4/4 process-cancellation tests passed (3.744 seconds). Retained logs: `resume-after.log`, `resume-workflows.log`, `resume-reliability.log`, and `resume-cancel.log`. Independent review is tracked separately.
