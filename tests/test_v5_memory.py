import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.benchmark import benchmark

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ccx v5 knowledge ')
        self.base=Path(self.tmp.name).resolve()
        self.db=self.base/'private'/'workspace.sqlite3'
        self.store=Store(self.db)
        self.root=self.base/'project ü';self.root.mkdir()
        subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        self.pid=self.store.register(self.root)['id']
    def tearDown(self): self.tmp.cleanup()
    def file(self,name,body):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body,encoding='utf-8');return p
    def test_restart_and_scope_isolation(self):
        mid=self.store.add_memory(self.pid,'project','Decision','Use bounded queues',kind='user_instruction')['id']
        other=self.base/'other';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True)
        oid=self.store.register(other)['id'];fresh=Store(self.db)
        self.assertEqual(fresh.search(self.pid,'bounded')[0]['id'],mid)
        self.assertEqual(fresh.search(oid,'bounded'),[])
        with self.assertRaises(KeyError): fresh.delete_memory(mid,oid)
        self.store.add_memory(None,'global','Private machine','Never shared automatically')
        self.assertEqual(fresh.search(self.pid,'automatically'),[])
    def test_incremental_index_hashes_and_symbols(self):
        p=self.file('module.py','import json\ndef unique_symbol():\n    return 1\n')
        one=self.store.index(self.pid);two=self.store.index(self.pid)
        self.assertEqual(one['updated'],1);self.assertEqual(two['unchanged'],1);self.assertEqual(two['bytes_read'],0)
        p.write_text('def unique_symbol():\n    return 2\n')
        self.assertTrue(self.store.search(self.pid,'unique_symbol')[0]['stale'])
        self.assertEqual(self.store.index(self.pid)['updated'],1)
        result=self.store.search(self.pid,'unique_symbol')[0]
        self.assertFalse(result['stale']);self.assertIn('unique_symbol',result['symbols'])
        p.unlink();self.assertEqual(self.store.index(self.pid)['deleted'],1)
    def test_exclusions_gitignore_binary_secret_content(self):
        self.file('.gitignore','ignored.txt\n')
        self.file('ignored.txt','not indexed')
        self.file('.env','private data')
        self.file('node_modules/pkg/index.js','dependency')
        self.file('normal.txt','api_key = abcdefghijklmnopqrstuvwxyz')
        self.file('README.md','Approved architecture')
        (self.root/'binary').write_bytes(b'\x00secret')
        self.store.index(self.pid)
        with self.store.connect() as db: paths=[r[0] for r in db.execute('SELECT path FROM documents')]
        self.assertEqual(set(paths),{'.gitignore','README.md'})
    @unittest.skipIf(os.name=='nt','Symlink creation needs optional Windows privileges')
    def test_symlink_sources_and_database_refused(self):
        outside=self.base/'outside';outside.write_text('external content')
        (self.root/'link.txt').symlink_to(outside)
        self.assertEqual(self.store.index(self.pid)['updated'],0)
        link=self.base/'db-link';link.symlink_to(self.db)
        with self.assertRaises(PermissionError): Store(link)
    def test_context_budgets_critical_staleness_and_dedup(self):
        self.file('one.md','rareword implementation details\n'*40)
        self.file('two.md','rareword implementation details\n'*40)
        self.store.index(self.pid)
        ctx=self.store.context(self.pid,'rareword',budget=300,critical=['MUST preserve approval boundaries'])
        self.assertIn('MUST preserve',ctx['content']);self.assertLessEqual(ctx['bytes'],1200)
        self.assertEqual(len(ctx['references']),1)
        self.assertTrue(any(x['reason']=='duplicate' for x in ctx['excluded']))
        with self.assertRaises(ValueError): self.store.context(self.pid,'rareword',64,critical=['x'*257])
        self.file('one.md','changed');self.file('two.md','changed')
        self.assertEqual(self.store.context(self.pid,'rareword')['references'],[])
    def test_memory_expiration_supersession_verification(self):
        first=self.store.add_memory(self.pid,'project','old','Decision A')['id']
        self.store.add_memory(self.pid,'project','new','Decision B',supersedes=first)
        self.store.add_memory(self.pid,'temporary','expired','gone',expires_at=1)
        self.assertEqual(len(self.store.memories(self.pid)),1)
        with self.assertRaises(ValueError): self.store.add_memory(self.pid,'project','false','claim',kind='verified')
        with self.assertRaises(ValueError): self.store.add_memory(self.pid,'project','sensitive','password=abcdefghijklmnop')
    def test_backup_recovery(self):
        self.store.add_memory(self.pid,'error','Fixed','Observed test failure and resolution')
        backup=self.base/'backup.sqlite3';self.store.backup(backup)
        recovered=Store(backup)
        self.assertEqual(recovered.memories(self.pid)[0]['title'],'Fixed')
        with self.assertRaises(FileExistsError): self.store.backup(backup)
    def test_machine_snapshot_is_cached_and_local(self):
        one=self.store.machine();two=self.store.machine()
        self.assertEqual(one,two);self.assertEqual(one['sharing'],'local_only')
        self.assertTrue(all(isinstance(v,bool) for v in one['tools'].values()))
    def test_measured_context_benchmark(self):
        self.file('target.py','def requested_feature():\n    return "evidence"\n')
        for i in range(20):self.file('noise%d.md'%i,'Unrelated documentation paragraph.\n'*100)
        self.store.index(self.pid)
        report=benchmark(self.store,self.pid,['requested_feature'],budget=300)
        self.assertGreater(report['context_byte_reduction'],0)
        self.assertEqual(report['runs'][0]['reference_count'],1)
        self.assertIsNone(report['cost_savings']);self.assertIsNone(report['runs'][0]['provider_reported_usage'])
    def test_transaction_rollback(self):
        with self.assertRaises(RuntimeError):
            with self.store.connect() as db:
                db.execute('DELETE FROM projects');raise RuntimeError('crash')
        self.assertEqual(Store(self.db).project(self.pid)['id'],self.pid)

if __name__=='__main__':unittest.main()
