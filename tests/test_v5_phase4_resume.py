"""Pause/resume cancellation checkpoints; no live provider requests."""
import threading
import unittest

import test_v5_workflows as fixtures
from ccx_workspace.store import Store
from ccx_workspace.workflows import WorkflowEngine


class ResumeCancelledTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    create = fixtures.WorkflowTests.create
    authorize = fixtures.WorkflowTests.authorize

    def pause_during(self, role, mutate=False, native_access=False, budgets=None):
        identifier = self.create(task=role != 'planner', budgets=budgets)
        self.authorize(identifier)
        if native_access:
            provider = 'codex' if role == 'executor' else 'claude'
            self.engine.approve(identifier, 'native_agent_access', {'provider': provider})
        registry = fixtures.MockRegistry()
        original = registry.invoke
        entered = threading.Event()
        interrupted = []
        calls = []
        def invoke(provider, request):
            calls.append(request['role'])
            if request['role'] == role and not interrupted:
                interrupted.append(True)
                if mutate:
                    (self.project / 'effect.txt').write_text('one uncertain local effect')
                entered.set()
                if not request['cancel_event'].wait(5):
                    raise RuntimeError('Cancellation barrier expired')
                return {'status': 'cancelled', 'output': '', 'usage': {}}
            return original(provider, request)
        registry.invoke = invoke
        outcome = []
        worker = threading.Thread(target=lambda: outcome.append(self.engine.run(identifier, registry)))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            self.engine.pause(identifier)
            worker.join(10)
            self.assertFalse(worker.is_alive())
            self.assertEqual(outcome[0]['status'], 'PAUSED')
        finally:
            worker.join(10)
        self.engine = WorkflowEngine(Store(self.store.path))
        return identifier, registry, calls

    def test_cancelled_planner_resumes_with_new_call_not_cached_cancellation(self):
        identifier, registry, calls = self.pause_during('planner')
        self.engine.resume(identifier)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result['reason'])
        self.assertEqual(calls.count('planner'), 2)
        self.assertEqual(calls.count('executor'), 1)
        self.assertEqual(result['provider_calls'], 4)
        self.assertTrue(any(c['event'] == 'READ_ONLY_CANCELLED_ACTION_CONSUMED' for c in self.engine.checkpoints(identifier)))

    def test_cancelled_reviewer_resumes_without_reexecuting_implementation(self):
        identifier, registry, calls = self.pause_during('reviewer')
        executor_sessions = [s for s in self.engine.status(identifier)['sessions'] if s['role'] == 'executor']
        self.engine.resume(identifier)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result['reason'])
        self.assertEqual(calls.count('reviewer'), 2)
        self.assertEqual(calls.count('executor'), 1)
        self.assertTrue(all(s in result['sessions'] for s in executor_sessions))

    def test_resume_does_not_reset_cancelled_call_budget(self):
        identifier, registry, calls = self.pause_during('planner', budgets={'max_provider_calls': 1})
        self.engine.resume(identifier)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'BUDGET_EXHAUSTED')
        self.assertEqual(result['provider_calls'], 1)
        self.assertEqual(calls.count('planner'), 1)

    def test_cancelled_executor_requires_recovery_even_without_visible_change(self):
        identifier, registry, calls = self.pause_during('executor')
        with self.assertRaises(PermissionError):
            self.engine.resume(identifier)
        self.assertEqual(self.engine.status(identifier)['pending_actions'][0]['state'], 'UNCERTAIN')
        self.engine.run(identifier, registry)
        self.assertEqual(calls.count('executor'), 1)

    def test_cancelled_planner_with_changed_snapshot_requires_recovery(self):
        identifier, registry, calls = self.pause_during('planner', mutate=True)
        with self.assertRaises(PermissionError):
            self.engine.resume(identifier)
        self.assertEqual(self.engine.status(identifier)['pending_actions'][0]['state'], 'UNCERTAIN')
        self.assertEqual(calls.count('planner'), 1)
        self.assertEqual((self.project / 'effect.txt').read_text(), 'one uncertain local effect')

    def test_cancelled_native_access_is_not_assumed_side_effect_free(self):
        identifier, registry, calls = self.pause_during('planner', native_access=True)
        with self.assertRaises(PermissionError):
            self.engine.resume(identifier)
        self.assertEqual(calls.count('planner'), 1)
        self.assertTrue(self.engine.status(identifier)['pending_actions'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
