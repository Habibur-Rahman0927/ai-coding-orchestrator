"""Streaming protocol fixtures, without network or real provider calls."""
import json
import os
import threading
import unittest
from unittest import mock
import test_v5_providers as fixtures
from ccx_workspace.providers import MiniMaxProvider, normalize_cli

class Streams(unittest.TestCase):
    setUp=fixtures.ProviderTests.setUp
    request=fixtures.ProviderTests.request

    def test_minimax_text_arrives_before_terminal_chunk_and_keeps_tool_fragments(self):
        release=threading.Event()
        parts=[
            {'choices':[{'delta':{'content':'Checking '}}]},
            {'choices':[{'delta':{'reasoning_content':'private reasoning','tool_calls':[{'index':0,'id':'call-1','function':{'name':'read_file','arguments':'{"path":'}}]}}]},
            {'choices':[{'delta':{'tool_calls':[{'index':0,'function':{'arguments':'"README.md"}'}}]},'finish_reason':'tool_calls'}],'usage':{'total_tokens':8}}]
        class Response:
            status=200
            index=0
            def getheader(self,*args):return 'text/event-stream'
            def readline(self,limit):
                if self.index==1:release.wait(3)
                if self.index==len(parts):return b'data: [DONE]\n'
                data=parts[self.index];self.index+=1
                return b'data: '+json.dumps(data).encode()+b'\n'
        response=Response();connection=fixtures.Connection(response)
        provider=MiniMaxProvider({'model':'fixture','api_key_env':'TEST_MINIMAX_KEY'},connection_factory=lambda *a,**k:connection)
        with mock.patch.dict(os.environ,{'TEST_MINIMAX_KEY':'fixture-key'}):
            stream=provider.execute(self.request(allowed_operations=['read_file']))
            self.assertEqual(next(stream)['type'],'session')
            first=next(stream)
            self.assertEqual(first['text'],'Checking ')
            release.set()
            events=list(stream)
        call=next(e['tool_call'] for e in events if e['type']=='tool_call')
        self.assertEqual(call['arguments'],{'path':'README.md'})
        self.assertIn('tool_calls',[e['type'] for e in events])
        visible=[e for e in events if e['type'] not in ('history','message')]
        self.assertNotIn('private reasoning',str(visible))
        self.assertTrue(json.loads(connection.requests[0][1]['body'])['stream'])

    def test_claude_partial_text_excludes_thinking_deltas(self):
        self.assertEqual(normalize_cli('claude',{'type':'stream_event','event':{'delta':{'type':'thinking_delta','thinking':'private'}}}),[])
        text=normalize_cli('claude',{'type':'stream_event','event':{'delta':{'type':'text_delta','text':'Hello'}}})
        self.assertEqual(text[0]['text'],'Hello')
        self.assertTrue(text[0]['partial'])

    def test_codex_updated_message_and_safe_command_output(self):
        event=normalize_cli('codex',{'type':'item.updated','item':{'id':'a','type':'agent_message','text':'Working'}})[0]
        self.assertTrue(event['snapshot'])
        command=normalize_cli('codex',{'type':'item.completed','item':{'type':'command_execution','command':'npm test','aggregated_output':'3 tests passed'}})[0]
        self.assertEqual(command['output'],'3 tests passed')
        change=normalize_cli('codex',{'type':'item.completed','item':{'type':'file_change','changes':[{'path':'src/main.rs','kind':'update'}]}})[0]
        self.assertEqual(change['label'],'File changes')
        self.assertIn('src/main.rs',change['detail'])
