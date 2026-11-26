"""Offline delivery contracts: saved access, durable queue and conversation isolation."""
import json
import threading
import time
import uuid
import unittest
from unittest import mock
import test_v5_memory as fixtures
from test_v5_easy_tasks import Registry
from ccx_workspace.server import Dashboard


class DeliveryTests(unittest.TestCase):
    file = fixtures.MemoryTests.file

    def setUp(self):
        fixtures.MemoryTests.setUp(self)
        self.file('app.txt', 'before')
        self.app = Dashboard(self.store, registry=Registry(tool=True))
        self.app.delivery.stop.set()
        self.app.delivery.thread.join(2)
        self.launch = mock.patch.object(self.app, '_launch')
        self.launched = self.launch.start()
        self.app.delivery.access(self.pid, {'confirmed': True, 'enabled': True, 'providers': ['codex']})

    def tearDown(self):
        self.launch.stop()
        self.app.close()
        fixtures.MemoryTests.tearDown(self)

    def body(self, **changes):
        return dict({'project_id': self.pid, 'provider': 'codex', 'instruction': 'Fix app.txt',
                     'confirmed': True, 'idempotency_key': uuid.uuid4().hex}, **changes)

    def test_explicit_grant_and_new_provider_boundary(self):
        self.app.delivery.access(self.pid, {'confirmed': True, 'enabled': False})
        with self.assertRaises(PermissionError):
            self.app.delivery.submit(self.body())
        self.assertEqual(self.app.engine.list(), [])
        self.app.delivery.access(self.pid, {'confirmed': True, 'enabled': True, 'providers': ['codex']})
        with self.assertRaises(PermissionError):
            self.app.delivery.submit(self.body(partner='minimax'))
        self.assertEqual(self.app.registry.calls, [])

    def test_double_send_is_one_workflow_and_one_message(self):
        body = self.body()
        first = self.app.delivery.submit(body)
        second = self.app.delivery.submit(body)
        self.assertEqual(first['workflow_id'], second['workflow_id'])
        self.assertEqual(len(self.app.engine.list()), 1)
        self.assertEqual(len(self.app.chat.status(first['chat_id'])['messages']), 1)
        self.assertEqual(self.launched.call_count, 1)
        with self.assertRaises(ValueError):
            self.app.delivery.submit(dict(body, instruction='Different task'))
        self.assertEqual(self.app.tasks.submission(body['idempotency_key'])['chat_id'], first['chat_id'])

    def test_queue_waits_and_refreshes_baseline_with_context(self):
        first = self.app.delivery.submit(self.body())
        second = self.app.delivery.submit(self.body(instruction='Add another change', chat_id=first['chat_id']))
        self.assertEqual(second['queue_state'], 'queued')
        self.assertEqual(self.launched.call_count, 1)
        self.file('app.txt', 'first change')
        self.app.engine.cancel(first['workflow_id'])
        self.app.delivery.finished(first['workflow_id'])
        self.app.delivery.drain()
        self.assertEqual(self.launched.call_count, 2)
        with self.store.connect() as db:
            payload = json.loads(db.execute('SELECT payload FROM task_proposals WHERE workflow_id=?', (second['workflow_id'],)).fetchone()[0])
        self.assertEqual(payload['before']['texts']['app.txt'], 'first change')
        status = self.app.engine.status(second['workflow_id'])
        self.assertEqual(status['objective'], 'Add another change')
        self.assertIn('Fix app.txt', status['continuation_context'])

    def test_revoke_blocks_previously_queued_work(self):
        first = self.app.delivery.submit(self.body())
        second = self.app.delivery.submit(self.body())
        self.app.delivery.access(self.pid, {'confirmed': True, 'enabled': False})
        self.app.engine.cancel(first['workflow_id'])
        self.app.delivery.finished(first['workflow_id'])
        self.app.delivery.drain()
        self.assertEqual(self.launched.call_count, 1)
        self.assertEqual(self.app.delivery.describe(second['workflow_id'])['queue_state'], 'held')
        self.assertIn('access', self.app.delivery.describe(second['workflow_id'])['queue_reason'])

    def test_cancel_queued_request_never_launches(self):
        first = self.app.delivery.submit(self.body())
        second = self.app.delivery.submit(self.body())
        self.app.engine.cancel(second['workflow_id'])
        self.app.engine.cancel(first['workflow_id'])
        self.app.delivery.finished(first['workflow_id'])
        self.app.delivery.drain()
        self.assertEqual(self.launched.call_count, 1)
        self.assertEqual(self.app.tasks.results(second['workflow_id'])['files'],[])

    def test_queue_survives_dashboard_restart_without_replaying_started_work(self):
        first = self.app.delivery.submit(self.body())
        second = self.app.delivery.submit(self.body())
        self.app.close()
        other = Dashboard(self.store, registry=Registry(tool=True))
        other.delivery.stop.set(); other.delivery.thread.join(2)
        try:
            with mock.patch.object(other, '_launch') as launch:
                other.delivery.drain()
                launch.assert_not_called()
                self.assertEqual(other.delivery.describe(second['workflow_id'])['queue_state'], 'queued')
                other.engine.cancel(first['workflow_id']); other.delivery.finished(first['workflow_id'])
                other.delivery.drain()
                launch.assert_called_once_with(second['workflow_id'])
        finally:
            other.close()

    def test_project_draft_and_effort_persist(self):
        draft = {'content': 'Continue work', 'mode': 'build', 'chatOptions': {'codex': {'model': 'custom', 'effort': 'low'}}}
        self.app.delivery.draft(self.pid, draft)
        self.assertEqual(self.app.delivery.draft(self.pid), draft)
        value = self.app.delivery.submit(self.body(effort_overrides={'executor': 'low'}, model_overrides={'reviewer': 'custom'}))
        w = self.app.engine.status(value['workflow_id'])
        self.assertEqual(w['effort_overrides']['executor'], 'low')
        self.assertEqual(w['model_overrides']['reviewer'], 'custom')

    def test_exclusion_change_invalidates_grant_and_hides_saved_diff(self):
        value=self.app.delivery.submit(self.body())
        with self.store.connect() as db:db.execute('UPDATE w5_workflows SET started_at=? WHERE id=?',(time.time(),value['workflow_id']))
        self.file('app.txt','task result')
        self.app.engine.cancel(value['workflow_id'])
        self.app.delivery.finished(value['workflow_id'])
        with self.store.connect() as db:
            db.execute('UPDATE projects SET exclusions=? WHERE id=?',(json.dumps(['app.txt']),self.pid))
        self.assertFalse(self.app.delivery.access(self.pid)['enabled'])
        self.assertEqual(self.app.tasks.results(value['workflow_id'])['diff'],'')
        with self.assertRaises(PermissionError):self.app.delivery.submit(self.body())

    def test_activity_cursor_includes_updated_existing_event(self):
        value=self.app.delivery.submit(self.body())
        wid=value['workflow_id']
        first=self.app.delivery.updates(wid,{'cursor':0})
        with self.store.connect() as db:
            self.app.engine._checkpoint(db,wid,'PROVIDER_EVENT',{'type':'text','text':'first'})
        second=self.app.delivery.updates(wid,{'cursor':first['cursor']})
        self.assertEqual(len(second['events']),1)
        event=second['events'][0]
        with self.store.connect() as db:
            db.execute('UPDATE w5_checkpoints SET data=? WHERE id=?',(json.dumps({'type':'text','text':'updated'}),event['id']))
        third=self.app.delivery.updates(wid,{'cursor':second['cursor']})
        self.assertEqual(third['events'][0]['id'],event['id'])
        self.assertEqual(third['events'][0]['data']['text'],'updated')
        self.assertEqual(self.app.delivery.updates(wid,{'cursor':third['cursor']})['events'],[])

    def test_finished_diff_is_stable_after_another_change(self):
        value=self.app.delivery.submit(self.body())
        with self.store.connect() as db:db.execute('UPDATE w5_workflows SET started_at=? WHERE id=?',(time.time(),value['workflow_id']))
        self.file('app.txt','task result')
        self.app.engine.cancel(value['workflow_id'])
        self.app.delivery.finished(value['workflow_id'])
        initial=self.app.tasks.results(value['workflow_id'])
        self.file('app.txt','later external edit')
        self.assertEqual(self.app.tasks.results(value['workflow_id']),initial)
        self.assertIn('+task result',initial['diff'])
        self.assertNotIn('later external',initial['diff'])

    def test_conversation_project_mismatch_is_refused(self):
        chat = self.app.chat.create(self.pid, 'codex', 'Original')
        with self.store.connect() as db:
            db.execute('UPDATE chats SET project_id=? WHERE id=?', ('different', chat['id']))
        with self.assertRaises(ValueError):
            self.app.delivery.submit(self.body(chat_id=chat['id']))
        self.launched.assert_not_called()
