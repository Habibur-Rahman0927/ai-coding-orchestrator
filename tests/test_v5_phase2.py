"""Phase 2 auth/onboarding/conversation security without real providers."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
from ccx_workspace.auth import BrowserAuth
from ccx_workspace.store import Store
from ccx_workspace.server import Dashboard, Handler
from ccx_workspace.onboarding import preview, save_setup, setup_state, doctor
from ccx_workspace.chat import Chat


class WireSocket:
    def __init__(self,data):self.input,self.output=io.BytesIO(data),io.BytesIO()
    def makefile(self,*args):return self.input
    def sendall(self,data):self.output.write(data)
    def settimeout(self,*args):pass


class LocalProvider:
    def __init__(self):self.requests=[]
    def execute(self,request):
        self.requests.append(request)
        yield {'type':'session','session_id':request.session_id or '00000000-0000-0000-0000-000000000001'}
        yield {'type':'text','text':'Reference-backed answer'}
        yield {'type':'usage','usage':{'input_tokens':12,'output_tokens':4}}
        yield {'type':'completed'}


class Registry:
    def __init__(self):self.provider=LocalProvider()
    def get(self,name):return self.provider
    def status(self):return [{'id':'codex','available':True,'connection_status':'authentication_unknown'}]


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ccx-phase2-')
        self.root=Path(self.temp.name).resolve()
        self.store=Store(self.root/'private/workspace.sqlite3')
        self.project=self.root/'project'
        subprocess.run(['git','init','-q',str(self.project)],check=True,capture_output=True)
        (self.project/'README.md').write_text('reference information for answer')
        self.pid=self.store.register(self.project)['id']
        self.registry=Registry()
        self.application=Dashboard(self.store,registry=self.registry)
        self.now=[1.0]
        self.auth=BrowserAuth(8765,clock=lambda:self.now[0],bootstrap_ttl=60,session_ttl=100)
        self.server=SimpleNamespace(application=self.application,token='a'*43,auth=self.auth,
            authorities={'127.0.0.1:8765'},server_address=('127.0.0.1',8765),instance='owned')

    def tearDown(self):
        self.application.close()
        self.temp.cleanup()

    def request(self,path,body=None,headers=None):
        method='POST' if body is not None else 'GET'
        payload=json.dumps(body).encode() if body is not None else b''
        fields={'Host':'127.0.0.1:8765'}
        if body is not None:fields.update({'Content-Type':'application/json','Content-Length':str(len(payload)),'Origin':'http://127.0.0.1:8765'})
        fields.update(headers or {})
        data=(method+' '+path+' HTTP/1.1\r\n'+''.join(k+': '+v+'\r\n' for k,v in fields.items())+'\r\n').encode()+payload
        wire=WireSocket(data);Handler(wire,('127.0.0.1',123),self.server)
        head,body=wire.output.getvalue().split(b'\r\n\r\n',1)
        parsed={}
        for line in head.decode().split('\r\n')[1:]:
            if ': ' in line:
                k,v=line.split(': ',1);parsed[k.lower()]=v
        return int(head.split()[1]),parsed,json.loads(body)

    def login(self):
        secret=self.auth.issue()
        code,headers,result=self.request('/api/auth/bootstrap',{'credential':secret})
        self.assertEqual(code,200)
        return secret,{'Cookie':headers['set-cookie'].split(';',1)[0],'X-CSRF-Token':result['csrf']}

    def test_single_use_bootstrap_cookie_expiration_logout_and_rotation(self):
        secret,headers=self.login()
        self.assertEqual(self.request('/api/auth/bootstrap',{'credential':secret})[0],401)
        self.assertEqual(self.request('/api/state',headers=headers)[0],200)
        self.assertEqual(self.request('/api/state',headers={'Cookie':headers['Cookie']})[0],403)
        self.assertEqual(self.request('/api/auth/session',headers={'Cookie':headers['Cookie']})[0],403)
        self.assertEqual(self.request('/api/auth/session',headers=headers)[2]['authenticated'],True)
        self.assertEqual(self.request('/api/auth/logout',{},headers)[0],200)
        self.assertEqual(self.request('/api/state',headers=headers)[0],401)
        _,headers=self.login();self.now[0]+=101
        self.assertEqual(self.request('/api/state',headers=headers)[0],401)
        old=self.auth.issue();self.now[0]+=61
        self.assertEqual(self.request('/api/auth/bootstrap',{'credential':old})[0],401)
        _,headers=self.login();self.auth.rotate()
        self.assertEqual(self.request('/api/state',headers=headers)[0],401)

    def test_csrf_origin_and_local_service_ownership(self):
        _,headers=self.login()
        self.assertEqual(self.request('/api/setup',{'step':2},{'Cookie':headers['Cookie']})[0],403)
        self.assertEqual(self.request('/api/setup',{'step':2},dict(headers,Origin='http://attacker.example'))[0],403)
        self.assertEqual(self.request('/api/service/stop',{},headers)[0],403)
        self.assertEqual(self.request('/api/service/health',headers={'Authorization':'Bearer '+'a'*43})[0],403)
        self.assertEqual(self.request('/api/setup',{'step':2},headers)[0],200)

    def test_setup_persistence_validation_and_explicit_project_preview(self):
        save_setup(self.store,{'step':6,'completed':True,'defaults':{'max_cost':1,'fallback_provider':'minimax'}})
        fresh=Store(self.store.path)
        self.assertTrue(setup_state(fresh,self.registry)['completed'])
        for invalid in ({'step':True},{'defaults':{'max_cost':float('nan')}},{'defaults':{'approval_policy':'allow_all'}}):
            with self.assertRaises(ValueError):save_setup(self.store,invalid)
        (self.project/'private.txt').write_text('private')
        result=preview(self.project,['private.txt'])
        self.assertFalse(result['indexed']);self.assertNotIn('private.txt',result['sample'])
        self.assertEqual(len(self.store.projects()),1)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM documents').fetchone()[0],0)
        report=doctor(self.store,self.registry,self.application.engine)
        self.assertEqual(report['database_integrity'],'ok')
        self.assertNotIn(str(self.store.path),json.dumps(report))

    def test_chat_requires_explicit_consent_uses_context_and_exact_session(self):
        chat=Chat(self.store,self.registry)
        try:
            item=chat.create(self.pid,'codex','Question')
            with self.assertRaises(PermissionError):chat.send(item['id'],{'content':'reference'})
            for unused in range(2):
                chat.send(item['id'],{'content':'reference','confirmed':True})
                deadline=time.monotonic()+5
                while chat.status(item['id'])['running'] and time.monotonic()<deadline:time.sleep(.01)
            result=chat.status(item['id'])
            self.assertEqual(result['status'],'IDLE');self.assertEqual(len(result['messages']),4)
            self.assertIn('Reference-backed',result['messages'][-1]['content'])
            self.assertIn('Untrusted reference',self.registry.provider.requests[0].prompt)
            self.assertEqual(self.registry.provider.requests[1].session_id,result['session_id'])
            self.assertNotIn('native_agent_write',self.registry.provider.requests[0].allowed_operations)
            self.assertEqual(self.application.engine.list(),[])
        finally:chat.close()

    def test_interrupted_chat_not_replayed_on_restart(self):
        chat=Chat(self.store,self.registry);item=chat.create(self.pid,'codex','Question')
        with self.store.connect() as db:db.execute("UPDATE chats SET status='RUNNING' WHERE id=?",(item['id'],))
        fresh=Chat(self.store,self.registry)
        self.assertEqual(fresh.status(item['id'])['status'],'RUNNING')
        fresh.reconcile_startup()
        self.assertEqual(fresh.status(item['id'])['status'],'INTERRUPTED')
        self.assertEqual(self.registry.provider.requests,[])

    def test_chat_rejects_session_collision_across_projects(self):
        chat=Chat(self.store,self.registry)
        first=chat.create(self.pid,'codex','First')
        chat._reserve_session(first['id'],'codex','00000000-0000-0000-0000-000000000001')
        other=self.root/'other'
        subprocess.run(['git','init','-q',str(other)],check=True,capture_output=True)
        second=chat.create(self.store.register(other)['id'],'codex','Second')
        with self.assertRaises(PermissionError):
            chat._reserve_session(second['id'],'codex','00000000-0000-0000-0000-000000000001')
        self.assertIsNone(chat.status(second['id'])['session_id'])

    def test_rotation_revokes_bearer_and_cookie(self):
        _,headers=self.login()
        self.assertEqual(self.request('/api/auth/rotate',{},headers)[0],200)
        self.assertEqual(self.request('/api/state',headers=headers)[0],401)
        self.assertEqual(self.request('/api/state',headers={'Authorization':'Bearer '+'a'*43})[0],401)

    def test_setup_defaults_apply_but_fallback_preferences_never_grant_access(self):
        save_setup(self.store,{'defaults':{'planner':'codex','executor':'codex','reviewer':'codex',
                                          'context_budget':300,'fallback_provider':'minimax','max_cost':1}})
        created=self.application.dispatch('POST','/api/workflows',{'project_id':self.pid,'objective':'Implement safely','criteria':['Tests pass']})
        self.assertEqual(created['providers'],{'planner':'codex','executor':'codex','reviewer':'codex'})
        self.assertEqual(created['budgets']['max_context_tokens'],300)
        self.assertEqual(len(created['approval_requests']),2)
        self.assertEqual(self.application.engine.approvals(created['id']),[])
        result=self.application.engine.run(created['id'],self.registry)
        self.assertEqual(result['status'],'APPROVAL_REQUIRED')
        self.assertEqual(self.registry.provider.requests,[])

    def test_mcp_verification_reports_changed_snapshot_as_stale(self):
        from test_v5_workflows import MockRegistry
        from ccx_workspace.mcp import Bridge
        engine=self.application.engine
        (self.project/'app.txt').write_text('good')
        flow=engine.create(self.pid,'Keep app correct',['app.txt contains good'],providers={'planner':'codex','executor':'codex','reviewer':'claude'})
        task=engine.create_task(flow['id'],'Check app')
        for provider in ('codex','claude'):engine.approve(flow['id'],'sharing',{'provider':provider})
        engine.approve(flow['id'],'command',{'name':'test','argv':[sys.executable,'-c','from pathlib import Path; assert Path("app.txt").read_text()=="good"']})
        self.assertEqual(engine.run(flow['id'],MockRegistry())['status'],'COMPLETED')
        bridge=Bridge(self.store,self.pid,engine=engine,registry=self.registry)
        arguments={'workflow_id':flow['id'],'task_id':task['id']}
        self.assertTrue(bridge.call('verify_task',arguments)['verified'])
        (self.project/'app.txt').write_text('changed after verification')
        result=bridge.call('verify_task',arguments)
        self.assertFalse(result['verified']);self.assertTrue(result['recorded_verified'])
        self.assertFalse(result['mutated'])


if __name__=='__main__':unittest.main(verbosity=2)
