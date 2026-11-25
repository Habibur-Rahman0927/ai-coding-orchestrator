"""Measured context regressions: deterministic local fixtures, no providers."""
import json
import os
import sqlite3
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
import ccx_workspace.store as module


class ContextOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='ccx-phase5-test-');self.base=Path(self.tmp.name)
        self.root=self.base/'project';self.root.mkdir();subprocess.run(['git','init','-q',str(self.root)],check=True,capture_output=True)
        self.store=module.Store(self.base/'private/state.sqlite3');self.pid=self.store.register(self.root)['id']
    def tearDown(self):self.tmp.cleanup()
    def file(self,path,body):
        p=self.root/path;p.parent.mkdir(exist_ok=True,parents=True);p.write_text(body);return p
    def corpus(self):
        for i in range(120):self.file('noise%03d.md'%i,'ledger ordinary discussion')
        self.file('zz_target.py','def reconcile_ledger():\n    return "ledger unique_evidence"\n');self.store.index(self.pid)
    def test_rank_before_limit_recovers_rare_symbol(self):
        self.corpus();ctx=self.store.context(self.pid,'ledger reconcile_ledger',budget=200)
        self.assertIn('unique_evidence',ctx['content'])
    def test_exact_path_and_no_fts_fallback(self):
        self.corpus();self.assertEqual(self.store.search(self.pid,'zz_target.py',limit=1)[0]['source'],'zz_target.py')
        self.store.fts=False
        self.assertIn('unique_evidence',self.store.context(self.pid,'reconcile_ledger')['content'])
    def test_policy_check_batched_and_fresh_ignore_respected(self):
        self.corpus();original=module.subprocess.run;calls=[]
        def run(*a,**kw):
            if 'check-ignore' in a[0]:calls.append(a[0])
            return original(*a,**kw)
        with patch.object(module.subprocess,'run',run):self.store.search(self.pid,'ledger',limit=100)
        self.assertLessEqual(len(calls),1)
        self.file('.gitignore','zz_target.py\n')
        self.assertNotIn('unique_evidence',self.store.context(self.pid,'reconcile_ledger')['content'])
    def test_distributed_symbol_snippets_have_original_line_references(self):
        self.file('code.py','def begin_task():\n    return "first_evidence"\n'+'# filler\n'*70+'def finish_task():\n    return "last_evidence"\n')
        self.store.index(self.pid);ctx=self.store.context(self.pid,'begin_task finish_task',budget=300)
        self.assertIn('first_evidence',ctx['content']);self.assertIn('last_evidence',ctx['content'])
        refs=ctx['references'];self.assertTrue(any(r['line']>60 for r in refs));self.assertLessEqual(ctx['bytes'],1200)
    def test_same_content_touch_does_not_reparse_or_rewrite_search(self):
        p=self.file('a.py','def ready(): return True\n');self.store.index(self.pid)
        with self.store.connect() as db:before=dict(db.execute('SELECT * FROM documents').fetchone())
        os.utime(p,ns=(p.stat().st_atime_ns,p.stat().st_mtime_ns+1000000))
        with patch.object(module.ast,'parse',side_effect=AssertionError('unchanged source must not parse')):result=self.store.index(self.pid)
        self.assertEqual(result['updated'],0);self.assertEqual(result['unchanged'],1)
        with self.store.connect() as db:after=dict(db.execute('SELECT * FROM documents').fetchone())
        self.assertEqual(before['indexed_at'],after['indexed_at']);self.assertNotEqual(before['signature'],after['signature'])
    def test_exact_memory_dedup_preserves_evidence_and_scope(self):
        ids=[self.store.add_memory(self.pid,'project','Decision','Use atomic writes',kind='observed')['id'] for _ in range(10)]
        self.assertEqual(len(set(ids)),1)
        hypothesis=self.store.add_memory(self.pid,'project','Decision','Use atomic writes',kind='hypothesis')['id']
        self.assertNotEqual(hypothesis,ids[0])
        changed=self.store.add_memory(self.pid,'project','Decision','Different choice',kind='observed')['id']
        self.assertNotEqual(changed,ids[0])
    def test_dedup_does_not_revive_superseded_or_expired_record(self):
        old=self.store.add_memory(self.pid,'project','Old','same')['id']
        self.store.add_memory(self.pid,'project','New','replacement',supersedes=old)
        again=self.store.add_memory(self.pid,'project','Old','same')['id'];self.assertNotEqual(old,again)
        dead=self.store.add_memory(self.pid,'temporary','Old','same',expires_at=1)['id']
        self.assertNotEqual(dead,self.store.add_memory(self.pid,'temporary','Old','same',expires_at=1)['id'])
    def test_concurrent_duplicate_submission_is_atomic(self):
        errors=[];ids=[]
        def add():
            try:ids.append(self.store.add_memory(self.pid,'project','Decision','bounded work')['id'])
            except Exception as e:errors.append(str(e))
        threads=[threading.Thread(target=add) for _ in range(6)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(errors,[]);self.assertEqual(len(set(ids)),1)
    def test_exact_path_ranking_rejects_suffix_filename_matches(self):
        self.file('a.py', '# parser helper\n')
        self.file('data.py', '# correct target file\n')
        self.store.index(self.pid)
        rows = self.store.search(self.pid, 'Inspect data.py and parser', limit=2)
        self.assertEqual(rows[0]['source'], 'data.py')
        self.assertTrue(rows[0]['retrieval_reason']['exact_path'])
        self.assertFalse(next(row for row in rows if row['source']=='a.py')['retrieval_reason']['exact_path'])

    def test_newly_available_fts_backfills_existing_index_without_source_reads(self):
        self.file('architecture.md', 'unique_business_constraint')
        path = self.base / 'optional/state.sqlite3'
        connect = sqlite3.connect
        class MissingFTS(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith('CREATE VIRTUAL TABLE'):
                    raise sqlite3.OperationalError('no such module: fts5')
                return super().execute(sql, *args)
        def connection(*args, **kwargs):
            return connect(*args, factory=MissingFTS, **kwargs)
        with patch.object(module.sqlite3, 'connect', side_effect=connection):
            fallback = module.Store(path)
            pid = fallback.register(self.root)['id']
            fallback.index(pid)
            self.assertFalse(fallback.fts)
            self.assertTrue(fallback.search(pid, 'unique_business_constraint'))
        restored = module.Store(path)
        self.assertTrue(restored.fts)
        self.assertEqual(restored.index(pid)['bytes_read'], 0)
        self.assertTrue(restored.search(pid, 'unique_business_constraint'))
        with restored.connect() as db:
            before = db.execute('SELECT COUNT(*) FROM document_search').fetchone()[0]
        reopened = module.Store(path)
        with reopened.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM document_search').fetchone()[0], before)

    def test_existing_fts_rebuilds_after_fallback_updates(self):
        source = self.file('notes.md', 'old_business_marker')
        self.store.index(self.pid)
        connect = sqlite3.connect
        class MissingFTS(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql.startswith('CREATE VIRTUAL TABLE'):
                    raise sqlite3.OperationalError('no such module: fts5')
                return super().execute(sql, *args)
        def connection(*args, **kwargs):
            return connect(*args, factory=MissingFTS, **kwargs)
        with patch.object(module.sqlite3, 'connect', side_effect=connection):
            fallback = module.Store(self.store.path)
            source.write_text('new_business_marker')
            fallback.index(self.pid)
            self.assertTrue(fallback.search(self.pid, 'new_business_marker'))
        restored = module.Store(self.store.path)
        self.assertEqual(restored.index(self.pid)['bytes_read'], 0)
        self.assertTrue(restored.search(self.pid, 'new_business_marker'))
        self.assertEqual(restored.search(self.pid, 'old_business_marker'), [])
        with restored.connect() as db:
            self.assertEqual(db.execute("SELECT value FROM knowledge_index_state WHERE key='fts_dirty'").fetchone()[0], 0)

    def test_role_priority_changes_optional_context_without_dropping_critical_rules(self):
        self.file('AGENTS.md', 'Never deploy.')
        self.file('architecture.md', 'needle architecture ' + 'a' * 120)
        self.file('tests/unit.py', '# needle test evidence ' + 'b' * 120)
        self.store.index(self.pid)
        for role, preferred, omitted in (('planner', 'architecture.md', 'tests/unit.py'),
                                          ('reviewer', 'tests/unit.py', 'architecture.md')):
            with self.subTest(role=role):
                context = self.store.context(self.pid, 'needle', budget=100, role=role,
                    critical=['Preserve acceptance criteria.', 'Preserve acceptance criteria.'])
                sources = [item['source'] for item in context['references']]
                self.assertIn('AGENTS.md', sources)
                self.assertIn(preferred, sources)
                self.assertNotIn(omitted, sources)
                self.assertIn('Never deploy.', context['content'])
                self.assertEqual(context['content'].count('Preserve acceptance criteria.'), 1)
                self.assertEqual(context['role'], role)
                self.assertLessEqual(context['bytes'], 400)
                self.assertTrue(any(item['source']==omitted and item['reason']=='budget' for item in context['excluded']))

    def test_tight_budget_constraints_and_stale_source(self):
        self.file('AGENTS.md','Mandatory rule late in the root instructions.\n'*12);self.file('work.py','def target(): return "old_fact"')
        self.store.index(self.pid)
        with self.assertRaises(ValueError):self.store.context(self.pid,'target',budget=64,critical=['Never deploy'])
        self.file('work.py','def target(): return "new_fact"')
        self.assertNotIn('old_fact',self.store.context(self.pid,'target',budget=1000)['content'])

if __name__=='__main__':unittest.main()
