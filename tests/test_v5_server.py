"""Dashboard contracts and HTTP security, with no live agent or remote API calls."""
import sys
sys.dont_write_bytecode = True
import ctypes
import http.client
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.server import Dashboard, Handler, MAX_BODY, create_server
from ccx_workspace.settings import registry_for
from ccx_workspace.store import Store


class Socket:
    """Run the actual HTTP parser against bounded in-memory request bytes."""
    def __init__(self, request):
        self.input, self.output = io.BytesIO(request), io.BytesIO()
    def makefile(self, mode, *args):
        return self.input
    def sendall(self, data):
        self.output.write(data)
    def settimeout(self, value):
        pass


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-dashboard-')
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / 'private/workspace.sqlite3')
        self.project = self.base / 'project'
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True, capture_output=True)
        (self.project / 'hello.py').write_text('def greet():\n    return "hello"\n', encoding='utf-8')
        self.application = Dashboard(self.store)
        self.token = 'x' * 43
        self.server = SimpleNamespace(application=self.application, token=self.token,
                                      authorities={'127.0.0.1:8765', 'localhost:8765'})

    def tearDown(self):
        self.temp.cleanup()

    def request(self, path, body=None, auth=True, extra=None, raw=None):
        method = 'POST' if body is not None or raw is not None else 'GET'
        payload = raw if raw is not None else json.dumps(body).encode() if body is not None else b''
        headers = {'Host': '127.0.0.1:8765'}
        if auth:
            headers['Authorization'] = 'Bearer ' + self.token
        if method == 'POST':
            headers.update({'Content-Type':'application/json', 'Content-Length':str(len(payload))})
        headers.update(extra or {})
        wire = (method + ' ' + path + ' HTTP/1.1\r\n'
                + ''.join(key + ': ' + value + '\r\n' for key,value in headers.items())
                + '\r\n').encode() + payload
        socket = Socket(wire)
        Handler(socket, ('127.0.0.1', 12345), self.server)
        head, data = socket.output.getvalue().split(b'\r\n\r\n', 1)
        code = int(head.split(b' ')[1])
        return code, head, json.loads(data) if b'application/json' in head else data

    def test_auth_and_cross_origin_boundaries(self):
        self.assertEqual(self.request('/api/state', auth=False)[0], 401)
        self.assertEqual(self.request('/api/state', extra={'Authorization':'Bearer wrong'})[0], 401)
        self.assertEqual(self.request('/api/state', extra={'Host':'attacker.example'})[0], 403)
        self.assertEqual(self.request('/api/state', extra={'Origin':'https://attacker.example'})[0], 403)
        self.assertEqual(self.request('/api/state', extra={'Sec-Fetch-Site':'cross-site'})[0], 403)
        self.assertEqual(self.request('/api/state?token=hidden')[0], 400)
        code, headers, state = self.request('/api/state', extra={'Origin':'http://127.0.0.1:8765'})
        self.assertEqual(code, 200)
        self.assertNotIn(b'Access-Control-Allow-Origin', headers)
        self.assertIn(b"frame-ancestors 'none'", headers)
        self.assertNotIn(self.token, json.dumps(state))

    def test_json_and_request_size_boundaries(self):
        self.assertEqual(self.request('/api/projects', {}, extra={'Content-Type':'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/projects', raw=b'{invalid')[0], 400)
        self.assertEqual(self.request('/api/projects', raw=b'[]')[0], 400)
        self.assertEqual(self.request('/api/projects', {}, extra={'Content-Length':str(MAX_BODY+1)})[0], 413)
        self.assertEqual(self.request('/api/projects', {}, extra={'Transfer-Encoding':'chunked'})[0], 411)

    def test_project_index_memory_context_and_export(self):
        (self.project/'skip.py').write_text('neverindexmarker = True\n',encoding='utf-8')
        code, _, project = self.request('/api/projects', {'path':str(self.project),'exclusions':['skip.py']})
        self.assertEqual(code, 200)
        self.assertEqual(self.request('/api/projects', {'path':str(self.project),'exclusions':'not-a-list'})[0],400)
        base = '/api/projects/' + project['id']
        self.assertEqual(self.request(base+'/index', {})[0], 200)
        self.assertEqual(self.request(base+'/search', {'query':'neverindexmarker'})[2],[])
        code, _, memory = self.request(base+'/remember', {'title':'A rule', 'body':'Use small functions.', 'scope':'project'})
        self.assertEqual(code, 200)
        self.assertEqual(self.request(base+'/memories')[2][0]['id'], memory['id'])
        self.assertEqual(self.request(base+'/search', {'query':'greet'})[0], 200)
        context = self.request(base+'/context', {'query':'greet','critical':['Keep this instruction'],'budget':300})
        self.assertEqual(context[0], 200)
        self.assertIn('Keep this instruction', context[2]['content'])
        self.assertEqual(len(self.request(base+'/export')[2]['records']), 1)
        self.assertEqual(self.request(base+'/delete-memory', {'id':memory['id']})[0], 200)

    def test_workflow_control_and_exact_approval_scope(self):
        project = self.store.register(self.project)
        code, _, workflow = self.request('/api/workflows', {'project_id':project['id'],
            'objective':'Document greet', 'criteria':['Tests pass']})
        self.assertEqual(code, 200)
        base = '/api/workflows/' + workflow['id']
        self.assertEqual(self.request(base+'/tasks', {'title':'Read greet','description':'Inspect behavior'})[0], 200)
        self.assertEqual(self.request(base+'/pause', {})[0], 200)
        self.assertEqual(self.request(base+'/resume', {})[0], 200)
        scope = {'provider':'codex'}
        code, _, approval = self.request(base+'/approve', {'kind':'sharing','scope':scope})
        self.assertEqual(code, 200)
        self.assertEqual(approval['scope'], scope)
        self.assertEqual(self.request(base+'/approve', {'kind':'sharing','scope':'all'})[0], 400)
        status = self.request(base)[2]
        self.assertTrue(status['tasks'])
        self.assertTrue(status['events'])
        self.assertEqual(status['approvals'][0]['actor'], 'user')
        self.assertEqual(self.request(base+'/revoke', {'approval_id':approval['id']})[0], 200)
        self.assertEqual(self.request(base+'/checkpoints')[0], 200)
        self.assertEqual(self.request(base+'/cancel', {})[0], 200)

    def test_provider_preferences_shared_without_credentials(self):
        config = {'model':'test-model'}
        self.assertEqual(self.request('/api/providers/codex/configure', {'config':config})[0], 200)
        self.assertEqual(registry_for(self.store).config['codex'], config)
        self.assertEqual(self.request('/api/providers/minimax/configure', {'config':{'api_key':'secret-value'}})[0], 400)
        self.assertFalse(self.request('/api/providers/codex/probe', {})[2]['live_connection_tested'])

    def test_background_runner_deduplicates_and_stops_at_approval_gate(self):
        project = self.store.register(self.project)
        workflow = self.application.engine.create(project['id'], 'Inspect project', ['Report findings'])
        identifier = workflow['id']
        base = '/api/workflows/' + identifier
        started, release = threading.Event(), threading.Event()
        def controlled_run(*args):
            started.set()
            release.wait(3)
        try:
            with mock.patch.object(self.application.engine, 'run', side_effect=controlled_run):
                self.assertEqual(self.request(base+'/run', {})[0], 200)
                self.assertTrue(started.wait(2))
                self.assertEqual(self.request(base+'/run', {})[0], 409)
                release.set()
                deadline = time.monotonic()+3
                while self.application.jobs and time.monotonic()<deadline:
                    time.sleep(.01)
                self.assertFalse(self.application.jobs)
        finally:
            release.set()
        self.assertEqual(self.request(base+'/run', {})[0], 200)
        deadline = time.monotonic()+3
        while self.application.jobs and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertFalse(self.application.jobs)
        status = self.request(base)[2]
        self.assertEqual(status['status'], 'APPROVAL_REQUIRED')
        self.assertIn('approval', status['reason'].lower())

    def test_static_assets_no_secret_bootstrap_or_path_traversal(self):
        for path in ('/', '/app.js', '/style.css'):
            code, headers, body = self.request(path, auth=False)
            self.assertEqual(code, 200)
            self.assertNotIn(self.token.encode(), body)
            self.assertIn(b'no-store', headers)
        self.assertEqual(self.request('/../server.py')[0], 404)
        script = (ROOT/'engine/lib/ccx_workspace/web/app.js').read_text()
        self.assertNotIn('innerHTML', script)
        self.assertNotIn('localStorage', script)

    def test_non_loopback_binding_refused_before_socket_creation(self):
        for host in ('0.0.0.0', '::', '192.168.1.1', 'example.com'):
            with self.assertRaises(ValueError):
                create_server(self.store, host=host)

    def test_actual_loopback_http_when_permitted(self):
        try:
            server = create_server(self.store, token=self.token)
        except PermissionError as error:
            self.skipTest('Sandbox denies loopback listening: ' + str(error))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1], timeout=3)
            connection.request('GET', '/api/state', headers={'Authorization':'Bearer '+self.token})
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn('projects', json.loads(response.read()))
            connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


