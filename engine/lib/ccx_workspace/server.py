"""Authenticated loopback dashboard. No cloud hosting or third-party web stack."""
import sys
sys.dont_write_bytecode = True

import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit
from .settings import registry_for, setting, save_setting

MAX_BODY = 65536
WEB = Path(__file__).with_name('web')


class DashboardError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class Dashboard:
    def __init__(self, store, engine=None, registry=None):
        self.store = store
        if registry is None:
            registry = registry_for(store)
        if engine is None:
            from .workflows import WorkflowEngine
            engine = WorkflowEngine(store)
        self.engine, self.registry = engine, registry
        self.jobs = {}
        self.errors = {}
        self.guard = threading.Lock()

    def setting(self, key, default=None):
        return setting(self.store, key, default)

    def save_setting(self, key, value):
        save_setting(self.store, key, value)

    def workflow_status(self, workflow_id):
        value = self.engine.status(workflow_id)
        value['events'] = self.engine.checkpoints(workflow_id)
        value['approvals'] = self.engine.approvals(workflow_id)
        value['usage'] = {'recorded_tokens': value.get('tokens_used'),
                          'recorded_cost': value.get('cost_used'),
                          'note': 'Recorded totals only; provider omissions are not a zero-cost guarantee.'}
        value['runner_error'] = self.errors.get(workflow_id)
        value['runner_active'] = workflow_id in self.jobs
        return value

    def run(self, workflow_id):
        self.engine.status(workflow_id)
        with self.guard:
            if workflow_id in self.jobs:
                raise DashboardError('This workflow already has a runner.', 409)
            if len(self.jobs) >= 4:
                raise DashboardError('Four workflow runners are already active.', 409)
            self.jobs[workflow_id] = True
            self.errors.pop(workflow_id, None)

        def execute():
            try:
                self.engine.run(workflow_id, self.registry)
            except Exception:
                # Provider and workflow modules own durable, redacted failure events.
                # Never log exceptions containing agent prompts or credentials here.
                self.errors[workflow_id] = 'Runner stopped unexpectedly; inspect the last persisted checkpoint before retrying.'
            finally:
                with self.guard:
                    self.jobs.pop(workflow_id, None)
        threading.Thread(target=execute, name='ccx-workflow', daemon=True).start()
        return {'accepted': True, 'workflow_id': workflow_id}

    def dispatch(self, method, path, body):
        parts = path.strip('/').split('/')
        if method == 'GET' and path == '/api/state':
            return {'projects': self.store.projects(), 'machine': self.store.machine(),
                    'workflows': self.engine.list(), 'providers': self.registry.status(),
                    'running': list(self.jobs), 'settings': {'host': 'loopback',
                    'authentication': 'bearer token', 'provider_config': self.setting('providers', {})}}
        if path == '/api/projects':
            if method == 'GET':
                return self.store.projects()
            if method == 'POST':
                exclusions = body.get('exclusions', [])
                if (not isinstance(exclusions, list) or len(exclusions) > 100
                        or not all(isinstance(item, str) and item.strip() and '\x00' not in item
                                   and len(item) <= 1000 for item in exclusions)):
                    raise DashboardError('Exclusions must be a list of at most 100 nonempty path patterns.')
                return self.store.register(required(body, 'path'), exclusions=exclusions)
        if method == 'POST' and path == '/api/machine/refresh':
            return self.store.machine(refresh=True)
        if len(parts) == 4 and parts[:2] == ['api', 'projects']:
            project, action = parts[2:]
            self.store.project(project)
            if method == 'GET' and action == 'memories':
                return self.store.memories(project)
            if method == 'GET' and action == 'export':
                return self.store.export_memory(project)
            if method == 'POST' and action == 'index':
                return self.store.index(project)
            if method == 'POST' and action == 'search':
                return self.store.search(project, required(body, 'query'), scope=body.get('scope'),
                                         limit=bounded_int(body.get('limit', 10), 1, 100))
            if method == 'POST' and action == 'context':
                critical = body.get('critical', [])
                if not isinstance(critical, list) or not all(isinstance(x, str) for x in critical):
                    raise DashboardError('Critical context must be a list of strings.')
                return self.store.context(project, required(body, 'query'),
                                          budget=bounded_int(body.get('budget', 2000), 100, 32000),
                                          critical=critical)
            if method == 'POST' and action == 'delete-memory':
                return self.store.delete_memory(required(body, 'id'), project)
            if method == 'POST' and action == 'remember':
                return self.store.add_memory(project, body.get('scope', 'project'),
                    required(body, 'title'), required(body, 'body'), kind='user_instruction')
        if method == 'POST' and path == '/api/workflows':
            return self.engine.create(required(body, 'project_id'), required(body, 'objective'),
                                      body.get('criteria', []), providers=body.get('providers'),
                                      budgets=body.get('budgets'))
        if len(parts) == 3 and parts[:2] == ['api', 'workflows'] and method == 'GET':
            return self.workflow_status(parts[2])
        if len(parts) == 4 and parts[:2] == ['api', 'workflows']:
            workflow, action = parts[2:]
            if method == 'GET' and action == 'checkpoints':
                return self.engine.checkpoints(workflow)
            if method == 'GET' and action == 'export':
                return self.workflow_status(workflow)
            if method == 'POST':
                if action == 'run':
                    return self.run(workflow)
                if action in ('pause', 'resume', 'cancel'):
                    return getattr(self.engine, action)(workflow)
                if action == 'approve':
                    scope = body.get('scope')
                    if not isinstance(scope, dict):
                        raise DashboardError('Approval scope must be an object.')
                    return self.engine.approve(workflow, required(body, 'kind'), scope, actor='user')
                if action == 'revoke':
                    return self.engine.revoke(workflow, required(body, 'approval_id'), actor='user')
                if action == 'tasks':
                    return self.engine.create_task(workflow, required(body, 'title'),
                        description=body.get('description', ''), parent_id=body.get('parent_id'),
                        executor=body.get('executor'), reviewer=body.get('reviewer'))
        if len(parts) == 4 and parts[:2] == ['api', 'tasks'] and method == 'POST':
            if parts[3] == 'delegate':
                return self.engine.delegate(parts[2], required(body, 'to_provider'), body.get('from_provider'))
            if parts[3] == 'failover':
                return self.engine.failover(parts[2], required(body, 'to_provider'), actor='user')
        if len(parts) == 4 and parts[:2] == ['api', 'providers'] and method == 'POST':
            provider, action = parts[2:]
            if action == 'probe':
                return self.registry.probe(provider)
            if action == 'configure':
                configuration = body.get('config')
                if not isinstance(configuration, dict):
                    raise DashboardError('Provider configuration must be an object.')
                with self.guard:
                    sanitized = self.registry.configure(provider, configuration)
                    configurations = self.setting('providers', {})
                    configurations[provider] = sanitized
                    self.save_setting('providers', configurations)
                return sanitized
        raise DashboardError('Endpoint not found.', 404)


