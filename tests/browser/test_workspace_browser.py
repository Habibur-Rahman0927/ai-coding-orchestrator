"""Real Chromium interaction checks against the actual local API/SQLite engine.

Optional test dependency: playwright in an isolated environment. Uses installed
Chrome, a fresh browser context, temporary projects, and deterministic providers.
Never uses a user's browser profile, provider account, or network API.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.server import create_server
from ccx_workspace.store import Store
from ccx_workspace.settings import save_setting
from ccx_workspace.onboarding import DEFAULTS

try:
    from playwright.sync_api import sync_playwright, expect
except ImportError:
    sync_playwright = None


class BrowserRegistry:
    offline = True
    def __init__(self):
        self.config = {}
        self.calls = []
        self.requests = []
        self.delay = 0.3
        self.executions = 0
    def status(self):
        return [{'id': name, 'available': True, 'configured': True,
                 'connection_status': 'Authentication unknown',
                 'capabilities': {'scoped_tools': True}, 'model': self.config.get(name, {}).get('model')}
                for name in ('codex', 'claude', 'minimax')]
    discover = status
    def get(self, name):
        registry = self
        class Provider:
            def status(self):
                return next(p for p in registry.status() if p['id'] == name)
            def execute(self, request):
                registry.calls.append((name, request.role))
                registry.requests.append(request)
                session=request.session_id or str(uuid.uuid4())
                yield {'type':'session','session_id':session}
                yield {'type':'activity','label':'Reading project files','phase':'running','detail':'README.md'}
                for index,chunk in enumerate(('A deterministic ', 'standalone reply.')):
                    if request.cancel_event and request.cancel_event.is_set():
                        yield {'type':'cancelled'}
                        return
                    time.sleep(.2 if index==0 else 2)
                    yield {'type':'text','text':chunk}
                yield {'type':'usage','usage':{'input_tokens':20,'output_tokens':10}}
                yield {'type':'completed'}
        return Provider()
    def configure(self, name, config):
        self.config[name] = dict(config)
        return dict(config)
    def probe(self, name):
        return self.get(name).status()
    def invoke(self, provider, request):
        self.calls.append((provider, request['role']))
        if request.get('event_callback'):
            request['event_callback']({'type':'text','text':'Browser fixture is working'})
            request['event_callback']({'type':'activity','label':'Inspecting project','phase':'completed','detail':'app.txt'})
        cancel = request.get('cancel_event')
        deadline = time.monotonic() + self.delay
        while time.monotonic() < deadline:
            if cancel and cancel.is_set():
                return {'status': 'cancelled', 'output': '', 'usage': {}}
            time.sleep(.02)
        prompt = json.loads(request['prompt'])
        result = {'status': 'completed', 'session_id': request.get('session_id') or str(uuid.uuid4()),
                  'usage': {'input_tokens': 20, 'output_tokens': 10}, 'output': ''}
        if request['role'] == 'planner':
            result['output'] = json.dumps({'tasks': [{'title': 'Correct the application'}]})
        elif request['role'] == 'executor':
            self.executions += 1
            path = Path(request['project']) / 'app.txt'
            if path.read_text() == 'bad':
                result.update(status='tool_calls', tool_calls=[{'id': 'fix-app', 'name': 'patch',
                    'arguments': {'path': 'app.txt', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'old': 'bad', 'new': 'good'}}])
            else:
                result['output'] = json.dumps({'summary':'Implementation ready','verification':{'commands':[{'name':'tests','argv':[sys.executable,'-B','check.py'],'cwd':'.','timeout':15}],'reason':'Check actual project behavior'}}) if prompt.get('verification_instruction') else 'Implementation ready for actual tests and independent review.'
        elif request['role'] == 'reviewer':
            result['output'] = json.dumps({'decision': 'approve', 'snapshot_hash': prompt['snapshot_hash'],
                'rationale': 'Inspected application and trusted test evidence',
                'criteria': [{'criterion': c, 'met': True, 'evidence': 'check.py passed and app.txt contains good'}
                             for c in prompt['criteria']]})
        else:
            result['output'] = 'A deterministic standalone reply.'
        return result


@unittest.skipIf(sync_playwright is None, 'Optional Playwright dependency is not installed')
class WorkspaceBrowser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable = os.environ.get('CCX_BROWSER_EXECUTABLE')
        if not executable:
            candidates = ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                          shutil.which('chromium'), shutil.which('google-chrome')]
            executable = next((p for p in candidates if p and Path(p).is_file()), None)
        if not executable:
            raise unittest.SkipTest('No installed Chromium browser; set CCX_BROWSER_EXECUTABLE')
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(executable_path=executable, headless=True,
                                                        chromium_sandbox=True)
        except Exception:
            cls.playwright.stop()
            raise
    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
    def setUp(self):
        for adapter in ('CLIProvider','MiniMaxProvider'):
            guard=mock.patch('ccx_workspace.providers.'+adapter+'.execute',side_effect=AssertionError('Live provider execution is forbidden in browser tests'))
            guard.start();self.addCleanup(guard.stop)
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-browser-')
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / 'sample project'
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True, capture_output=True)
        (self.project / 'app.txt').write_text('bad')
        (self.project / 'check.py').write_text('from pathlib import Path\nassert Path("app.txt").read_text()=="good"\n')
        (self.project / 'README.md').write_text('The application is correct when app.txt contains good.\n')
        self.store = Store(self.base / 'private/workspace.sqlite3')
        self.registry = BrowserRegistry()
        self.server = create_server(self.store, registry=self.registry)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
    def tearDown(self):
        self.context.close()
        self.server.application.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(3)
        self.temp.cleanup()
        self.assertEqual(self.errors, [], 'Browser JavaScript errors')
    def login(self):
        credential = self.server.auth.issue()
        self.page.goto(self.url + '/#bootstrap=' + credential)
        expect(self.page.locator('#workspace')).to_be_visible()
        self.assertNotIn(credential, self.page.url)
        self.assertEqual(self.page.evaluate('document.cookie'), '')
        return credential
    def ready(self):
        self.pid = self.store.register(self.project)['id']
        self.store.index(self.pid)
        save_setting(self.store, 'setup', {'completed': True, 'step': 6, 'defaults': dict(DEFAULTS)})
        self.login()
    def nav(self, name):
        if name not in ('Chat','Projects','Settings') and not self.page.get_by_role('navigation').get_by_role('link',name=name,exact=True).is_visible():
            self.page.get_by_text('Advanced tools',exact=True).click()
        self.page.get_by_role('navigation').get_by_role('link', name=name, exact=True).click()
    def approve(self, permission, values=None):
        form = self.page.locator('#workflow-detail form').filter(has=self.page.get_by_role('button', name='Approve this permission'))
        form.get_by_label('Permission', exact=True).select_option(permission)
        for label, value in (values or {}).items():
            field = form.get_by_label(label, exact=True)
            if field.evaluate('(node)=>node.tagName') == 'SELECT':
                field.select_option(value)
            else:
                field.fill(value)
        form.get_by_role('button', name='Approve this permission').click()
        expect(form.get_by_role('button', name='Approve this permission')).to_be_enabled()
    def test_onboarding_preview_persistence_and_keyboard_mobile(self):
        used = self.login()
        expect(self.page.get_by_role('heading', name='Choose your project')).to_be_visible()
        self.page.get_by_label('Project directory').fill(str(self.project))
        self.page.get_by_role('button', name='Preview project').click()
        expect(self.page.get_by_role('heading', name='Indexing preview')).to_be_visible()
        self.assertEqual(self.store.projects(), [])
        self.page.get_by_role('button', name='Register this project').click()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        self.page.reload()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        self.assertEqual(len(self.store.projects()), 1)
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.keyboard.press('Tab')
        self.assertTrue(self.page.evaluate('document.activeElement !== document.body'))
        self.nav('Settings')
        self.page.get_by_role('button', name='Reopen setup').click()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        # A fresh browser cannot replay the consumed link.
        second = self.browser.new_context()
        try:
            other = second.new_page()
            other.goto(self.url + '/#bootstrap=' + used)
            expect(other.locator('#login')).to_be_visible()
            expect(other.locator('#notice')).to_contain_text('expired or was already used')
        finally:
            second.close()
    def test_provider_forms_session_credentials_and_diagnostics(self):
        self.ready()
        self.nav('Providers')
        card = self.page.locator('section.panel').filter(has=self.page.get_by_role('heading', name='minimax', exact=True))
        card.get_by_label('Application model override').fill('fixture-model')
        card.get_by_role('button', name='Save configuration').click()
        expect(self.page.locator('#notice')).to_contain_text('preferences saved')
        card.get_by_text('Secure credential setup', exact=True).click()
        card.get_by_label('MiniMax API key', exact=True).fill('fixture-key-only-not-a-real-credential')
        card.get_by_label('Credential storage').select_option('session')
        card.get_by_role('button', name='Save credential').click()
        expect(self.page.locator('#notice')).to_contain_text('Credential saved')
        expect(card.get_by_label('MiniMax API key', exact=True)).to_have_value('')
        self.assertNotIn('fixture-key-only', self.page.content())
        card.get_by_role('button', name='Remove stored credential').click()
        self.nav('Settings')
        self.page.get_by_role('button', name='Run diagnostics').click()
        expect(self.page.get_by_role('button', name='Export redacted report')).to_be_visible()
        self.assertEqual(self.registry.calls, [])
    def test_workflow_real_patch_test_review_and_refresh(self):
        self.ready()
        self.nav('Workflows')
        self.page.get_by_label('What should be done?').fill('Correct the sample application')
        self.page.get_by_label('How will we verify it? One criterion per line').fill('app.txt contains good')
        self.page.get_by_label('Orchestrator', exact=True).select_option('codex')
        self.page.get_by_label('Executor', exact=True).select_option('minimax')
        self.page.get_by_label('Reviewer', exact=True).select_option('codex')
        self.page.get_by_role('button', name='Create workflow', exact=True).click()
        expect(self.page.locator('#workflow-detail')).to_be_visible()
        self.approve('sharing', {'Provider': 'codex'})
        self.approve('sharing', {'Provider': 'minimax'})
        self.approve('operations')
        self.approve('command', {'Command name': 'acceptance', 'Executable': sys.executable,
                                 'Arguments, one per line': 'check.py'})
        self.page.get_by_role('button', name='Run', exact=True).click()
        self.page.reload()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='COMPLETED').first).to_be_visible(timeout=20000)
        self.assertEqual((self.project / 'app.txt').read_text(), 'good')
        workflow = self.server.application.engine.list()[0]
        self.assertEqual(workflow['status'], 'COMPLETED')
        self.assertEqual(self.registry.executions, 2)
        self.page.get_by_role('button', name='Inspect exact workflow context').click()
        context_panel=self.page.locator('section.panel').filter(has=self.page.get_by_role('heading',name='Workflow context',exact=True))
        expect(context_panel).to_contain_text('reported_usage')
        self.page.get_by_role('button', name='Inspect execution results').click()
        results_panel=self.page.locator('section.panel').filter(has=self.page.get_by_role('heading',name='Execution results',exact=True))
        expect(results_panel).to_contain_text('output')
        self.nav('Memory')
        expect(self.page.get_by_role('heading', name='Project memory', exact=True)).to_be_visible()
        self.page.get_by_label('Search query').fill('good')
        self.page.get_by_role('button', name='Search', exact=True).click()
        expect(self.page.locator('#memory-content')).to_contain_text('good')
        self.nav('Context')
        self.page.get_by_label('What are you working on?').fill('app good')
        self.page.get_by_role('button', name='Assemble context').click()
        expect(self.page.get_by_role('heading', name='Assembled context')).to_be_visible()
        self.nav('Sessions')
        expect(self.page.get_by_role('heading', name='Provider sessions', exact=True)).to_be_visible()
    def test_pause_resume_cancel_permissions_and_logout(self):
        self.ready()
        engine = self.server.application.engine
        workflow = engine.create(self.pid, 'Pause a controlled task', ['app.txt contains good'],
                                 providers={'planner':'codex','executor':'codex','reviewer':'minimax'})
        engine.create_task(workflow['id'], 'Inspect the application')
        self.page.reload()
        self.nav('Workflows')
        self.page.get_by_role('button', name='Run', exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='APPROVAL_REQUIRED').first).to_be_visible()
        self.assertEqual(self.registry.calls, [])
        engine._set_status(workflow['id'], 'BLOCKED', 'Controlled recoverable fixture')
        self.page.get_by_role('button', name='Refresh status', exact=True).click()
        self.page.get_by_role('button', name='Retry', exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='APPROVAL_REQUIRED').first).to_be_visible()
        self.assertEqual(self.registry.calls, [])
        self.page.get_by_role('button', name='Pause', exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='PAUSED').first).to_be_visible()
        self.page.get_by_role('button', name='Resume', exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='READY').first).to_be_visible()
        self.page.get_by_role('button', name='Cancel', exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='CANCELLED').first).to_be_visible()
        self.page.get_by_role('button', name='Disconnect', exact=True).click()
        expect(self.page.locator('#login')).to_be_visible()
        self.page.reload()
        expect(self.page.locator('#login')).to_be_visible()

    def test_standalone_chat_stream_resume_and_expired_session(self):
        self.ready()
        self.nav('Chat')
        self.page.get_by_label('Agent',exact=True).select_option('minimax')
        self.page.get_by_label('Your task',exact=True).fill('Explain app.txt')
        self.page.get_by_role('button',name='Send',exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_have_count(1)
        self.page.reload()
        expect(self.page.locator('.chat-messages')).to_contain_text('A deterministic standalone reply.',timeout=10000)
        self.assertEqual(len(self.server.application.engine.list()), 0)
        conversation = self.server.application.chat.list()[0]
        before=self.server.application.chat.status(conversation['id'])['session_id']
        self.page.get_by_label('Your task', exact=True).fill('Continue the explanation')
        self.page.get_by_role('button', name='Send', exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_have_count(2)
        expect(self.page.locator('.chat-message.assistant').last).to_contain_text('standalone reply.')
        self.assertEqual(self.server.application.chat.status(conversation['id'])['session_id'], before)
        self.assertEqual(self.page.evaluate('localStorage.length'), 0)
        self.assertEqual(self.page.evaluate('Object.keys(sessionStorage)'), ['ccx-session-proof'])
        self.assertGreater(len(self.page.evaluate('sessionStorage.getItem("ccx-session-proof")')), 32)
        for session in self.server.auth.sessions.values():
            session['expires']=0
        self.page.reload()
        expect(self.page.locator('#login')).to_be_visible()
        self.assertEqual(len(self.registry.calls), 2)

    def test_active_execution_pause_resume_and_cancel(self):
        self.ready()
        (self.project/'app.txt').write_text('good')
        self.registry.delay=5
        engine=self.server.application.engine
        w=engine.create(self.pid,'Control a running agent',['app.txt contains good'],
                        providers={'planner':'codex','executor':'codex','reviewer':'minimax'})
        engine.create_task(w['id'],'Inspect current app')
        engine.approve(w['id'],'sharing',{'provider':'codex'})
        engine.approve(w['id'],'sharing',{'provider':'minimax'})
        engine.approve(w['id'],'command',{'name':'check','argv':[sys.executable,'check.py'],'timeout':15})
        self.page.reload()
        self.nav('Workflows')
        self.page.get_by_role('button',name='Run',exact=True).click()
        expect(self.page.get_by_role('button',name='Run',exact=True)).to_be_disabled()
        expect(self.page.get_by_text('Browser fixture is working',exact=True).first).to_be_visible()
        self.page.get_by_role('button',name='Pause',exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='PAUSED').first).to_be_visible()
        expect(self.page.get_by_role('button',name='Resume',exact=True)).to_be_enabled(timeout=10000)
        self.page.get_by_role('button',name='Resume',exact=True).click()
        expect(self.page.locator('#notice')).to_contain_text('refused')
        uncertain=engine.status(w['id'])['pending_actions']
        self.assertEqual(len(uncertain),1)
        self.approve('recovery',{'Interrupted action ID':uncertain[0]['id'],'Recovery decision':'retry'})
        self.page.get_by_role('button',name='Resume',exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='READY').first).to_be_visible()
        self.page.get_by_role('button',name='Run',exact=True).click()
        self.page.get_by_role('button',name='Cancel',exact=True).click()
        expect(self.page.locator('#workflow-detail .tag').filter(has_text='CANCELLED').first).to_be_visible()
        expect(self.page.get_by_role('button',name='Run',exact=True)).to_be_disabled()
        self.assertEqual((self.project/'app.txt').read_text(),'good')

    def test_requested_approval_denial_handoff_and_workflow_overrides(self):
        self.ready()
        self.nav('Workflows')
        self.page.get_by_label('What should be done?').fill('Inspect with a single task')
        self.page.get_by_label('How will we verify it? One criterion per line').fill('app.txt contains good')
        self.page.get_by_text('Optional execution policy and model overrides',exact=True).click()
        self.page.get_by_label('Execution policy',exact=True).select_option('single_task')
        expect(self.page.get_by_label('Orchestrator model override',exact=True)).to_have_value('')
        expect(self.page.get_by_label('Reviewer model override',exact=True)).to_have_value('')
        self.page.get_by_label('Executor model override',exact=True).fill('fixture-model')
        self.page.get_by_role('button',name='Create workflow',exact=True).click()
        expect(self.page.locator('#workflow-detail')).to_be_visible()
        engine=self.server.application.engine
        workflow=engine.list()[0]
        self.assertEqual(workflow['execution_policy'],'single_task')
        self.assertEqual(workflow['model_overrides'],{'executor':'fixture-model'})
        request=engine.request_approval(workflow['id'],'sharing',{'provider':'minimax'},'Allow this provider to inspect selected project context')
        self.page.get_by_role('button',name='Refresh status',exact=True).click()
        self.page.get_by_role('button',name='Deny request',exact=True).click()
        expect(self.page.get_by_role('button',name='Deny request',exact=True)).to_have_count(0)
        self.assertEqual(engine.approvals(workflow['id']),[])
        request=engine.request_approval(workflow['id'],'failover',{'role':'planner','to_provider':'minimax'},'Use this orchestrator after a controlled unavailable provider')
        self.page.get_by_role('button',name='Refresh status',exact=True).click()
        self.page.get_by_role('button',name='Approve requested scope',exact=True).click()
        expect(self.page.get_by_role('button',name='Approve requested scope',exact=True)).to_have_count(0)
        self.page.get_by_label('Role to hand off',exact=True).select_option('planner')
        self.page.get_by_label('New provider',exact=True).select_option('minimax')
        self.page.get_by_role('button',name='Apply approved handoff',exact=True).click()
        expect(self.page.locator('#workflow-detail')).to_contain_text('Orchestrator: minimax')
        self.assertEqual(engine.status(workflow['id'])['providers']['planner'],'minimax')
        self.assertEqual(self.registry.calls,[])

    def test_error_state_accessibility_and_responsive_screenshots(self):
        self.ready()
        self.nav('Projects')
        self.page.get_by_text('Register a project',exact=True).click()
        self.page.get_by_label('Project directory').fill(str(self.base/'missing-project'))
        self.page.get_by_role('button', name='Preview project').click()
        expect(self.page.locator('#notice')).to_be_visible()
        self.assertEqual(len(self.store.projects()), 1)
        # Every rendered editable control has an associated visible label.
        for control in self.page.locator('main input, main textarea, main select').all():
            self.assertTrue(control.evaluate('(element)=>element.labels && element.labels.length>0'))
        self.nav('Overview')
        artifacts=Path(os.environ.get('CCX_BROWSER_ARTIFACT_DIR',str(self.base)))
        artifacts.mkdir(parents=True,exist_ok=True)
        self.page.screenshot(path=str(artifacts/'ccx-phase2-browser-desktop.png'), full_page=True)
        self.page.set_viewport_size({'width':390,'height':844})
        expect(self.page.get_by_role('heading', name='Your work, in view.')).to_be_visible()
        self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
        self.page.screenshot(path=str(artifacts/'ccx-phase2-browser-mobile.png'), full_page=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
