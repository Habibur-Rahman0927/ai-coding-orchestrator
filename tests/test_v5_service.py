"""Actual disposable local service lifecycle; no host service registration."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace import service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        try:
            with socket.socket() as probe:probe.bind(('127.0.0.1',0))
        except PermissionError as error:self.skipTest('Loopback unavailable: '+str(error))
        self.temp=tempfile.TemporaryDirectory(prefix='ccx-service-')
        self.base=Path(self.temp.name).resolve()
        self.store=Store(self.base/'private/workspace.sqlite3')
        self.processes=[]

    def tearDown(self):
        if not hasattr(self,'temp'):return
        service.stop(self.store)
        for process in self.processes:
            try:process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate();process.communicate(timeout=5)
        self.temp.cleanup()

    def launch(self,port=0):
        process=subprocess.Popen([sys.executable,'-B',str(ROOT/'engine/orchestrator.py'),
            'start','--database',str(self.store.path),'--port',str(port),'--no-browser'],
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.processes.append(process)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            result=service.status(self.store)
            if result.get('running'):return process,result
            if process.poll() is not None:self.fail('Startup failed: '+process.communicate()[1])
            time.sleep(.05)
        self.fail('Service did not become ready')

    def test_start_duplicate_health_browser_bootstrap_and_graceful_stop(self):
        process,status=self.launch()
        self.assertTrue(status['running']);self.assertTrue(status['url'].startswith('http://127.0.0.1:'))
        repeated=service.start(self.store,background=True,browser=False)
        self.assertTrue(repeated['existing']);self.assertEqual(repeated['url'],status['url'])
        link=service.request(self.store,'/api/service/browser',{})
        self.assertIn('#bootstrap=',link['url'])
        self.assertNotIn('token',json.dumps(status))
        record=service.private_read(service.paths(self.store)[0])
        stopped=service.stop(self.store);self.assertFalse(stopped['running'])
        out,err=process.communicate(timeout=10)
        self.assertEqual(process.returncode,0,err)
        self.assertNotIn(record['token'],out+err)
        self.assertNotIn(link['url'].split('#')[1],out+err)
        self.assertFalse(service.paths(self.store)[0].exists())

    def test_busy_port_uses_safe_alternative_and_stale_metadata_recovers(self):
        service.write_state(service.paths(self.store)[0],{'port':1,'pid':999999,'token':'stale','instance':'stale'})
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1',0));occupied.listen()
            port=occupied.getsockname()[1]
            process,result=self.launch(port)
            self.assertNotEqual(result['url'],'http://127.0.0.1:'+str(port))
            self.assertTrue(service.stop(self.store)['running'] is False)

    def test_explicit_background_and_restart_preserve_database(self):
        self.store.add_memory(None,'global','Preference','Keep project access explicit')
        result=service.start(self.store,port=0,background=True,browser=False)
        self.assertTrue(result['background'])
        first=service.private_read(service.paths(self.store)[0])['instance']
        service.stop(self.store)
        result=service.start(self.store,port=0,background=True,browser=False)
        self.assertTrue(result['running'])
        self.assertNotEqual(first,service.private_read(service.paths(self.store)[0])['instance'])
        self.assertEqual(self.store.memories(None)[0]['title'],'Preference')

    def test_reused_port_cannot_obtain_control_bearer(self):
        from http.server import BaseHTTPRequestHandler,HTTPServer
        import threading
        received=[]
        class UnrelatedApplication(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                received.append(dict(self.headers))
                self.rfile.read(int(self.headers.get('Content-Length','0')))
                data=b'{"proof":"invalid"}'
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        other=HTTPServer(('127.0.0.1',0),UnrelatedApplication)
        thread=threading.Thread(target=other.serve_forever,daemon=True);thread.start()
        try:
            service.write_state(service.paths(self.store)[0],{'port':other.server_address[1],'token':'private-control-value','instance':'old'})
            self.assertFalse(service.status(self.store)['running'])
            self.assertEqual(len(received),1)
            self.assertNotIn('Authorization',received[0])
        finally:other.shutdown();other.server_close();thread.join()
        service.paths(self.store)[0].unlink()

    def test_actual_backend_crash_keeps_unknown_action_without_duplicate_execution(self):
        from ccx_workspace.workflows import WorkflowEngine
        project=self.base/'project'
        subprocess.run(['git','init','-q',str(project)],check=True,capture_output=True)
        pid=self.store.register(project)['id'];engine=WorkflowEngine(self.store)
        flow=engine.create(pid,'Controlled crash',['Do not repeat the implementation'],providers={'planner':'codex','executor':'codex','reviewer':'claude'})
        engine.create_task(flow['id'],'Write marker once')
        engine.approve(flow['id'],'sharing',{'provider':'codex'})
        # Test-only injection. The production startup has no fake-provider flag.
        fixture='''import sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from ccx_workspace import server,service
from ccx_workspace.store import Store
class Offline:
 offline=True
 def status(self):return []
 def get(self,name):
  class Provider:
   def status(self):return {'capabilities':{}}
  return Provider()
 def invoke(self,name,request):
  target=Path(request['project'])/'counter.txt'
  target.write_text(str(int(target.read_text())+1) if target.exists() else '1')
  time.sleep(60)
server.registry_for=lambda store:Offline()
service.run(Store(sys.argv[2]),port=0,browser=False)
'''
        process=subprocess.Popen([sys.executable,'-B','-c',fixture,str(ROOT/'engine/lib'),str(self.store.path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.processes.append(process)
        deadline=time.monotonic()+10
        while not service.status(self.store).get('running') and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(service.status(self.store)['running'])
        service.request(self.store,'/api/workflows/'+flow['id']+'/run',{})
        marker=project/'counter.txt'
        while not marker.exists() and time.monotonic()<deadline:time.sleep(.05)
        self.assertTrue(marker.exists())
        process.kill();process.communicate(timeout=5)
        self.launch()
        service.request(self.store,'/api/workflows/'+flow['id']+'/run',{})
        deadline=time.monotonic()+5
        while engine.status(flow['id'])['status']!='RECOVERY_REQUIRED' and time.monotonic()<deadline:time.sleep(.05)
        self.assertEqual(engine.status(flow['id'])['status'],'RECOVERY_REQUIRED')
        self.assertEqual(marker.read_text(),'1')
        self.assertTrue(engine.status(flow['id'])['pending_actions'])


class ServiceMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ccx-service-security-')
        self.base=Path(self.temp.name).resolve();self.store=Store(self.base/'private/workspace.sqlite3')
    def tearDown(self):self.temp.cleanup()

    def test_browser_url_must_match_owned_loopback_origin(self):
        service.write_state(service.paths(self.store)[0],{'port':8765,'token':'x'*43,'instance':'owned'})
        for url in ('https://example.invalid/#bootstrap='+'x'*43,'http://127.0.0.1:9999/#bootstrap='+'x'*43,'http://127.0.0.1:8765/?token=bad'):
            with mock.patch.object(service,'request',return_value={'url':url}),mock.patch.object(service.webbrowser,'open') as opener:
                with self.assertRaises(ValueError):service.open_browser(self.store)
                opener.assert_not_called()

    @unittest.skipIf(os.name=='nt','POSIX mode exposure; Windows uses native ACL validation')
    def test_readable_control_metadata_is_refused(self):
        path=service.paths(self.store)[0]
        service.write_state(path,{'port':8765,'token':'private-value','instance':'owned'})
        path.chmod(0o644)
        with self.assertRaises(PermissionError):service.private_read(path)

    @unittest.skipUnless(hasattr(os,'mkfifo'),'Named-pipe fixture is Unix-only')
    def test_fifo_metadata_and_hardlinked_lock_refused(self):
        metadata,lock=service.paths(self.store)
        os.mkfifo(metadata,0o600)
        with self.assertRaises(PermissionError):service.private_read(metadata)
        metadata.unlink()
        original=self.base/'lock-source';original.write_text('');original.chmod(0o600)
        os.link(original,lock)
        with self.assertRaises(PermissionError):service.run(self.store,port=0,browser=False)


if __name__=='__main__':unittest.main(verbosity=2)
