"""Project-bound legacy import and storage security regressions."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
from ccx_workspace.store import Store, digest, allowed
from ccx_workspace.migration import import_v4


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ccx v5 import ')
        self.base=Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)
        self.store=Store(self.base/'private/db.sqlite3')
        self.project=self.base/'project';self.project.mkdir()
        subprocess.run(['git','init','-q',str(self.project)],check=True,capture_output=True)
        self.pid=self.store.register(self.project)['id']
        self.legacy=self.base/'legacy'/self.pid;self.legacy.mkdir(parents=True,mode=0o700)
        self.session=str(uuid.uuid4());self.codex=str(uuid.uuid4())
        self.record=self.legacy/(self.session+'.json')
        self.record.write_text(json.dumps({'codex_session_id':self.codex,'model':'configured-model'}))

    def test_readonly_idempotent_import_preserves_ids_and_project_scope(self):
        before=self.record.read_bytes()
        result=import_v4(self.store,self.pid,self.legacy)
        self.assertEqual(result['imported'],1)
        self.assertFalse(result['source_modified'])
        self.assertEqual(import_v4(self.store,self.pid,self.legacy)['imported'],0)
        self.assertEqual(self.record.read_bytes(),before)
        memory=self.store.memories(self.pid)[0]
        self.assertEqual(memory['kind'],'observed')
        self.assertEqual(json.loads(memory['body'])['codex_session_id'],self.codex)
        self.assertFalse(self.store.memories(None))

    def test_another_project_directory_rejected_before_import(self):
        other=self.base/'other';other.mkdir()
        subprocess.run(['git','init','-q',str(other)],check=True,capture_output=True)
        oid=self.store.register(other)['id']
        with self.assertRaises(ValueError):import_v4(self.store,oid,self.legacy)
        self.assertEqual(self.store.memories(oid),[])

    def test_conflicting_project_record_prevents_partial_import(self):
        tasks=self.legacy/'tasks';tasks.mkdir()
        (tasks/(str(uuid.uuid4())+'.json')).write_text(json.dumps({'project':str(self.base/'other'),'workflow_status':'RUNNING'}))
        with self.assertRaises(ValueError):import_v4(self.store,self.pid,self.legacy)
        self.assertEqual(self.store.memories(self.pid),[])

    def test_manifest_binding_must_match(self):
        (self.legacy/'integrity').mkdir()
        (self.legacy/'integrity/manifest.json').write_text(json.dumps({'project':'elsewhere'}))
        with self.assertRaises(ValueError):import_v4(self.store,self.pid,self.legacy)

    def test_casefolded_sensitive_paths_excluded(self):
        for path in ('.GIT/config','.CLAUDE/settings.json','.AWS/config','Node_Modules/code.py'):
            self.assertFalse(allowed(path),path)

    @unittest.skipIf(os.name=='nt','Symlinks require optional Windows privileges')
    def test_links_in_legacy_records_and_replaced_database_refused(self):
        self.record.unlink();self.record.symlink_to(self.base/'outside')
        with self.assertRaises(PermissionError):import_v4(self.store,self.pid,self.legacy)
        original=self.store.path
        moved=original.with_suffix('.saved');original.rename(moved);original.symlink_to(moved)
        with self.assertRaises(PermissionError):self.store.projects()
        original.unlink();moved.rename(original)

    @unittest.skipIf(os.name=='nt','Hard-link setup verified separately on native Windows')
    def test_hardlinked_index_source_refused(self):
        external=self.base/'external';external.write_text('private outside content')
        os.link(external,self.project/'normal.txt')
        self.assertEqual(self.store.index(self.pid)['updated'],0)
        self.assertEqual(self.store.search(self.pid,'private'),[])

    def test_real_workflow_verification_stays_current_until_source_changes(self):
        from ccx_workspace.workflows import WorkflowEngine
        from test_v5_workflows import MockRegistry
        (self.project/'app.txt').write_text('good')
        engine=WorkflowEngine(self.store)
        workflow=engine.create(self.pid,'Make the app correct',['app.txt contains good'])
        identifier=workflow['id'];engine.create_task(identifier,'Correct app.txt')
        for provider in ('codex','claude'):engine.approve(identifier,'sharing',{'provider':provider})
        engine.approve(identifier,'command',{'name':'test','argv':[sys.executable,'-c','print("ok")'],'timeout':5})
        result=engine.run(identifier,MockRegistry())
        self.assertEqual(result['status'],'COMPLETED',result.get('reason'))
        memories=[item for item in self.store.search(self.pid,'Workflow verification') if item.get('kind')=='verified']
        self.assertEqual(len(memories),1)
        self.assertFalse(memories[0]['stale'])
        (self.project/'app.txt').write_text('changed')
        self.assertTrue(self.store.search(self.pid,'Workflow verification')[0]['stale'])

    def test_new_ignore_rules_hide_cached_and_tracked_content(self):
        path=self.project/'private.txt';path.write_text('unique_private_content')
        subprocess.run(['git','-C',str(self.project),'add','private.txt'],check=True,capture_output=True)
        self.store.index(self.pid)
        self.assertTrue(self.store.search(self.pid,'unique_private_content'))
        (self.project/'.gitignore').write_text('private.txt\n')
        self.assertEqual(self.store.search(self.pid,'unique_private_content'),[])
        self.store.index(self.pid)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM documents WHERE path=?',('private.txt',)).fetchone()[0],0)

    def test_forged_workflow_reference_is_stale(self):
        self.store.add_memory(self.pid,'verification','claimed verification','evidence',kind='verified',
                              source='workflow:'+str(uuid.uuid4()),source_hash='a'*64,verified_at=1)
        self.assertTrue(self.store.search(self.pid,'evidence')[0]['stale'])


if __name__=='__main__':unittest.main(verbosity=2)
