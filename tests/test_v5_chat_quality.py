"""Grounded read-only chat, per-message options and safe provider argument mapping."""
import json
from pathlib import Path
import time
import unittest
from unittest import mock
import uuid
import test_v5_phase2 as fixtures
from ccx_workspace.chat import Chat
from ccx_workspace.providers import CLIProvider, ProviderRequest, validate_chat_options


class ChatQuality(unittest.TestCase):
    setUp = fixtures.Phase2Tests.setUp
    tearDown = fixtures.Phase2Tests.tearDown

    def send(self, **options):
        chat = self.application.chat
        item = chat.create(self.pid, 'codex', 'Project question')
        chat.send(item['id'], {'content': 'amar backend ki diye banano?', 'confirmed': True, **options})
        deadline = time.monotonic()+5
        while chat.status(item['id'])['running'] and time.monotonic()<deadline:
            time.sleep(.01)
        result = chat.status(item['id'])
        self.assertEqual(result['status'], 'IDLE')
        return result

    def test_broad_question_has_inventory_manifest_sources_and_grounding_rules(self):
        (self.project/'pyproject.toml').write_text('[project]\nname="sample"\ndependencies=["fastapi"]\n')
        (self.project/'app.py').write_text('from fastapi import FastAPI\napp = FastAPI()\n')
        (self.project/'.env').write_text('do not expose this file')
        result = self.send(model='test-model', effort='high')
        request = self.registry.provider.requests[-1]
        payload = json.loads(request.prompt)
        evidence = payload['project_evidence']
        self.assertEqual(evidence['extensions']['.py'], 1)
        self.assertNotIn('.env', evidence['sample_paths'])
        self.assertIn('fastapi', json.dumps(evidence['manifest_excerpts']))
        self.assertIn('Never invent citations', payload['rules'])
        self.assertIn('user-pasted examples', payload['rules'])
        self.assertIn('Do not edit files', payload['rules'])
        self.assertEqual((request.model, request.effort), ('test-model','high'))
        self.assertEqual((result['model'],result['effort']), ('test-model','high'))
        metadata = result['messages'][-1]['metadata']
        self.assertIn('pyproject.toml', [r['source'] for r in metadata['sources']])
        self.assertEqual(metadata['requested_model'], 'test-model')
        self.assertNotIn('native_agent_write', request.allowed_operations)
        self.assertEqual(Chat(self.store,self.registry).status(result['id'])['effort'], 'high')

    def test_exact_resume_can_change_requested_model_and_reset_effort(self):
        first = self.send(model='one',effort='high')
        chat = self.application.chat
        chat.send(first['id'], {'content':'Next question','confirmed':True,'model':'two','effort':None})
        deadline=time.monotonic()+5
        while chat.status(first['id'])['running'] and time.monotonic()<deadline:time.sleep(.01)
        request=self.registry.provider.requests[-1]
        self.assertEqual(request.session_id, first['session_id'])
        self.assertEqual(request.model,'two');self.assertIsNone(request.effort)
        self.assertEqual(chat.status(first['id'])['messages'][1]['metadata']['requested_model'],'one')

    def test_invalid_settings_reject_before_message_or_provider_call(self):
        item=self.application.chat.create(self.pid,'codex','Question')
        for changes in ({'model':'--bad'}, {'effort':'invalid'}, {'model':123}):
            with self.assertRaises(ValueError):
                self.application.chat.send(item['id'],dict(content='Question',confirmed=True,**changes))
        self.assertEqual(self.application.chat.status(item['id'])['messages'],[])
        self.assertEqual(self.registry.provider.requests,[])
        with self.assertRaises(ValueError):validate_chat_options('minimax',None,'high')
        with self.assertRaises(ValueError):validate_chat_options('claude',None,'ultra')

    def test_provider_arguments_include_options_on_initial_and_resume(self):
        for provider in ('codex','claude'):
            for session in (None,str(uuid.uuid4())):
                request=ProviderRequest(project=self.project,prompt='hello',model='test-model',effort='high',
                                        session_id=session,allowed_operations=['native_agent_access'])
                command=CLIProvider(provider).command(request)
                self.assertEqual(command[command.index('--model')+1],'test-model')
                if provider=='codex':self.assertIn('model_reasoning_effort="high"',command)
                else:self.assertEqual(command[command.index('--effort')+1],'high')
                if session:self.assertIn(session,command)
                self.assertNotIn('workspace-write',command)

    def test_options_cache_is_bounded_validated_and_local(self):
        cache=self.root/'model-metadata';cache.mkdir()
        (cache/'models_cache.json').write_text(json.dumps({'models':[{'slug':'test-model'}, {'slug':'--bad'}]}))
        registry=mock.Mock();registry.get.return_value.status.return_value={}
        chat=Chat(self.store,registry)
        with mock.patch.dict('os.environ', {'CODEX_HOME':str(cache)}):
            result=chat.options('codex')
            self.assertEqual(result['models'],['test-model'])
        self.assertEqual(chat.options('minimax')['efforts'],[])
        self.assertIn('sonnet',chat.options('claude')['models'])
        registry.get.return_value.execute.assert_not_called()

    def test_old_conversations_migrate_without_losing_messages(self):
        store=fixtures.Store(self.root/'old/workspace.sqlite3')
        with store.connect() as db:
            db.executescript("""CREATE TABLE chats(
                id TEXT PRIMARY KEY,project_id TEXT NOT NULL,provider TEXT NOT NULL,title TEXT NOT NULL,
                status TEXT NOT NULL,session_id TEXT,history TEXT NOT NULL DEFAULT '[]',updated_at REAL NOT NULL);
                CREATE TABLE chat_messages(id TEXT PRIMARY KEY,chat_id TEXT NOT NULL,role TEXT NOT NULL,
                content TEXT NOT NULL,usage TEXT NOT NULL DEFAULT '{}',created_at REAL NOT NULL);
                INSERT INTO chats VALUES('old-chat','project','codex','Old question','IDLE',NULL,'[]',1);
                INSERT INTO chat_messages VALUES('old-message','old-chat','assistant','Saved answer','{}',1);""")
        Chat(store,self.registry)
        migrated=Chat(store,self.registry).status('old-chat')
        self.assertEqual(migrated['messages'][0]['content'],'Saved answer')
        self.assertEqual(migrated['messages'][0]['metadata'],{})
        self.assertIsNone(migrated['model']);self.assertIsNone(migrated['effort'])

    def test_task_endpoint_forwards_settings_and_deduplicates(self):
        body={'project_id':self.pid,'provider':'codex','content':'question','confirmed':True,
              'idempotency_key':uuid.uuid4().hex,'model':'test-model','effort':'medium'}
        first=self.application.tasks.message(body)
        second=self.application.tasks.message(body)
        self.assertEqual(first['chat_id'],second['chat_id'])
        deadline=time.monotonic()+5
        while self.application.chat.status(first['chat_id'])['running'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(len(self.registry.provider.requests),1)
        request=self.registry.provider.requests[0]
        self.assertEqual((request.model,request.effort),('test-model','medium'))
