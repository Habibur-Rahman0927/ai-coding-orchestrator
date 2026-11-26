"""Real browser onboarding against an isolated installed engine, not source imports."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
try:
    from playwright.sync_api import sync_playwright,expect
except ImportError:
    sync_playwright=None
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace import service


@unittest.skipIf(sync_playwright is None,'Optional Playwright is not installed')
class InstalledWorkspace(unittest.TestCase):
    def test_clean_prefix_install_onboarding_restart_and_safe_uninstall(self):
        chrome=os.environ.get('CCX_BROWSER_EXECUTABLE') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        if not Path(chrome).is_file():self.skipTest('Set CCX_BROWSER_EXECUTABLE to installed Chromium')
        with tempfile.TemporaryDirectory(prefix='ccx-installed-browser-') as temporary:
            base=Path(temporary).resolve();prefix=base/'engine';bin_path=base/'bin';db=base/'private/workspace.sqlite3'
            project=base/'approved project'
            subprocess.run(['git','init','-q',str(project)],check=True,capture_output=True)
            (project/'README.md').write_text('A deliberately isolated onboarding fixture.')
            installation=subprocess.run(['/bin/sh',str(ROOT/'install.sh'),'--prefix',str(prefix),'--bin-dir',str(bin_path)],capture_output=True,text=True)
            self.assertEqual(installation.returncode,0,installation.stderr)
            command=[str(bin_path/'orchestrator'),'start','--database',str(db),'--port','0','--background','--no-browser']
            started=subprocess.run(command,capture_output=True,text=True,timeout=20)
            self.assertEqual(started.returncode,0,started.stderr)
            store=Store(db)
            try:
                with sync_playwright() as tool:
                    browser=tool.chromium.launch(executable_path=chrome,headless=True,chromium_sandbox=True)
                    context=browser.new_context()
                    page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.set_default_timeout(15000)
                    link=service.request(store,'/api/service/browser',{})['url']
                    origin=link.split('/#',1)[0]
                    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
                    page.goto(link)
                    expect(page.get_by_role('heading',name='Choose your project')).to_be_visible()
                    page.get_by_label('Project directory').fill(str(project))
                    page.get_by_role('button',name='Preview project').click()
                    expect(page.get_by_role('heading',name='Indexing preview')).to_be_visible()
                    page.get_by_role('button',name='Register this project').click()
                    expect(page.get_by_role('button',name='New chat',exact=True)).to_be_visible()
                    expect(page.get_by_label('Project',exact=True)).to_be_visible()
                    page.reload();expect(page.get_by_label('Project',exact=True)).to_be_visible()
                    self.assertEqual(len(store.projects()),1)
                    self.assertEqual(errors,[])
                    context.close();browser.close()
                service.stop(store)
                restarted=subprocess.run(command,capture_output=True,text=True,timeout=20)
                self.assertEqual(restarted.returncode,0,restarted.stderr)
                self.assertTrue(service.request(store,'/api/setup')['completed'])
            finally:service.stop(store)
            removal=subprocess.run(['/bin/sh',str(prefix/'uninstall.sh'),'--prefix',str(prefix),'--bin-dir',str(bin_path),'--yes'],capture_output=True,text=True)
            self.assertEqual(removal.returncode,0,removal.stderr)
            self.assertFalse((bin_path/'orchestrator').exists())
            self.assertTrue(db.exists());self.assertEqual(len(store.projects()),1)


if __name__=='__main__':unittest.main(verbosity=2)
