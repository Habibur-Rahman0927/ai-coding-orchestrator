"""Secret handling and diagnostics; no actual OS credential write or paid request."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'engine/lib'))
from ccx_workspace.credentials import CredentialManager, CredentialError, SecretService, _SESSION
from ccx_workspace.diagnostics import Diagnostics
from ccx_workspace.providers import ProviderRegistry, MiniMaxProvider, normalized_usage, classify_error
from ccx_workspace.settings import provider_config, save_setting, registry_for
from ccx_workspace.store import Store


class MemoryVault:
    name = 'Mock OS credential facility'
    def __init__(self): self.values = {}; self.reads = 0
    def set(self, service, account, value): self.values[(service, account)] = value
    def get(self, service, account): self.reads += 1; return self.values.get((service, account))
    def remove(self, service, account): self.values.pop((service, account), None)


class MockRegistry:
    offline = True
    def __init__(self): self.calls = []; self.session = str(uuid.uuid4())
    def get(self, provider):
        return MiniMaxProvider({'model': 'mock-model', 'api_key_env': 'MOCK_KEY'})
    def invoke(self, provider, request):
        self.calls.append(dict(request))
        return {'status': 'completed', 'session_id': self.session,
                'usage': {'input_tokens': 7, 'output_tokens': 2}, 'events': [{'type': 'text'}],
                'history': [{'role': 'assistant', 'content': 'WORKSPACE_OK'}], 'output': 'WORKSPACE_OK'}


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-v5-secrets-test-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / 'state/workspace.sqlite3')
        self.vault = MemoryVault()
        self.manager = CredentialManager(self.store, backend=self.vault)
        self.secret = 'dummy-private-test-value'
        self.addCleanup(_SESSION.clear)

    def test_secret_add_replace_remove_without_database_or_status_leak(self):
        with self.assertRaises(PermissionError): self.manager.set('minimax', self.secret)
        first = self.manager.set('minimax', self.secret, authorized=True)
        self.assertTrue(first['configured'])
        self.assertNotIn(self.secret, json.dumps(first))
        self.assertNotIn(self.secret.encode(), self.store.path.read_bytes())
        self.assertEqual(self.vault.reads, 0)
        self.assertEqual(self.manager.resolve('minimax', provider_config(self.store)['minimax']), self.secret)
        self.manager.set('minimax', 'replacement-test-key', authorized=True)
        self.assertEqual(self.manager.resolve('minimax', {'credential_mode': 'os'}), 'replacement-test-key')
        self.assertFalse(self.manager.remove(authorized=True)['configured'])
        self.assertFalse(self.vault.values)

    def test_native_cli_authentication_is_outside_credential_manager(self):
        for provider in ('codex', 'claude'):
            with self.assertRaises(ValueError): self.manager.set(provider, self.secret, authorized=True)

    def test_no_plaintext_fallback_when_facility_unavailable(self):
        manager = CredentialManager(self.store, backend=False)
        with self.assertRaises(CredentialError): manager.set('minimax', self.secret, authorized=True)
        self.assertFalse(provider_config(self.store))
        self.assertNotIn(self.secret.encode(), self.store.path.read_bytes())
        status = manager.set('minimax', self.secret, mode='session', authorized=True)
        self.assertFalse(status['persistent'])
        self.assertEqual(CredentialManager(self.store, backend=False).resolve('minimax', {'credential_mode': 'session'}), self.secret)
        _SESSION.clear()
        self.assertFalse(manager.status()['configured'])

    def test_database_namespaces_do_not_share_os_or_session_credentials(self):
        self.manager.set('minimax', self.secret, authorized=True)
        other = CredentialManager(Store(self.base / 'other/workspace.sqlite3'), backend=self.vault)
        self.assertIsNone(other.resolve('minimax', {'credential_mode': 'os'}))
        self.manager.set('minimax', self.secret, mode='session', authorized=True)
        self.assertIsNone(other.resolve('minimax', {'credential_mode': 'session'}))

    def test_session_secret_resolves_without_global_environment_mutation(self):
        self.manager.set('minimax', self.secret, mode='session', authorized=True)
        config = provider_config(self.store)
        config['minimax']['model'] = 'explicit-model'
        save_setting(self.store, 'providers', config)
        registry = registry_for(self.store)
        self.assertTrue(registry.probe('minimax')['available'])
        self.assertEqual(registry.get('minimax').credential_resolver('minimax', config['minimax']), self.secret)
        self.assertNotIn(self.secret, os.environ.values())

    def test_secret_service_uses_stdin_never_argv(self):
        with mock.patch('ccx_workspace.credentials.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            SecretService().set('application-test', 'minimax', self.secret)
        args, kwargs = run.call_args
        self.assertNotIn(self.secret, repr(args))
        self.assertEqual(kwargs['input'], self.secret)
        self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)

    def test_model_update_does_not_discard_selected_credential_facility(self):
        registry = ProviderRegistry(config={'minimax': {'model': 'first-model', 'credential_mode': 'os'}})
        value = registry.configure('minimax', {'model': 'second-model'})
        self.assertEqual(value['credential_mode'], 'os')
        self.assertEqual(value['model'], 'second-model')
        value = registry.configure('minimax', {'credential_mode': 'environment', 'api_key_env': 'NAMED_KEY'})
        self.assertEqual(value['credential_mode'], 'environment')

    def test_credential_change_invalidates_verification_fingerprint(self):
        diagnostics = Diagnostics(self.store, registry=MockRegistry(), credentials=self.manager)
        before = diagnostics._fingerprint('minimax')
        self.manager.set('minimax', self.secret, authorized=True)
        self.assertNotEqual(before, diagnostics._fingerprint('minimax'))

    def test_live_test_requires_exact_human_authorization_before_call(self):
        registry = MockRegistry(); diagnostics = Diagnostics(self.store, registry, self.manager)
        for authorization in ({}, {'confirmed': True}, {'confirmed': True, 'provider': 'claude', 'max_calls': 1},
                              {'confirmed': True, 'provider': 'minimax', 'max_calls': 2}):
            with self.assertRaises(PermissionError): diagnostics.live('minimax', authorization)
        self.assertFalse(registry.calls)
        with self.assertRaises(PermissionError): diagnostics.live('codex', {'confirmed': True, 'provider': 'codex', 'max_calls': 1})

    def test_authorized_mock_session_creation_resume_and_redacted_record(self):
        registry = MockRegistry(); diagnostics = Diagnostics(self.store, registry, self.manager)
        report = diagnostics.live('minimax', {'confirmed': True, 'provider': 'minimax', 'max_calls': 2}, resume=True)
        self.assertEqual(report['status'], 'verified')
        self.assertFalse(report['live'])
        self.assertIsNone(diagnostics.local('minimax')['last_verified_at'])
        self.assertEqual(len(registry.calls), 2)
        self.assertEqual(registry.calls[1]['session_id'], registry.session)
        self.assertFalse(Path(registry.calls[0]['project']).exists())
        self.assertEqual(report['calls'][0]['usage']['input_tokens'], 7)
        self.assertNotIn('WORKSPACE_OK', json.dumps(report))
        self.assertFalse(report['project_data_shared'])

    def test_failed_live_test_never_reports_connection_verified(self):
        registry = MockRegistry(); registry.offline = False
        registry.invoke = lambda *_: {'status': 'failed', 'error_kind': 'usage_limit'}
        diagnostics = Diagnostics(self.store, registry, self.manager)
        report = diagnostics.live('minimax', {'confirmed': True, 'provider': 'minimax', 'max_calls': 1})
        self.assertEqual(report['status'], 'failed')
        self.assertEqual(diagnostics.local('minimax')['connection_status'], 'usage_restricted')

    def test_executable_presence_does_not_prove_connection(self):
        diagnostics = Diagnostics(self.store, credentials=self.manager)
        with mock.patch('ccx_workspace.diagnostics.shutil.which', return_value='/mock/codex'), mock.patch('ccx_workspace.providers.shutil.which', return_value='/mock/codex'), mock.patch('ccx_workspace.diagnostics._command', side_effect=[(0, 'codex-cli 0.171.0', ''), (None, '', '')]):
            result = diagnostics.local('codex')
        self.assertEqual(result['connection_status'], 'authentication_unknown')
        self.assertFalse(result['live_connection_tested'])
        self.assertIsNone(result['last_verified_at'])

    def test_unsupported_claude_version_reports_actionable_error(self):
        diagnostics = Diagnostics(self.store, credentials=self.manager)
        with mock.patch('ccx_workspace.diagnostics.shutil.which', return_value='/mock/claude'), mock.patch('ccx_workspace.diagnostics._command', return_value=(0, '2.1.10', '')):
            result = diagnostics.local('claude')
        self.assertFalse(result['compatible'])
        self.assertEqual(result['connection_status'], 'unavailable')

    def test_visible_event_callback_excludes_opaque_transcript_and_is_nonfatal(self):
        class FakeProvider:
            def execute(self, request):
                for item in ({'type': 'message', 'message': {'reasoning_content': 'opaque'}},
                             {'type': 'history', 'history': [{'reasoning_content': 'opaque'}]},
                             {'type': 'text', 'text': 'visible'}, {'type': 'completed'}):
                    yield item
        seen = []
        def callback(event):
            seen.append(event)
            raise RuntimeError('UI disconnected')
        registry = ProviderRegistry(providers={'minimax': FakeProvider()})
        result = registry.invoke('minimax', {'project': self.base, 'prompt': 'test', 'event_callback': callback})
        self.assertEqual(result['status'], 'completed')
        self.assertEqual([event['type'] for event in seen], ['text', 'completed'])
        self.assertNotIn('opaque', repr(seen))

    def test_summary_uses_redacted_cache_without_cli_or_vault_reads(self):
        diagnostics = Diagnostics(self.store, credentials=self.manager)
        with mock.patch('ccx_workspace.diagnostics.shutil.which', return_value='/mock/codex'), mock.patch('ccx_workspace.providers.shutil.which', return_value='/mock/codex'), mock.patch('ccx_workspace.diagnostics._command', side_effect=[(0, 'codex-cli 0.171.0', ''), (0, 'Logged in', '')]):
            diagnostics.local('codex')
        with mock.patch('ccx_workspace.providers.shutil.which', return_value='/mock/codex'), mock.patch('ccx_workspace.diagnostics._command', side_effect=AssertionError('Summary spawned CLI')):
            summary = diagnostics.summary('codex')
        self.assertEqual(summary['authentication'], 'authenticated_locally')
        self.assertEqual(summary['connection_status'], 'configured')
        self.assertIsNotNone(summary['last_local_check_at'])
        self.assertEqual(self.vault.reads, 0)

    def test_usage_normalization_and_redacted_error_categories(self):
        usage = normalized_usage({'prompt_tokens': 100, 'completion_tokens': 20,
            'prompt_tokens_details': {'cached_tokens': 60}, 'completion_tokens_details': {'reasoning_tokens': 10}})
        self.assertEqual(usage['input_tokens'], 100)
        self.assertEqual(usage['output_tokens'], 20)
        self.assertEqual(usage['cached_input_tokens'], 60)
        self.assertEqual(usage['reasoning_tokens'], 10)
        self.assertEqual(classify_error('HTTP 429'), 'usage_limit')
        self.assertEqual(classify_error('HTTP 401'), 'authentication')

if __name__ == '__main__': unittest.main(verbosity=2)
