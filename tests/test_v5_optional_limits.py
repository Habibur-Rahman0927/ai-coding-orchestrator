"""Optional cumulative limits retain explicit provider authorization."""
import unittest
import test_v5_easy_tasks as fixtures

class OptionalLimits(unittest.TestCase):
    setUp = fixtures.EasyTasks.setUp
    tearDown = fixtures.EasyTasks.tearDown
    file = fixtures.EasyTasks.file
    start_body = fixtures.EasyTasks.start_body
    wait = fixtures.EasyTasks.wait

    def test_new_task_defaults_unlimited_and_completes_offline(self):
        data = dict(self.data)
        data.pop('max_cost'); data.pop('max_call_cost')
        proposal = self.app.tasks.preview(data)
        self.assertEqual(proposal['workflow']['budget_policy'], 'unlimited')
        result = self.wait(self.app.tasks.start(self.start_body(proposal))['workflow_id'])
        self.assertEqual(result['status'], 'COMPLETED', result['reason'])
        costs = self.app.engine._approved(result['id'], 'cost')
        self.assertTrue(costs)
        self.assertTrue(all(a['scope']['unlimited'] for a in costs))

    def test_explicit_caps_remain_limited(self):
        proposal = self.app.tasks.preview(self.data)
        self.assertEqual(proposal['workflow']['budget_policy'], 'limited')

    def test_stopped_legacy_task_can_remove_limits_without_running(self):
        engine = self.app.engine
        flow = engine.create(self.pid, 'Example', ['done'])
        engine.approve(flow['id'], 'sharing', {'provider':'codex'})
        engine.approve(flow['id'], 'cost', {'provider':'codex','max_cost':1,'max_call_cost':.1})
        changed = engine.configure_usage_limits(flow['id'], 'unlimited')
        self.assertEqual(changed['status'], flow['status'])
        self.assertEqual(self.registry.calls, [])
        changed.update(tokens_used=10**10, cost_used=10**10, started_at=1)
        self.assertIsNone(engine._budget(changed))
        self.assertIsNone(engine._provider_budget(changed))
        self.assertEqual(engine._approved(flow['id'], 'cost')[-1]['scope'], {'provider':'codex','unlimited':True})
        with self.assertRaises(ValueError):
            engine.configure_usage_limits(flow['id'], 'limited', {'max_cost':1}, -1)
        self.assertEqual(engine.status(flow['id'])['budget_policy'], 'unlimited')
        self.assertTrue(engine._approved(flow['id'], 'cost')[-1]['scope']['unlimited'])
        engine.cancel(flow['id'])
        with self.assertRaises(ValueError):
            engine.configure_usage_limits(flow['id'], 'limited', {'max_cost':1}, .1)

    def test_numeric_approval_does_not_authorize_unlimited_live_calls(self):
        engine = self.app.engine
        flow = engine.create(self.pid, 'Example', ['done'], budget_policy='unlimited')
        engine.approve(flow['id'], 'sharing', {'provider':'codex'})
        engine.approve(flow['id'], 'cost', {'provider':'codex','max_cost':1,'max_call_cost':.1})
        self.registry.offline = False
        self.assertIn('approval', engine._gate(flow,'codex','executor',self.registry))
        engine.configure_usage_limits(flow['id'], 'unlimited')
        self.assertIsNone(engine._gate(engine.status(flow['id']),'codex','executor',self.registry))
        self.assertEqual(self.registry.calls, [])

    def test_budget_exhausted_task_resumes_after_explicit_removal(self):
        proposal = self.app.tasks.preview(dict(self.data, max_tokens=128))
        result = self.wait(self.app.tasks.start(self.start_body(proposal))['workflow_id'])
        self.assertEqual(result['status'], 'BUDGET_EXHAUSTED')
        identifier = result['id']
        calls = len(self.registry.calls)
        self.app.dispatch('POST', '/api/workflows/'+identifier+'/limits',
                          {'confirmed':True, 'policy':'unlimited'})
        self.assertEqual(len(self.registry.calls), calls)
        self.app.dispatch('POST', '/api/workflows/'+identifier+'/retry', {})
        result = self.wait(identifier)
        self.assertEqual(result['status'], 'COMPLETED', result['reason'])
