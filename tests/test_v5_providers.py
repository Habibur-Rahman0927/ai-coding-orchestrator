"""Provider protocol and scoped-tool tests; never authenticate or send API traffic."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
import uuid

LIB = Path(__file__).resolve().parents[1] / 'engine/lib'
sys.path.insert(0, str(LIB))
from ccx_workspace.providers import (ProviderRegistry, ProviderRequest, CLIProvider,
                                     MiniMaxProvider, normalize_cli, MINIMAX_ENDPOINT)
from ccx_workspace.tools import ScopedTools


class Response:
    status = 200
    def __init__(self, data, status=200):
        self.data, self.status = data, status
    def read(self, limit):
        return json.dumps(self.data).encode()[:limit]


class Connection:
    def __init__(self, response):
        self.response, self.requests, self.closed = response, [], False
    def connect(self):
        pass
    def request(self, *args, **kwargs):
        self.requests.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        self.closed = True


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def request(self, **kwargs):
        return ProviderRequest(project=self.project, prompt='Review this change', **kwargs)

    def test_configuration_never_accepts_key_values_or_arbitrary_origin(self):
        registry = ProviderRegistry()
        for config in ({'api_key':'not-allowed'}, {'api_key_env':'secret-value'},
                       {'endpoint':'https://attacker.invalid/v1/chat/completions'}, {'model':'sk-test-secret'}):
            with self.subTest(config=config), self.assertRaises(ValueError):
                registry.configure('minimax', config)
        registry.configure('minimax', {'model':'configured-model','api_key_env':'TEST_MINIMAX_KEY'})
        self.assertFalse(registry.probe('minimax')['live_connection_tested'])

    def test_cli_requires_native_agent_authorization(self):
        for name in ('claude','codex'):
            with self.subTest(name=name), self.assertRaises(PermissionError):
                CLIProvider(name).command(self.request())
        argv = CLIProvider('codex').command(self.request(allowed_operations=['native_agent_access']))
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', argv)
        self.assertNotIn('--model', argv)

    def test_exact_session_and_separate_native_write_authorization(self):
        session = str(uuid.uuid4())
        request = self.request(session_id=session, allowed_operations=['native_agent_access','native_agent_write'])
        argv = CLIProvider('codex').command(request)
        self.assertEqual(argv[:3], ['codex','exec','resume'])
        self.assertIn(session, argv)
        self.assertNotIn('--last', argv)
        self.assertIn('sandbox_mode="workspace-write"', argv)
        claude = CLIProvider('claude').command(request)
        self.assertEqual(claude[claude.index('--resume')+1], session)
        self.assertEqual(claude[claude.index('--tools')+1], '')
        self.assertNotIn('--dangerously-skip-permissions', claude)

    def test_normalization_omits_reasoning(self):
        events = normalize_cli('claude', {'type':'assistant','message':{'content':[
            {'type':'thinking','thinking':'internal'}, {'type':'text','text':'answer'}]}})
        self.assertEqual(events,[{'type':'text','text':'answer'}])
        session = str(uuid.uuid4())
        self.assertEqual(normalize_cli('codex',{'type':'thread.started','thread_id':session})[0]['session_id'],session)

    def fake_minimax(self, response, status=200):
        connection = Connection(Response(response,status))
        provider = MiniMaxProvider({'model':'configured-model','api_key_env':'TEST_MINIMAX_KEY'},
                                   connection_factory=lambda *a, **k: connection)
        registry = ProviderRegistry(providers={'minimax':provider})
        return registry, connection

    def test_minimax_independent_api_normalization_and_credential_redaction(self):
        registry, connection = self.fake_minimax({'choices':[{'message':{'role':'assistant','content':'answer'},
                                                              'finish_reason':'stop'}],
                                                  'usage':{'prompt_tokens':4,'completion_tokens':2}})
        with mock.patch.dict(os.environ, {'TEST_MINIMAX_KEY':'dummy-test-key'}):
            result = registry.invoke('minimax', self.request())
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['output'],'answer')
        self.assertNotIn('dummy-test-key',repr(result))
        args, kwargs = connection.requests[0]
        self.assertEqual(args[:2],('POST','/v1/chat/completions'))
        self.assertEqual(kwargs['headers']['Authorization'],'Bearer dummy-test-key')
        self.assertEqual(json.loads(kwargs['body'])['model'],'configured-model')
        self.assertTrue(connection.closed)

    def test_tool_call_is_returned_not_executed_and_full_history_preserved(self):
        message = {'role':'assistant','content':None,'reasoning_content':'opaque-provider-state',
                   'tool_calls':[{'id':'call1','type':'function','function':{'name':'read_file','arguments':'{"path":"README.md"}'}}]}
        registry, connection = self.fake_minimax({'choices':[{'message':message,'finish_reason':'tool_calls'}]})
        with mock.patch.dict(os.environ, {'TEST_MINIMAX_KEY':'dummy-test-key'}):
            result = registry.invoke('minimax',self.request(allowed_operations=['read_file']))
        self.assertEqual(result['status'],'tool_calls')
        self.assertEqual(result['tool_calls'][0]['arguments'],{'path':'README.md'})
        self.assertEqual(result['message'],message)
        self.assertNotIn('opaque-provider-state',repr(result['events']))
        self.assertFalse((self.project / 'README.md').exists())

    def test_unapproved_model_tool_and_redirect_fail_closed(self):
        message = {'role':'assistant','tool_calls':[{'id':'x','function':{'name':'run_command','arguments':'{}'}}]}
        for response,status in (({'choices':[{'message':message}]},200), ({},302)):
            registry,connection = self.fake_minimax(response,status)
            with mock.patch.dict(os.environ, {'TEST_MINIMAX_KEY':'dummy-test-key'}):
                result = registry.invoke('minimax',self.request())
            self.assertEqual(result['status'],'failed')
            self.assertEqual(len(connection.requests),1)

    def test_cancellation_before_request_has_no_transport_effect(self):
        registry,connection = self.fake_minimax({})
        cancelled=threading.Event();cancelled.set()
        with mock.patch.dict(os.environ, {'TEST_MINIMAX_KEY':'dummy-test-key'}):
            result=registry.invoke('minimax',self.request(cancel_event=cancelled))
        self.assertEqual(result['status'],'cancelled')
        self.assertFalse(connection.requests)

    def test_cli_controlled_mock_runs_under_actual_supervisor(self):
        session=str(uuid.uuid4())
        script=self.project/'agent.py'
        script.write_text('import json\nprint(json.dumps({"type":"thread.started","thread_id":'+repr(session)+'}))\n'
                          'print(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"mock reply"}}))\n'
                          'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":5}}))\n')
        provider=CLIProvider('codex')
        with mock.patch.object(provider,'command',return_value=[sys.executable,str(script)]):
            result=ProviderRegistry(providers={'codex':provider}).invoke('codex',self.request(timeout=5))
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(result['session_id'],session)
        self.assertEqual(result['output'],'mock reply')

    def test_cli_timeout_and_active_cancellation(self):
        provider=CLIProvider('codex')
        for cancel in (False,True):
            flag=threading.Event()
            timer=threading.Timer(.2,flag.set) if cancel else None
            if timer: timer.start()
            try:
                with mock.patch.object(provider,'command',return_value=[sys.executable,'-c','import time;time.sleep(30)']):
                    result=ProviderRegistry(providers={'codex':provider}).invoke('codex',self.request(timeout=1,cancel_event=flag))
                self.assertEqual(result['status'],'cancelled' if cancel else 'timeout',result)
            finally:
                if timer: timer.cancel()

    def test_minimax_tool_continuation_keeps_exact_local_session_and_transcript(self):
        session=str(uuid.uuid4())
        history=[{'role':'system','content':'role'}, {'role':'user','content':'original'},
                 {'role':'assistant','tool_calls':[{'id':'c','type':'function','function':{'name':'read_file','arguments':'{}'}}]},
                 {'role':'tool','tool_call_id':'c','content':'result'}]
        registry,connection=self.fake_minimax({'choices':[{'message':{'role':'assistant','content':'done'},'finish_reason':'stop'}]})
        with mock.patch.dict(os.environ, {'TEST_MINIMAX_KEY':'dummy-test-key'}):
            result=registry.invoke('minimax',self.request(session_id=session,history=history))
        self.assertEqual(result['session_id'],session)
        self.assertEqual(json.loads(connection.requests[0][1]['body'])['messages'],history)
        self.assertEqual(result['history'][:-1],history)
        self.assertEqual(result['history'][-1]['content'],'done')


class ScopedToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.project=Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        subprocess.run(['git','init','-q',str(self.project)],check=True,capture_output=True)
        (self.project/'file ü.txt').write_text('hello\nworld\n',encoding='utf-8')
        self.tools=ScopedTools(self.project,['list_directory','read_file','search','patch','run_command'])

    def test_authorization_required(self):
        with self.assertRaises(PermissionError):
            ScopedTools(self.project).execute('read_file',{'path':'file ü.txt'})
        with self.assertRaises(PermissionError):
            self.tools.execute('run_command',{'name':'unapproved'})

    def test_traversal_and_sensitive_files_refused(self):
        for path in ('../outside','C:/outside','NUL','.env','.git/config','secrets.json'):
            with self.subTest(path=path), self.assertRaises((ValueError,PermissionError)):
                self.tools.execute('read_file',{'path':path})
        (self.project/'ordinary.txt').write_text('-----BEGIN ' + 'PRIVATE KEY-----\nprivate\n')
        with self.assertRaises(PermissionError):
            self.tools.execute('read_file',{'path':'ordinary.txt'})

    @unittest.skipIf(os.name=='nt','Symlink creation requires optional Windows privileges')
    def test_symlink_and_hardlink_refused(self):
        (self.project/'link').symlink_to(self.project/'file ü.txt')
        with self.assertRaises(PermissionError):
            self.tools.execute('read_file',{'path':'link'})
        os.link(self.project/'file ü.txt',self.project/'hard')
        with self.assertRaises(PermissionError):
            self.tools.execute('read_file',{'path':'hard'})

    def test_patch_requires_exact_current_hash_and_unique_context(self):
        read=self.tools.execute('read_file',{'path':'file ü.txt'})
        args={'path':'file ü.txt','sha256':read['sha256'],'old':'hello','new':'updated'}
        self.assertTrue(self.tools.execute('patch',args)['changed'])
        self.assertEqual((self.project/'file ü.txt').read_text(),'updated\nworld\n')
        with self.assertRaises(ValueError):
            self.tools.execute('patch',args)
        result=self.tools.execute('search',{'query':'world'})
        self.assertEqual(result['matches'][0]['line'],2)

    def test_gitignored_and_custom_excluded_files_are_not_read_or_listed(self):
        (self.project/'.gitignore').write_text('private.txt\n')
        (self.project/'private.txt').write_text('private data')
        (self.project/'custom.txt').write_text('custom data')
        tools=ScopedTools(self.project,['read_file','list_directory'],exclusions=['custom.txt'])
        for path in ('private.txt','custom.txt'):
            with self.assertRaises(PermissionError):tools.execute('read_file',{'path':path})
        names=[item['name'] for item in tools.execute('list_directory',{})['entries']]
        self.assertNotIn('private.txt',names);self.assertNotIn('custom.txt',names)

    def test_new_file_patch_is_explicit_and_never_overwrites(self):
        arguments={'path':'new directory/module.py','sha256':'absent','old':'','new':'print("hello")\n'}
        result=self.tools.execute('patch',arguments)
        self.assertTrue(result['created'])
        self.assertEqual((self.project/'new directory/module.py').read_text(),'print("hello")\n')
        with self.assertRaises(ValueError):
            self.tools.execute('patch',arguments)

    def test_only_exact_user_approved_command_runs(self):
        tools=ScopedTools(self.project,['run_command'],{'test':{'argv':[sys.executable,'-c','print("ok")'],'timeout':5}})
        result=tools.execute('run_command',{'name':'test'})
        self.assertEqual(result['exit_code'],0,result)
        self.assertIn('ok',result['output'])
        with self.assertRaises(ValueError):
            tools.execute('run_command',{'name':'test','argv':['malicious']})


if __name__=='__main__':
    unittest.main(verbosity=2)
