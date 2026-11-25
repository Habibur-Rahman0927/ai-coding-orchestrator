import io
import contextlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.mcp import Bridge
class Engine:
    def status(self,wid):return {'id':wid,'project_id':wid}
class Registry:
    def discover(self):return [{'id':'codex','configured':False}]
class MCPTests(unittest.TestCase):
    def test_delegate_is_bound_to_selected_workflow_and_project(self):
        from ccx_workspace.workflows import WorkflowEngine
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
            engine=WorkflowEngine(store)
            one=engine.create(pid,'First objective',['Report findings'])
            two=engine.create(pid,'Second objective',['Report findings'])
            task=engine.create_task(one['id'],'Inspect code')
            other=engine.create_task(two['id'],'Other task')
            bridge=Bridge(store,pid,engine=engine,registry=Registry())
            with self.assertRaises(PermissionError):
                bridge.call('delegate_task',{'workflow_id':one['id'],'task_id':other['id'],'to_provider':'claude'})
            changed=bridge.call('delegate_task',{'workflow_id':one['id'],'task_id':task['id'],'to_provider':'claude'})
            self.assertEqual(changed['executor'],'claude')
            self.assertEqual(engine.approvals(one['id']),[])

    def test_cli_budget_delegate_failover_and_revoke_controls(self):
        from ccx_workspace.cli import main
        from ccx_workspace.workflows import WorkflowEngine
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
            def invoke(*args,expected=0):
                output,error=io.StringIO(),io.StringIO()
                with contextlib.redirect_stdout(output),contextlib.redirect_stderr(error):
                    code=main(['--database',str(store.path),'workflow',*args])
                self.assertEqual(code,expected,error.getvalue())
                return json.loads(output.getvalue()) if output.getvalue() else None
            workflow=invoke('create',pid,'Inspect project','--criterion','Report findings','--budgets','{"max_cost":2,"max_tokens":1000}')
            self.assertEqual(workflow['budgets']['max_tokens'],1000)
            task=invoke('task',workflow['id'],'Inspect code')
            self.assertEqual(invoke('delegate',task['id'],'claude')['executor'],'claude')
            invoke('failover',task['id'],'minimax','--yes',expected=1)
            approval=invoke('approve',workflow['id'],'failover',json.dumps({'task_id':task['id'],'to_provider':'minimax'}),'--yes')
            self.assertEqual(invoke('failover',task['id'],'minimax','--yes')['executor'],'minimax')
            invoke('revoke',workflow['id'],approval['id'],'--yes')
            self.assertTrue(WorkflowEngine(store).approvals(workflow['id'])[0]['revoked'])

    def test_malformed_params_refused_without_losing_session(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
            bridge=Bridge(store,pid,engine=Engine(),registry=Registry())
            bridge.message({'jsonrpc':'2.0','id':1,'method':'initialize'})
            for value in (None,[],42,'invalid'):
                result=bridge.message({'jsonrpc':'2.0','id':2,'method':'tools/call','params':value})
                self.assertEqual(result['error']['code'],-32602)
            result=bridge.message({'jsonrpc':'2.0','id':3,'method':'tools/call',
                                   'params':{'name':[], 'arguments':{}}})
            self.assertTrue(result['result']['isError'])
            self.assertIn('result',bridge.message({'jsonrpc':'2.0','id':4,'method':'ping'}))

    def test_mcp_and_cli_load_shared_provider_preferences(self):
        from ccx_workspace.settings import save_setting
        from ccx_workspace.cli import main
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
            save_setting(store,'providers',{'codex':{'model':'test-shared-model'}})
            bridge=Bridge(store,pid,engine=Engine())
            self.assertEqual(bridge.registry.config['codex']['model'],'test-shared-model')
            output=io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(['--database',str(store.path),'providers']),0)
            providers=json.loads(output.getvalue())
            self.assertEqual(next(p for p in providers if p['id']=='codex')['model'],'test-shared-model')

    def test_tools_require_initialization_and_cannot_grant_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
            bridge=Bridge(store,pid,engine=Engine(),registry=Registry())
            def request(method,params=None):return bridge.message({'jsonrpc':'2.0','id':1,'method':method,'params':params or {}})
            self.assertIn('error',request('tools/list'))
            self.assertEqual(request('initialize')['result']['protocolVersion'],'2025-11-25')
            tools=request('tools/list')['result']['tools']
            self.assertNotIn('approve',[t['name'] for t in tools])
            result=request('tools/call',{'name':'approve','arguments':{'actor':'user'}})
            self.assertTrue(result['result']['isError'])
            result=request('tools/call',{'name':'get_workflow_status','arguments':{'workflow_id':'other-project'}})
            self.assertTrue(result['result']['isError'])
            result=request('tools/call',{'name':'get_project_context','arguments':{'query':'x','project_id':'other'}})
            self.assertTrue(result['result']['isError'])
            result=request('tools/call',{'name':'discover_providers','arguments':{}})
            self.assertFalse(result['result']['isError'])
if __name__=='__main__':unittest.main()
