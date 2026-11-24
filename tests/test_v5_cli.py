import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
class WorkspaceCLI(unittest.TestCase):
    def test_real_cli_persistent_knowledge_and_context(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve();project=base/'project';project.mkdir()
            subprocess.run(['git','init','-q',str(project)],check=True)
            (project/'README.md').write_text('Architecture uses durable workflow checkpoints.')
            def run(*args):
                result=subprocess.run([sys.executable,'-B',str(ROOT/'engine/orchestrator.py'),'workspace','--database',str(base/'private/state.sqlite3'),*args],capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            pid=run('register',str(project))['id']
            self.assertEqual(run('index',pid)['updated'],1)
            context=run('context',pid,'checkpoints','--critical','Keep evidence')
            self.assertIn('Keep evidence',context['content'])
            run('remember',pid,'Decision','Maintain isolated state')
            self.assertEqual(run('search',pid,'isolated')[0]['title'],'Decision')
            run('backup',str(base/'snapshot.sqlite3'))
            self.assertTrue((base/'snapshot.sqlite3').exists())
if __name__=='__main__':unittest.main()
