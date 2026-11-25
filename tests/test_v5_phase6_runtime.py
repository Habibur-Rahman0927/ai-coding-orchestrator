"""An active V5 runtime must exclude global code replacement; no live providers."""
import sys
from pathlib import Path
import threading
import unittest
import test_v5_workflows as fixtures
import ccx_install as install
import json
import socket
import subprocess
import test_portable_install as portable_fixtures

class InstalledRuntimeTests(unittest.TestCase):
    setUp=portable_fixtures.PortableInstall.setUp
    tearDown=portable_fixtures.PortableInstall.tearDown
    command=portable_fixtures.PortableInstall.command

    def test_installed_backend_excludes_mutation_and_releases_on_stop(self):
        try:
            with socket.socket() as probe:probe.bind(('127.0.0.1',0))
        except PermissionError:self.skipTest('Host sandbox prohibits loopback binding')
        self.command('install')
        cli=[sys.executable,'-B',str(self.prefix/'orchestrator.py'),'workspace','--database',str(self.base/'custom database.sqlite3')]
        def workspace(*args):
            result=subprocess.run(cli+list(args),env=self.env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            return json.loads(result.stdout)
        try:
            self.assertTrue(workspace('start','--background','--no-browser','--port','0')['running'])
            self.assertTrue(workspace('status')['running'])
            self.command('install','--upgrade',expected=75)
            self.command('uninstall','--yes',expected=75)
            self.assertTrue(workspace('status')['running'])
        finally:
            workspace('stop')
        self.assertFalse(workspace('status')['running'])
        self.command('install','--upgrade')
        self.command('uninstall','--yes')

class RuntimeMutationTests(unittest.TestCase):
    setUp=fixtures.WorkflowTests.setUp
    tearDown=fixtures.WorkflowTests.tearDown
    create=fixtures.WorkflowTests.create
    authorize=fixtures.WorkflowTests.authorize
    def test_active_workflow_holds_shared_engine_lease_until_exit(self):
        identifier=self.create();self.authorize(identifier);registry=fixtures.MockRegistry();original=registry.invoke
        entered=threading.Event();release=threading.Event();results=[]
        def invoke(provider,request):
            if request['role']=='executor':
                entered.set()
                if not release.wait(10):raise RuntimeError('Test barrier expired')
            return original(provider,request)
        registry.invoke=invoke;worker=threading.Thread(target=lambda:results.append(self.engine.run(identifier,registry)))
        worker.start()
        try:
            self.assertTrue(entered.wait(5))
            with self.assertRaises(install.InstallError):
                with install.lock_engine(Path(install.__file__).resolve().parent.parent):pass
        finally:
            release.set();worker.join(10)
        self.assertFalse(worker.is_alive());self.assertEqual(results[0]['status'],'COMPLETED')
        with install.lock_engine(Path(install.__file__).resolve().parent.parent):pass
    def test_mutation_lock_refuses_new_workflow_before_dispatch(self):
        identifier=self.create();self.authorize(identifier);registry=fixtures.MockRegistry()
        with install.lock_engine(Path(install.__file__).resolve().parent.parent):
            with self.assertRaisesRegex(RuntimeError,'engine'):
                self.engine.run(identifier,registry)
        self.assertEqual(registry.calls,[]);self.assertEqual(self.engine.status(identifier)['status'],'READY')

if __name__=='__main__':unittest.main()
