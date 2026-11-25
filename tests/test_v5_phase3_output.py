"""Offline checks that provider-controlled secrets never become durable evidence."""
import json
import sys
import threading
import unittest
from unittest import mock
import test_v5_workflows as fixtures
from ccx_workspace.chat import Chat
from ccx_workspace.providers import ProviderRegistry


def marker():
    return 'ghp_' + 'B' * 32


class OutputSecurityTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    create = fixtures.WorkflowTests.create
    authorize = fixtures.WorkflowTests.authorize

    def test_workflow_refuses_sensitive_output_and_nested_history(self):
        for field in ('output', 'history'):
            with self.subTest(field=field):
                identifier = self.create()
                self.authorize(identifier)
                registry = fixtures.MockRegistry()
                original = registry.invoke
                def invoke(provider, request):
                    result = original(provider, request)
                    result[field] = marker() if field == 'output' else [{'content': marker()}]
                    return result
                registry.invoke = invoke
                result = self.engine.run(identifier, registry)
                self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
                with self.store.connect() as db:
                    for table in ('w5_actions', 'w5_sessions', 'w5_checkpoints'):
                        rows = [tuple(r) for r in db.execute('SELECT * FROM ' + table)]
                        self.assertNotIn(marker(), json.dumps(rows))
                self.engine.cancel(identifier)

    def test_registry_refuses_sensitive_nested_provider_events(self):
        registry = ProviderRegistry()
        class Adapter:
            def execute(self, request):
                yield {'type': 'history', 'history': [{'content': marker()}]}
                yield {'type': 'completed'}
        with mock.patch.object(registry, 'get', return_value=Adapter()):
            result = registry.invoke('codex', {'project': self.project, 'prompt': 'Inspect'})
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn(marker(), json.dumps(result))

    def test_registry_checks_accumulated_text_before_stream_callback(self):
        registry = ProviderRegistry()
        callbacks = []
        class Adapter:
            def execute(self, request):
                yield {'type': 'text', 'text': marker()[:10]}
                yield {'type': 'text', 'text': marker()[10:]}
                yield {'type': 'completed'}
        with mock.patch.object(registry, 'get', return_value=Adapter()):
            result = registry.invoke('codex', {'project': self.project, 'prompt': 'Inspect',
                'event_callback': callbacks.append})
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn(marker(), ''.join(e.get('text', '') for e in callbacks))
        self.assertNotIn(marker(), json.dumps(result))

    def test_workflow_checks_split_telemetry_from_registry(self):
        identifier = self.create()
        self.authorize(identifier)
        registry = fixtures.MockRegistry()
        original = registry.invoke
        def invoke(provider, request):
            request['event_callback']({'type': 'text', 'text': marker()[:10]})
            request['event_callback']({'type': 'text', 'text': marker()[10:]})
            return original(provider, request)
        registry.invoke = invoke
        self.engine.run(identifier, registry)
        texts = [r['data'].get('text', '') for r in self.engine.checkpoints(identifier)
                 if r['event'] == 'PROVIDER_EVENT']
        self.assertNotIn(marker(), ''.join(texts))

    def test_chat_rejects_split_secret_and_nested_history(self):
        for kind in ('text', 'history'):
            with self.subTest(kind=kind):
                class Adapter:
                    def execute(self, request):
                        if kind == 'text':
                            yield {'type': 'text', 'text': marker()[:10]}
                            yield {'type': 'text', 'text': marker()[10:]}
                        else:
                            yield {'type': 'history', 'history': [{'content': marker()}]}
                        yield {'type': 'completed'}
                registry = mock.Mock()
                registry.get.return_value = Adapter()
                chat = Chat(self.store, registry)
                item = chat.create(self.pid, 'codex', 'Inspect')
                record = dict(item, history='[]')
                chat._execute(record, 'Inspect', 256, 10, threading.Event())
                self.assertEqual(chat.status(item['id'])['status'], 'FAILED')
                with self.store.connect() as db:
                    for table in ('chats', 'chat_messages'):
                        self.assertNotIn(marker(), json.dumps([tuple(r) for r in db.execute('SELECT * FROM ' + table)]))
                chat.close()


if __name__ == '__main__':
    unittest.main()
