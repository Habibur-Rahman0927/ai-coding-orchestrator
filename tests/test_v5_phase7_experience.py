"""Task proposals and navigation must never create permissions or execute providers."""
import unittest
from unittest.mock import Mock
import test_v5_memory as fixtures
from ccx_workspace.experience import preferences, propose
from ccx_workspace.server import Dashboard
from ccx_workspace.store import Store


class ExperienceTests(unittest.TestCase):
    setUp = fixtures.MemoryTests.setUp
    tearDown = fixtures.MemoryTests.tearDown

    def request(self, **changes):
        registry = Mock()
        registry.status.return_value = [{'id': p, 'available': True} for p in ('codex', 'claude', 'minimax')]
        data = {'project_id': self.pid, 'provider': 'codex', 'instruction': 'Explain the project', 'mode': 'solo'}
        data.update(changes)
        result = propose(self.store, registry, data)
        registry.invoke.assert_not_called()
        return result

    def test_proposal_is_read_only_and_does_not_create_work(self):
        dashboard = Dashboard(self.store)
        try:
            before = dashboard.engine.list()
            plan = self.request()
            self.assertEqual(plan['kind'], 'chat')
            self.assertFalse(plan['permissions_granted'])
            self.assertFalse(plan['execution_started'])
            self.assertEqual(dashboard.engine.list(), before)
            self.assertEqual(dashboard.chat.list(), [])
        finally:
            dashboard.close()

    def test_auto_uses_explicit_preset_without_provider_ranking(self):
        self.assertEqual(self.request(mode='auto')['kind'], 'chat')
        plan = self.request(mode='auto', preset='quick_fix', partner='minimax', criteria='Existing tests pass')
        self.assertEqual(plan['workflow']['execution_policy'], 'single_task')
        self.assertEqual(plan['workflow']['providers']['reviewer'], 'minimax')
        self.assertEqual(plan['workflow']['budgets']['max_cost'], 0)

    def test_provider_reference_does_not_authorize_delegation(self):
        self.assertEqual(self.request(instruction='Explain how Claude works')['kind'], 'chat')
        for instruction in ('Use Claude to fix this', 'Ask MiniMax to review this', 'Use Codex and MiniMax together'):
            with self.subTest(instruction=instruction), self.assertRaises(ValueError):
                self.request(instruction=instruction)

    def test_requested_pair_requires_explicit_collaboration_controls(self):
        with self.assertRaises(ValueError):
            self.request(instruction='Use Codex and MiniMax together', partner='minimax')
        value=self.request(instruction='Use Codex and MiniMax together', partner='minimax', mode='collaborate', criteria='Acceptance test passes')
        self.assertEqual(value['kind'], 'workflow')
        with self.assertRaises(ValueError):
            self.request(instruction='Use MiniMax to implement this', partner='minimax', mode='collaborate', criteria='pass')

    def test_invalid_inputs_cannot_weaken_existing_security(self):
        for changes in ({'mode':'approve_everything'}, {'permissions':True}, {'provider':'other'},
                        {'project_id':'missing'}, {'mode':'collaborate','partner':'codex','criteria':'pass'},
                        {'mode':'collaborate','partner':'minimax'}, {'instruction':''}):
            with self.subTest(changes=changes), self.assertRaises((ValueError, KeyError)):
                self.request(**changes)

    def test_unavailable_provider_is_rejected_before_any_work(self):
        registry=Mock();registry.status.return_value=[]
        with self.assertRaises(ValueError):
            propose(self.store,registry,{'project_id':self.pid,'provider':'codex','instruction':'Explain'})
        registry.invoke.assert_not_called()

    def test_preferences_persist_in_database_without_provider_auth_changes(self):
        value=preferences(self.store,{'project':self.pid,'favorite':self.pid,'appearance':'light','agent':'minimax'})
        self.assertEqual(preferences(Store(self.db)), value)
        self.assertEqual(value['agents'][self.pid], 'minimax')
        self.assertEqual(value['recent'], [self.pid])
        self.assertEqual(preferences(self.store,{'project':self.pid})['recent'],[self.pid])
        self.assertEqual(preferences(self.store,{'favorite':self.pid})['favorites'],[])

    def test_simultaneous_preference_updates_do_not_lose_favorites(self):
        import concurrent.futures
        import threading
        gate=threading.Barrier(8)
        def toggle(unused):
            gate.wait(timeout=5)
            preferences(self.store,{'favorite':self.pid})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(toggle,range(8)))
        self.assertEqual(preferences(self.store)['favorites'],[])

    def test_invalid_preferences_are_atomic_and_cannot_set_permissions(self):
        before=preferences(self.store)
        for data in ({'project':'missing'}, {'appearance':'script'}, {'permissions':'all'},
                     {'appearance':'light','agent':'untrusted'}, {'favorite':'missing'}):
            with self.subTest(data=data), self.assertRaises((ValueError,KeyError)):
                preferences(self.store,data)
            self.assertEqual(preferences(self.store),before)

    def test_continue_requires_project_history_and_never_resumes_it(self):
        with self.assertRaises(ValueError):
            self.request(instruction='Continue the previous task')
        dashboard=Dashboard(self.store)
        try:
            flow=dashboard.engine.create(self.pid,'Saved task',['Tests pass'])
            before=dashboard.engine.status(flow['id'])['status']
            plan=self.request(instruction='Continue the previous task')
            self.assertEqual(plan['workflow_id'],flow['id'])
            self.assertFalse(plan['execution_started'])
            self.assertEqual(dashboard.engine.status(flow['id'])['status'],before)
        finally:dashboard.close()


import test_v5_phase2 as wire


class ExperienceHTTPTests(unittest.TestCase):
    setUp=wire.Phase2Tests.setUp
    tearDown=wire.Phase2Tests.tearDown
    request=wire.Phase2Tests.request
    login=wire.Phase2Tests.login

    def test_new_controls_require_authentication_origin_and_session_proof(self):
        unused,headers=self.login()
        for path,body in (('/api/experience',{'appearance':'light'}),
                          ('/api/strategy',{'project_id':self.pid,'provider':'codex','instruction':'Explain'})):
            with self.subTest(path=path):
                self.assertEqual(self.request(path,body)[0],401)
                self.assertEqual(self.request(path,body,{'Cookie':headers['Cookie']})[0],403)
                self.assertEqual(self.request(path,body,dict(headers,Origin='http://evil.example'))[0],403)
                self.assertEqual(self.request(path,body,headers)[0],200)
        self.assertEqual(self.registry.provider.requests,[])


if __name__ == '__main__':
    unittest.main()
