"""Real-browser evidence for the short Ask/Build flows. No live providers."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest import mock
import test_workspace_browser as browser_tests
from test_workspace_browser import sync_playwright, expect
from ccx_workspace.settings import save_setting
from ccx_workspace.server import DashboardError


@unittest.skipIf(sync_playwright is None, 'Optional Playwright is not installed')
class EasyWorkspace(unittest.TestCase):
    setUpClass = classmethod(browser_tests.WorkspaceBrowser.setUpClass.__func__)
    tearDownClass = classmethod(browser_tests.WorkspaceBrowser.tearDownClass.__func__)
    setUp = browser_tests.WorkspaceBrowser.setUp
    tearDown = browser_tests.WorkspaceBrowser.tearDown
    login = browser_tests.WorkspaceBrowser.login
    ready = browser_tests.WorkspaceBrowser.ready

    def test_chat_model_effort_persist_and_reach_provider(self):
        self.ready()
        expect(self.page.get_by_label('Model',exact=True)).to_be_hidden()
        self.page.get_by_label('Chat settings',exact=True).click()
        self.page.get_by_label('Model',exact=True).select_option('custom')
        self.page.get_by_label('Model ID',exact=True).fill('fixture-model')
        self.page.get_by_label('Reasoning effort',exact=True).select_option('high')
        expect(self.page.get_by_label('Chat settings',exact=True)).to_contain_text('fixture-model · high')
        self.page.get_by_role('button',name='Done',exact=True).click()
        expect(self.page.get_by_label('Model',exact=True)).to_be_hidden()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_focused()
        directory=os.environ.get('CCX_EASY_EVIDENCE_DIR')
        if directory:
            Path(directory).mkdir(parents=True,exist_ok=True)
            self.page.screenshot(path=str(Path(directory)/'chat-settings-collapsed.png'),full_page=True)
        self.page.get_by_label('Your task',exact=True).fill('Explain this project')
        self.page.get_by_role('button',name='Send',exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        request=self.registry.requests[-1]
        self.assertEqual((request.model,request.effort),('fixture-model','high'))
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('Requested: fixture-model')
        self.page.reload()
        expect(self.page.get_by_label('Model',exact=True)).to_be_hidden()
        expect(self.page.get_by_label('Chat settings',exact=True)).to_contain_text('fixture-model · high')
        self.page.get_by_label('Chat settings',exact=True).click()
        expect(self.page.get_by_label('Model',exact=True)).to_have_value('fixture-model')
        expect(self.page.get_by_label('Reasoning effort',exact=True)).to_have_value('high')
        self.page.get_by_label('Agent',exact=True).select_option('minimax')
        self.page.get_by_label('Chat settings',exact=True).click()
        expect(self.page.get_by_label('Reasoning effort',exact=True)).to_be_disabled()
        expect(self.page.get_by_label('Model',exact=True)).to_have_value('')
        self.page.get_by_label('Action',exact=True).select_option('build')
        expect(self.page.locator('[data-chat-settings]')).to_be_hidden()

    def test_old_cancelled_task_never_replaces_new_chat(self):
        self.ready()
        engine=self.server.application.engine
        flow=engine.create(self.pid,'Old cancelled task',['done'])
        task=engine.create_task(flow['id'],'Old testing step')
        engine.cancel(flow['id'])
        with self.store.connect() as db:
            db.execute("UPDATE w5_tasks SET status='TESTING' WHERE id=?",(task['id'],))
        self.page.reload()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        expect(self.page.locator('[data-task-progress]')).to_be_hidden()
        self.page.get_by_label('Your task',exact=True).fill('Explain current project')
        self.page.get_by_role('button',name='Send',exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        expect(self.page.locator('[data-task-progress]')).to_be_hidden()
        self.page.get_by_text('Tasks (1)',exact=True).click()
        self.page.get_by_label('Find task',exact=True).fill('not present')
        expect(self.page.get_by_text('No tasks here',exact=True)).to_be_visible()
        self.page.get_by_label('Find task',exact=True).fill('')
        self.page.get_by_label('Show tasks',exact=True).select_option('done')
        expect(self.page.get_by_text('No tasks here',exact=True)).to_be_visible()
        self.page.get_by_label('Show tasks',exact=True).select_option('all')
        self.page.get_by_role('button',name='Old cancelled task · cancelled',exact=True).click()
        expect(self.page.locator('[data-task-progress] [role=status]')).to_contain_text('Cancelled')
        expect(self.page.locator('[data-task-progress] [role=status]')).not_to_contain_text('Testing')
        expect(self.page.locator('.chat-messages')).to_be_hidden()
        self.page.get_by_role('navigation').get_by_role('link',name='Chat',exact=False).click()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply')
        expect(self.page.locator('[data-task-progress]')).to_be_hidden()
        self.page.get_by_role('button',name='New chat',exact=True).click()
        expect(self.page.get_by_label('Your task',exact=True)).to_have_value('')
        expect(self.page.locator('.chat-message')).to_have_count(0)
        expect(self.page.locator('[data-task-progress]')).to_be_hidden()

    def test_remove_budget_limit_and_resume_from_tasks(self):
        self.ready()
        app=self.server.application
        proposal=app.tasks.preview({'project_id':self.pid,'provider':'codex',
            'instruction':'Fix app.txt','max_tokens':128,'max_cost':1,'max_call_cost':.1,
            'commands':[{'name':'tests','argv':[sys.executable,'-B','check.py'],'cwd':'.','timeout':15}]})
        import uuid
        started=app.tasks.start({'proposal_id':proposal['proposal_id'],'revision':proposal['revision'],
            'confirmed':True,'idempotency_key':uuid.uuid4().hex})
        self.page.get_by_role('navigation').get_by_role('link',name='Tasks',exact=False).click()
        row=self.page.get_by_role('button',name='Fix app.txt · budget exhausted',exact=True)
        expect(row).to_be_visible(timeout=15000)
        row.click()
        expect(self.page.get_by_role('button',name='Resume task',exact=True)).to_have_count(0)
        self.page.get_by_role('button',name='Remove usage limits & resume',exact=True).click()
        expect(self.page.get_by_text('Done · tests and review verified',exact=True)).to_be_visible(timeout=30000)
        self.assertEqual(app.engine.status(started['workflow_id'])['budget_policy'],'unlimited')
        self.page.get_by_role('button',name='New task',exact=True).click()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        expect(self.page.get_by_label('Action',exact=True)).to_have_value('build')

    def test_markdown_tables_are_safe_and_readable(self):
        self.ready()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        self.page.evaluate(r"""() => {
          const node=chatMarkdown('| Area | Status |\n| --- | --- |\n| **API** | Done |\n| UI | <img src=x onerror=alert(1)> |');
          node.id='table-check';document.querySelector('.chat-transcript').append(node);
        }""")
        table=self.page.locator('#table-check table')
        expect(table.locator('th')).to_have_count(2)
        expect(table.locator('tbody tr')).to_have_count(2)
        expect(table.locator('strong')).to_have_text('API')
        expect(table.locator('img')).to_have_count(0)

    def test_live_activity_is_visible_and_survives_reload(self):
        self.ready()
        self.page.get_by_label('Your task',exact=True).fill('Explain the project')
        self.page.get_by_role('button',name='Send',exact=True).click()
        expect(self.page.locator('.live-activity')).to_be_visible()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        self.page.locator('.live-activity summary').click()
        expect(self.page.locator('.live-activity')).to_contain_text('Reading project files')
        expect(self.page.locator('.live-activity')).to_contain_text('Response completed')
        self.page.reload()
        expect(self.page.locator('.live-activity summary')).to_contain_text('Response completed')

    def test_simple_build_detects_checks_and_can_switch_to_ask(self):
        (self.project/'Cargo.toml').write_text('[package]\nname="sample"\nversion="0.1.0"\n')
        self.ready()
        self.page.get_by_label('Action',exact=True).select_option('build')
        self.page.get_by_label('Your task',exact=True).fill('Check what remains to do')
        self.page.get_by_role('button',name='Review task',exact=True).click()
        expect(self.page.locator('.build-checks')).to_contain_text('cargo')
        expect(self.page.get_by_label('Test executable',exact=True)).to_be_hidden()
        expect(self.page.get_by_label('Total usage reservation',exact=True)).to_be_hidden()
        expect(self.page.get_by_label('What should work when finished?',exact=True)).to_be_hidden()
        self.page.get_by_text('Optional usage limits',exact=True).click()
        self.page.get_by_label('Usage allowance',exact=True).select_option('small')
        expect(self.page.get_by_role('button',name='Approve & start',exact=True)).to_be_enabled()
        directory=os.environ.get('CCX_EASY_EVIDENCE_DIR')
        if directory:
            Path(directory).mkdir(parents=True,exist_ok=True)
            self.page.screenshot(path=str(Path(directory)/'simple-build.png'),full_page=True)
        self.page.get_by_role('button',name='Just ask · no file changes',exact=True).click()
        expect(self.page.get_by_label('Action',exact=True)).to_have_value('ask')
        expect(self.page.get_by_label('Your task',exact=True)).to_have_value('Check what remains to do')
        self.assertEqual(self.registry.calls,[])

    def test_build_custom_team_and_models_in_review_card(self):
        self.ready()
        self.page.get_by_label('Action',exact=True).select_option('build')
        self.page.get_by_label('Build team',exact=True).click()
        self.page.get_by_label('Team mode',exact=True).select_option('custom')
        self.page.get_by_label('Review agent',exact=True).select_option('minimax')
        self.page.get_by_label('Implementation model',exact=True).fill('worker-model')
        self.page.get_by_label('Review model',exact=True).fill('review-model')
        self.page.get_by_label('Task planning',exact=True).select_option('subtasks')
        self.page.get_by_role('button',name='Done',exact=True).click()
        self.page.get_by_label('Your task',exact=True).fill('Implement and review this change')
        self.page.get_by_role('button',name='Review task',exact=True).click()
        expect(self.page.locator('[data-task-review]')).to_contain_text('Separate minimax review session')
        expect(self.page.locator('[data-task-review]')).to_contain_text('executor = worker-model')
        expect(self.page.locator('[data-task-review]')).to_contain_text('reviewer = review-model')
        self.page.get_by_text('Optional usage limits',exact=True).click()
        self.page.get_by_label('Usage allowance',exact=True).select_option('small')
        expect(self.page.locator('[data-task-review]')).to_contain_text('reviewer = review-model')
        self.assertEqual(self.registry.calls,[])

    def test_chat_composer_stays_visible_with_long_history(self):
        self.ready()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        self.page.evaluate("""() => {const t=document.querySelector('.chat-transcript');
          for(let i=0;i<100;i++)t.append(chatMessage({role:'assistant',content:'Long history '+i},'codex'));
          document.querySelector('.chat-stream').scrollTop=500;}""")
        box=self.page.get_by_label('Your task',exact=True).bounding_box()
        self.assertGreaterEqual(box['y'],0)
        self.assertLessEqual(box['y']+box['height'],1000)
        self.page.get_by_role('button',name='New chat',exact=True).click()
        expect(self.page.locator('.chat-message')).to_have_count(0)
        self.page.set_viewport_size({'width':390,'height':844})
        expect(self.page.get_by_role('button',name='Send',exact=True)).to_be_visible()
        box=self.page.get_by_role('button',name='Send',exact=True).bounding_box()
        self.assertLessEqual(box['y']+box['height'],844)
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)

    def test_markdown_renders_without_executing_html_or_unsafe_links(self):
        self.ready()
        self.page.evaluate(r"""() => {
          const node=chatMarkdown('## Answer\n**Python** and `SQLite`\n- One\n- Two\n```python\nprint("hello")\n```\n<img src=x onerror="window.chatXss=true">\n[bad](javascript:alert(1))\n[docs](https://example.com/docs)');
          node.id='markdown-check';document.querySelector('main').append(node);
        }""")
        rendered=self.page.locator('#markdown-check')
        expect(rendered.locator('strong')).to_have_text('Python')
        expect(rendered.locator('li')).to_have_count(2)
        expect(rendered.locator('pre code')).to_contain_text('print("hello")')
        expect(rendered.locator('img, script')).to_have_count(0)
        expect(rendered.locator('a')).to_have_count(1)
        self.assertFalse(self.page.evaluate('Boolean(window.chatXss)'))

    def test_one_click_question_and_two_click_build(self):
        self.pid = self.store.register(self.project)['id']
        save_setting(self.store, 'task_preferences', {self.pid: {'max_cost':1,'max_call_cost':.1,
            'max_tokens':50000,'commands':[{'name':'tests','argv':[sys.executable,'-B','check.py'],'cwd':'.','timeout':15}]}})
        self.login()
        expect(self.page.get_by_label('Your task', exact=True)).to_be_visible()
        self.page.get_by_label('Your task', exact=True).fill('Explain this project')
        self.page.get_by_role('button', name='Send', exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        self.assertEqual(len(self.registry.calls),1)
        self.assertEqual(len(self.server.application.chat.list()),1)
        expect(self.page.get_by_role('button',name='Start conversation',exact=True)).to_have_count(0)
        self.page.reload()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply')
        self.page.get_by_label('Action',exact=True).select_option('build')
        self.page.get_by_label('Your task',exact=True).fill('Make app.txt contain good')
        self.page.get_by_role('button',name='Review task',exact=True).click()
        expect(self.page.get_by_role('button',name='Approve & start',exact=True)).to_be_enabled()
        expect(self.page.get_by_text('Separate codex review session',exact=True)).to_be_visible()
        self.assertEqual(len(self.registry.calls),1,'Preview must not invoke an agent')
        self.page.get_by_role('button',name='Approve & start',exact=True).click()
        expect(self.page.get_by_text('Done · tests and review verified',exact=True)).to_be_visible(timeout=30000)
        expect(self.page.get_by_text('Files changed since start',exact=True)).to_be_visible()
        expect(self.page.get_by_text('Live agent activity',exact=True)).to_be_visible()
        self.page.get_by_text('View diff',exact=True).click()
        expect(self.page.locator('[data-task-progress] pre').filter(has_text='+good')).to_be_visible()
        self.assertEqual((self.project/'app.txt').read_text(),'good')
        self.assertEqual(len(self.server.application.engine.list()),1)
        self.assertEqual(self.server.application.engine.list()[0]['budget_policy'],'unlimited')
        expect(self.page.get_by_label('Your task',exact=True)).to_have_count(0)
        self.assertNotIn('planner',[call[1] for call in self.registry.calls])
        self.assertIn('reviewer',[call[1] for call in self.registry.calls])
        self.assertEqual(self.page.url.split('#')[-1] if '#' in self.page.url else '', 'tasks')
        # Tasks have their own everyday destination.
        nav=self.page.get_by_role('navigation')
        self.assertEqual(nav.locator('a:visible').all_text_contents(), ['◌Chat','✓Tasks','▣Projects','⚙Settings'])
        directory=os.environ.get('CCX_EASY_EVIDENCE_DIR')
        if directory:
            Path(directory).mkdir(parents=True,exist_ok=True)
            self.page.screenshot(path=str(Path(directory)/'easy-task-results.png'),full_page=True)
            (Path(directory)/'click-counts.json').write_text(json.dumps({'ask_submission_clicks':1,
                'build_submission_clicks':2,'includes_input_and_action_selection':False,
                'provider':'offline mock','verified_completion':True},indent=2))

    def test_onboarding_register_returns_to_composer(self):
        self.login()
        expect(self.page.get_by_text('Choose your project',exact=True)).to_be_visible()
        self.page.get_by_label('Project directory',exact=True).fill(str(self.project))
        self.page.get_by_role('button',name='Preview project',exact=True).click()
        self.page.get_by_role('button',name='Register this project',exact=True).click()
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible(timeout=15000)
        self.assertEqual(self.registry.calls,[])

    def test_inline_budget_validation_and_edit_invalidates_approval(self):
        self.ready()
        self.page.get_by_label('Action',exact=True).select_option('build')
        self.page.get_by_label('Your task',exact=True).fill('Fix app.txt')
        self.page.get_by_role('button',name='Review task',exact=True).click()
        approve=self.page.get_by_role('button',name='Approve & start',exact=True)
        expect(approve).to_be_disabled()
        self.page.get_by_label('Test command',exact=True).select_option('custom')
        self.page.get_by_label('Test executable',exact=True).fill(sys.executable)
        self.page.get_by_label('Arguments · one per line',exact=True).fill('-B\ncheck.py')
        self.page.get_by_text('Optional usage limits',exact=True).click()
        self.page.get_by_label('Usage allowance',exact=True).select_option('small')
        expect(approve).to_be_enabled(timeout=10000)
        self.page.get_by_label('Your task',exact=True).fill('A different task')
        expect(approve).to_have_count(0)
        self.assertEqual(self.registry.calls,[])

    def test_mobile_and_keyboard_accessible_composer(self):
        self.ready()
        self.page.set_viewport_size({'width':390,'height':844})
        expect(self.page.get_by_label('Your task',exact=True)).to_be_visible()
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),390)
        self.page.get_by_label('Your task',exact=True).focus()
        self.page.keyboard.type('Read only')
        self.page.keyboard.press('Control+Enter')
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)

    def test_duplicate_transport_retry_does_not_repeat_provider(self):
        self.ready()
        # Lose the first successful response after the server processed it.
        original=self.server.application.tasks.message
        first=[True]
        def drop(body):
            result=original(body)
            if first[0]:
                first[0]=False
                raise DashboardError('Simulated lost response; inspect and retry the same submission', 503)
            return result
        with mock.patch.object(self.server.application.tasks,'message',side_effect=drop):
            self.page.get_by_label('Your task',exact=True).fill('Explain safely')
            send=self.page.get_by_role('button',name='Send',exact=True)
            send.click()
            expect(self.page.locator('#notice')).to_contain_text('Simulated lost response')
            expect(self.page.get_by_label('Your task',exact=True)).to_have_value('Explain safely')
            send.click()
            expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        self.assertEqual(len(self.registry.calls),1)

    def test_reload_recovers_lost_response_without_resending(self):
        self.ready()
        original=self.server.application.tasks.message
        def drop(body):
            original(body)
            raise DashboardError('Response lost after acceptance',503)
        with mock.patch.object(self.server.application.tasks,'message',side_effect=drop):
            self.page.get_by_label('Your task',exact=True).fill('Recover this question')
            self.page.get_by_role('button',name='Send',exact=True).click()
            expect(self.page.locator('#notice')).to_contain_text('Response lost')
            self.page.reload()
            expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        self.assertEqual(len(self.registry.calls),1)
        self.assertEqual(self.page.evaluate('Object.keys(sessionStorage)'),['ccx-session-proof'])

    def test_switch_project_restores_its_own_conversation(self):
        self.ready()
        self.page.get_by_label('Your task',exact=True).fill('First project question')
        self.page.get_by_role('button',name='Send',exact=True).click()
        expect(self.page.locator('.chat-message.assistant')).to_contain_text('standalone reply',timeout=15000)
        import subprocess
        other=self.base/'another project'
        subprocess.run(['git','init','-q',str(other)],check=True,capture_output=True)
        second=self.store.register(other)['id']
        self.page.reload()
        self.page.get_by_label('Project',exact=True).select_option(second)
        expect(self.page.locator('.chat-message')).to_have_count(0)
        self.page.get_by_label('Project',exact=True).select_option(self.pid)
        expect(self.page.locator('.chat-message.user')).to_contain_text('First project question')
        self.assertEqual(len(self.registry.calls),1)


if __name__=='__main__':unittest.main()