def required(body, name):
    value = body.get(name)
    if not isinstance(value, str) or not value.strip():
        raise DashboardError(name + ' must be a nonempty string.')
    return value.strip()


def bounded_int(value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DashboardError('Numeric value is outside the permitted range.')
    return value


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'LocalWorkspace'
    sys_version = ''

    def log_message(self, *args):
        pass  # Do not log paths, bearer tokens, prompts, or local filenames.

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def send_data(self, status, data, content_type='application/json; charset=utf-8'):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8') if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; "
                         "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(payload)

    def handle_request(self):
        try:
            authorities = self.server.authorities
            hosts = self.headers.get_all('Host', [])
            if len(hosts) != 1 or hosts[0] not in authorities:
                raise DashboardError('Invalid local Host header.', 403)
            origins = self.headers.get_all('Origin', [])
            if len(origins) > 1:
                raise DashboardError('Duplicate Origin headers are refused.', 403)
            origin = origins[0] if origins else None
            if origin and origin not in {'http://' + host for host in authorities}:
                raise DashboardError('Cross-origin requests are refused.', 403)
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                raise DashboardError('Cross-site requests are refused.', 403)
            parsed = urlsplit(self.path)
            if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
                raise DashboardError('Use a local path without query parameters.')
            path = parsed.path
            if self.command == 'GET' and path in ('/', '/index.html', '/app.js', '/style.css'):
                name = 'index.html' if path == '/' else path[1:]
                mime = {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8',
                        'style.css': 'text/css; charset=utf-8'}[name]
                return self.send_data(200, (WEB / name).read_bytes(), mime)
            auth = self.headers.get_all('Authorization', [])
            expected = 'Bearer ' + self.server.token
            if len(auth) != 1 or not hmac.compare_digest(auth[0].encode(), expected.encode()):
                raise DashboardError('Enter the dashboard token to continue.', 401)
            body = {}
            if self.command == 'POST':
                if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                    raise DashboardError('A single Content-Length is required.', 411)
                length = int(self.headers['Content-Length'])
                if length < 0 or length > MAX_BODY:
                    raise DashboardError('Request exceeds the 64 KiB limit.', 413)
                if self.headers.get_content_type() != 'application/json':
                    raise DashboardError('Content-Type must be application/json.', 415)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise DashboardError('Incomplete request body.')
                body = json.loads(raw.decode('utf-8'))
                if not isinstance(body, dict):
                    raise DashboardError('JSON body must be an object.')
            result = self.server.application.dispatch(self.command, path, body)
            return self.send_data(200, result if isinstance(result, (dict, list)) else {'result': result})
        except DashboardError as error:
            self.send_data(error.status, {'error': str(error)})
        except (ValueError, TypeError, KeyError) as error:
            self.send_data(400, {'error': 'Invalid request. Check the selected record and field values.'})
        except PermissionError:
            self.send_data(403, {'error': 'The operation was refused by the local security policy.'})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            self.close_connection = True
        except Exception:
            self.send_data(500, {'error': 'Operation failed. Inspect local workflow status for details.'})

    do_GET = handle_request
    do_POST = handle_request

    def do_OPTIONS(self):
        self.send_data(405, {'error': 'Cross-origin access is not supported.'})


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16

    def __init__(self, *args, **kwargs):
        self.connections = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.connections.release()


def create_server(store, host='127.0.0.1', port=0, token=None, engine=None, registry=None):
    if host not in ('127.0.0.1', 'localhost'):
        raise ValueError('Dashboard must bind to IPv4 loopback (127.0.0.1 or localhost).')
    if token is not None and (not isinstance(token, str) or len(token) < 32):
        raise ValueError('Dashboard tokens must contain at least 32 characters.')
    if token is not None and not all(c.isascii() and (c.isalnum() or c in '-_') for c in token):
        raise ValueError('Dashboard tokens must use URL-safe ASCII characters.')
    server = LocalServer(('127.0.0.1', port), Handler)
    server.token = token or secrets.token_urlsafe(32)
    actual_port = server.server_address[1]
    server.authorities = {'127.0.0.1:' + str(actual_port), 'localhost:' + str(actual_port)}
    try:
        server.application = Dashboard(store, engine, registry)
    except BaseException:
        server.server_close()
        raise
    return server


def serve(store, host='127.0.0.1', port=8765):
    import ccx_platform
    server = create_server(store, host, port)
    directory = Path(store.path).parent
    token_file = directory / ('dashboard-' + str(server.server_address[1]) + '.token')
    try:
        ccx_platform.secure_mkdir(directory, parents=True, exist_ok=True)
        # Exclusive creation refuses a pre-existing token or link.
        with token_file.open('x', encoding='utf-8') as output:
            ccx_platform.secure_mode(token_file, 0o600)
            output.write(server.token)
        print('Dashboard: http://127.0.0.1:' + str(server.server_address[1]), flush=True)
        print('Read the private token file and paste it into the dashboard: ' + str(token_file), flush=True)
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if token_file.is_file() and not ccx_platform.is_link(token_file):
            if token_file.read_text(encoding='utf-8') == server.token:
                token_file.unlink()
