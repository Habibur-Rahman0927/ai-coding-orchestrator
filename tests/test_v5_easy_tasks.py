"""Single-approval tasks with real storage and deterministic offline providers."""
import concurrent.futures
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest import mock
import uuid
import test_v5_memory as fixtures
from test_v5_workflows import MockRegistry
from ccx_workspace.server import Dashboard
from ccx_workspace.settings import save_setting, setting
from ccx_workspace.experience import preferences


class Registry(MockRegistry):
    def status(self):
        return [{'id': name, 'available': True} for name in ('codex', 'claude', 'minimax')]

    def get(self, name):
        registry = self
        class Provider:
            def status(self):
                return {'available': True, 'capabilities': {'scoped_tools': True}}
            def execute(self, request):
                registry.calls.append((name, request.role))
                yield {'type': 'session', 'session_id': request.session_id or str(uuid.uuid4())}
                yield {'type': 'text', 'text': 'Read-only answer'}
                yield {'type': 'completed'}
        return Provider()


class EasyTasks(unittest.TestCase):
    def setUp(self):
        fixtures.MemoryTests.setUp(self)
        self.registry = Registry(tool=True)
        self.file('app.txt', 'bad')
        self.file('check.py', 'from pathlib import Path\nassert Path("app.txt").read_text()=="good"\n')
        self.app = Dashboard(self.store, registry=self.registry)
        self.data = {'project_id': self.pid, 'provider': 'codex', 'instruction': 'Fix app.txt',
                     'criteria': 'app.txt contains good', 'max_cost': 1, 'max_call_cost': .1,
                     'commands': [{'name': 'tests', 'argv': [sys.executable, '-B', 'check.py'], 'cwd': '.', 'timeout': 10}]}
    file = fixtures.MemoryTests.file

    def tearDown(self):
        self.app.close()
        fixtures.MemoryTests.tearDown(self)

    def preview(self, **changes):
        return self.app.dispatch('POST', '/api/tasks/preview', dict(self.data, **changes))

    def start_body(self, proposal):
        return {'proposal_id': proposal['proposal_id'], 'revision': proposal['revision'],
                'confirmed': True, 'idempotency_key': uuid.uuid4().hex}

    def wait(self, workflow):
        deadline = time.time() + 15
        while workflow in self.app.jobs and time.time() < deadline:
            time.sleep(.05)
        self.assertNotIn(workflow, self.app.jobs)
        return self.app.engine.status(workflow)

    def test_rust_checks_are_suggested_without_execution(self):
        self.file('backend/Cargo.toml', '[package]\nname="sample"\nversion="0.1.0"\n')
        data=dict(self.data);data.pop('commands')
        proposal=self.app.tasks.preview(data)
        self.assertEqual(proposal['commands'][0]['argv'],['cargo','test'])
        self.assertEqual(proposal['commands'][0]['cwd'],'backend')
        self.assertEqual(self.registry.calls,[])
        self.assertEqual(self.app.engine.list(),[])

    def test_custom_team_models_reach_separate_role_sessions(self):
        for reviewer in ('codex', 'minimax'):
            with self.subTest(reviewer=reviewer):
                self.file('app.txt','bad');self.registry.executions=0
                models={'executor':'implementation-model','reviewer':'review-model','planner':'implementation-model'}
                proposal=self.preview(partner=reviewer,model_overrides=models)
                with mock.patch.object(self.registry,'invoke',wraps=self.registry.invoke) as invoke:
                    started=self.app.tasks.start(self.start_body(proposal))
                    status=self.wait(started['workflow_id'])
                self.assertEqual(status['status'],'COMPLETED',status.get('reason'))
                self.assertEqual(status['model_overrides'],models)
                work=[c.args for c in invoke.call_args_list if c.args[1]['role']=='executor']
                review=[c.args for c in invoke.call_args_list if c.args[1]['role']=='reviewer']
                self.assertEqual(work[0][0],'codex');self.assertEqual(review[0][0],reviewer)
                self.assertEqual(work[0][1]['model'],'implementation-model')
                self.assertEqual(review[0][1]['model'],'review-model')
                with self.store.connect() as db:
                    sessions=db.execute('SELECT session_id FROM w5_sessions WHERE workflow_id=?',(status['id'],)).fetchall()
                self.assertGreaterEqual(len({row[0] for row in sessions}),2)

    def test_planned_subtasks_run_with_approved_team(self):
        original=self.registry.invoke
        def plan(provider,request):
            result=original(provider,request)
            if request['role']=='planner':
                result['output']=json.dumps({'tasks':[{'title':'Implement change'},{'title':'Check the result'}]})
            return result
        proposal=self.preview(partner='minimax',planning=True,model_overrides={'executor':'worker','reviewer':'checker'})
        with mock.patch.object(self.registry,'invoke',side_effect=plan):
            status=self.wait(self.app.tasks.start(self.start_body(proposal))['workflow_id'])
        self.assertEqual(status['status'],'COMPLETED',status.get('reason'))
        self.assertEqual(len(status['tasks']),2)
        self.assertTrue(all(t['executor']=='codex' and t['reviewer']=='minimax' for t in status['tasks']))

    def test_reject_invalid_team_models_before_any_execution(self):
        for overrides in ({'unknown':'model'},{'executor':'--unsafe'},['model']):
            with self.assertRaises(ValueError):self.app.tasks.preview(dict(self.data,model_overrides=overrides))
        self.assertEqual(self.registry.calls,[])
        self.assertEqual(self.app.engine.list(),[])

    def test_concurrent_sqlite_sidecar_removal_is_harmless(self):
        from ccx_workspace import store as store_module
        sidecar = Path(str(self.store.path) + '-journal')
        sidecar.touch(mode=0o600)
        validate = store_module.native.validate_permissions
        def disappears(path, *args, **kwargs):
            if Path(path) == sidecar:
                sidecar.unlink(missing_ok=True)
                raise FileNotFoundError(str(path))
            return validate(path, *args, **kwargs)
        with mock.patch.object(store_module.native, 'validate_permissions', side_effect=disappears):
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT 1').fetchone()[0], 1)

    def test_preview_creates_no_work_permissions_or_calls(self):
        value = self.preview()
        self.assertEqual(value['workflow']['providers'], {'planner':'codex','executor':'codex','reviewer':'codex'})
        self.assertEqual(value['workflow']['execution_policy'], 'single_task')
        self.assertEqual(self.app.engine.list(), [])
        self.assertEqual(self.registry.calls, [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM w5_approvals').fetchone()[0], 0)

    def test_approve_start_tests_and_separate_review(self):
        proposal = self.preview()
        started = self.app.tasks.start(self.start_body(proposal))
        status = self.wait(started['workflow_id'])
        self.assertEqual(status['status'], 'COMPLETED', status.get('reason'))
        self.assertGreater(self.registry.reviews, 0)
        with self.store.connect() as db:
            sessions = db.execute("SELECT session_id FROM w5_sessions WHERE role IN ('executor','reviewer')").fetchall()
        self.assertGreaterEqual(len({r[0] for r in sessions}), 2)
        result = self.app.tasks.results(started['workflow_id'])
        self.assertEqual(result['files'], ['app.txt'])
        self.assertIn('app.txt', result['preexisting'])
        self.assertIn('-bad', result['diff'])
        self.assertIn('+good', result['diff'])
        self.assertIn('\\ No newline at end of file', result['diff'])

    def test_duplicate_concurrent_start_launches_once(self):
        proposal = self.preview();body = self.start_body(proposal)
        with mock.patch.object(self.app, 'run', return_value={'accepted': True}) as run:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: self.app.tasks.start(body), range(2)))
        self.assertEqual(run.call_count, 1)
        self.assertEqual(len(self.app.engine.list()), 1)
        self.assertTrue(any(r.get('reused') for r in results))

    def test_invalid_second_approval_rolls_back_work_and_all_permissions(self):
        proposal = self.preview();original = self.app.engine.approve
        def fail(workflow, kind, scope, **kwargs):
            if kind == 'cost':
                raise ValueError('Injected validation failure')
            return original(workflow, kind, scope, **kwargs)
        with mock.patch.object(self.app.engine, 'approve', side_effect=fail):
            with self.assertRaises(ValueError):
                self.app.tasks.start(self.start_body(proposal))
        self.assertEqual(self.app.engine.list(), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM w5_approvals').fetchone()[0], 0)

    def test_expired_altered_or_unconfirmed_proposal_never_starts(self):
        proposal = self.preview()
        for changes in ({'confirmed': False}, {'revision': 'different'}, {'max_cost': 999}):
            with self.assertRaises((ValueError, PermissionError)):
                self.app.tasks.start(dict(self.start_body(proposal), **changes))
        with self.store.connect() as db:
            db.execute('UPDATE task_proposals SET expires=0')
        with self.assertRaises(ValueError):
            self.app.tasks.start(self.start_body(proposal))
        self.assertEqual(self.registry.calls, [])

    def test_project_change_requires_new_preview(self):
        proposal = self.preview();self.file('app.txt', 'edited by user')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.app.tasks.start(self.start_body(proposal))
        self.assertEqual(self.app.engine.list(), [])

    def test_provider_change_requires_new_preview(self):
        proposal = self.preview()
        save_setting(self.store, 'providers', {'codex': {'model':'changed'}})
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.app.tasks.start(self.start_body(proposal))

    def test_zero_usage_or_missing_commands_block_start(self):
        for changes in ({'max_cost':0}, {'commands':[]}):
            proposal = self.preview(**changes)
            self.assertTrue(proposal['blockers'])
            with self.assertRaises(ValueError):
                self.app.tasks.start(self.start_body(proposal))
        self.assertEqual(self.registry.calls, [])

    def test_launch_failure_is_saved_not_automatically_retried(self):
        proposal = self.preview();body=self.start_body(proposal)
        with mock.patch.object(self.app, 'run', side_effect=RuntimeError('busy')) as run:
            first = self.app.tasks.start(body);second=self.app.tasks.start(body)
        self.assertFalse(first['accepted']);self.assertTrue(second['reused'])
        self.assertEqual(run.call_count, 1)
        self.assertTrue(self.app.tasks.results(first['workflow_id'])['launch_error'])

    def test_next_task_remembers_preferences_but_not_permissions(self):
        first=self.preview()
        with mock.patch.object(self.app, 'run', return_value={'accepted':True}):
            self.app.tasks.start(self.start_body(first))
        before=len(self.app.engine.list())
        next_value=self.app.tasks.preview({'project_id':self.pid,'provider':'codex','instruction':'Next task'})
        self.assertEqual(next_value['commands'], first['commands'])
        self.assertEqual(next_value['workflow']['budgets']['max_cost'], 1)
        self.assertEqual(len(self.app.engine.list()), before)

    def test_manifest_suggestion_is_never_executed(self):
        self.file('package.json', json.dumps({'scripts':{'test':'echo unsafe && exit 1'}}))
        proposal = self.app.tasks.preview({'project_id':self.pid,'provider':'codex','instruction':'Fix'})
        self.assertEqual(proposal['commands'][0]['argv'], ['npm','test'])
        self.assertEqual(self.registry.calls, [])

    def message(self, **changes):
        value={'project_id':self.pid,'provider':'codex','content':'Explain this project',
               'confirmed':True,'idempotency_key':uuid.uuid4().hex}
        value.update(changes)
        return value

    def test_one_message_creates_and_sends_without_second_action(self):
        body=self.message();reply=self.app.tasks.message(body)
        deadline=time.time()+3
        while self.app.chat.active and time.time()<deadline:time.sleep(.02)
        chat=self.app.chat.status(reply['chat_id'])
        self.assertEqual(len(chat['messages']),2)
        self.assertEqual(chat['messages'][1]['content'],'Read-only answer')
        self.assertEqual(preferences(self.store)['conversations'][self.pid],reply['chat_id'])
        self.assertEqual(self.app.engine.list(), [])

    def test_duplicate_message_and_new_conversation_are_idempotent(self):
        body=self.message()
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self.app.tasks.message(body),range(2)))
        self.assertEqual(results[0]['chat_id'],results[1]['chat_id'])
        deadline=time.time()+3
        while self.app.chat.active and time.time()<deadline:time.sleep(.02)
        self.assertEqual(len(self.registry.calls),1)
        self.assertEqual(len(self.app.chat.list()),1)
        with self.assertRaises(ValueError):self.app.tasks.message(dict(body,content='different'))

    def test_unconfirmed_message_or_cross_project_chat_rejected(self):
        with self.assertRaises(PermissionError):self.app.tasks.message(self.message(confirmed=False))
        chat=self.app.chat.create(self.pid,'claude','Different project')
        with self.store.connect() as db:db.execute('UPDATE chats SET project_id=? WHERE id=?',('different-project',chat['id']))
        with self.assertRaises(ValueError):self.app.tasks.message(self.message(chat_id=chat['id']))
        self.assertEqual(self.registry.calls,[])

    def test_agent_switch_keeps_conversation_and_separate_native_sessions(self):
        first=self.app.tasks.message(self.message())
        deadline=time.time()+3
        while self.app.chat.active and time.time()<deadline:time.sleep(.02)
        original=self.app.chat.status(first['chat_id'])['session_id']
        second=self.app.tasks.message(self.message(chat_id=first['chat_id'],provider='claude'))
        deadline=time.time()+3
        while self.app.chat.active and time.time()<deadline:time.sleep(.02)
        alternate=self.app.chat.status(first['chat_id'])['session_id']
        self.assertNotEqual(original,alternate)
        third=self.app.tasks.message(self.message(chat_id=first['chat_id'],provider='codex'))
        deadline=time.time()+3
        while self.app.chat.active and time.time()<deadline:time.sleep(.02)
        self.assertEqual(first['chat_id'],second['chat_id'])
        self.assertEqual(first['chat_id'],third['chat_id'])
        self.assertEqual(self.app.chat.status(first['chat_id'])['session_id'],original)

    def test_restart_duplicate_message_not_resent(self):
        body=self.message();first=self.app.tasks.message(body)
        self.app.close();self.app=Dashboard(self.store,registry=self.registry)
        second=self.app.tasks.message(body)
        self.assertEqual(first['chat_id'],second['chat_id'])
        self.assertTrue(second['reused'])
        self.assertEqual(len(self.registry.calls),1)

    def test_excluded_secret_not_in_result_or_baseline(self):
        self.file('.env','private value')
        value=self.preview()
        with mock.patch.object(self.app,'run',return_value={}):
            self.app.tasks.start(self.start_body(value))
        self.file('.env','new private value')
        with self.store.connect() as db:
            row=db.execute('SELECT workflow_id,payload FROM task_proposals').fetchone()
        self.assertNotIn('private value',row['payload'])
        self.assertNotIn('.env',self.app.tasks.results(row['workflow_id'])['files'])


if __name__=='__main__':unittest.main()