class JavaScriptSyntax(unittest.TestCase):
    def test_dashboard_javascript_parses(self):
        path = ROOT/'engine/lib/ccx_workspace/web/app.js'
        if shutil.which('node'):
            result = subprocess.run(['node','--check',str(path)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        elif sys.platform == 'darwin':
            library = ctypes.CDLL('/System/Library/Frameworks/JavaScriptCore.framework/JavaScriptCore')
            library.JSGlobalContextCreate.argtypes = [ctypes.c_void_p]
            library.JSGlobalContextCreate.restype = ctypes.c_void_p
            library.JSStringCreateWithUTF8CString.argtypes = [ctypes.c_char_p]
            library.JSStringCreateWithUTF8CString.restype = ctypes.c_void_p
            library.JSCheckScriptSyntax.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)]
            library.JSCheckScriptSyntax.restype = ctypes.c_bool
            library.JSStringRelease.argtypes = [ctypes.c_void_p]
            library.JSGlobalContextRelease.argtypes = [ctypes.c_void_p]
            context = library.JSGlobalContextCreate(None)
            script = library.JSStringCreateWithUTF8CString(path.read_bytes())
            try:
                exception = ctypes.c_void_p()
                self.assertTrue(library.JSCheckScriptSyntax(context,script,None,1,ctypes.byref(exception)), 'Dashboard JavaScript syntax error')
            finally:
                library.JSStringRelease(script)
                library.JSGlobalContextRelease(context)
        else:
            self.skipTest('No installed JavaScript parser is available')


if __name__ == '__main__':
    unittest.main()
