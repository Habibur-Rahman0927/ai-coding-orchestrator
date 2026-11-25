"""Storage fault injection in disposable databases; never touches user state."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.store import Store


class StorageFaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-phase3-storage-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.store = Store(self.base / 'private/workspace.sqlite3')
        root = self.base / 'project'
        subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
        self.pid = self.store.register(root)['id']
        self.original = self.store.add_memory(self.pid, 'project', 'Durable fact', 'original evidence')['id']

    def assert_intact(self):
        fresh = Store(self.store.path)
        self.assertIn(self.original, {r['id'] for r in fresh.memories(self.pid)})
        with fresh.connect() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(db.execute('SELECT body FROM memory WHERE id=?', (self.original,)).fetchone()[0], 'original evidence')

    def test_killed_process_rolls_back_uncommitted_write(self):
        marker = self.base / 'transaction-open'
        code = '''import pathlib, sqlite3, sys, time
connection = sqlite3.connect(sys.argv[1])
connection.execute('BEGIN IMMEDIATE')
connection.execute('UPDATE memory SET body=? WHERE id=?', ('uncommitted mutation', sys.argv[2]))
pathlib.Path(sys.argv[3]).write_text('ready')
time.sleep(60)
'''
        process = subprocess.Popen([sys.executable, '-B', '-c', code, str(self.store.path), self.original, str(marker)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 5
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(marker.exists(), 'Child never reached the uncommitted write')
            process.kill()
            process.communicate(timeout=5)
            self.assertNotEqual(process.returncode, 0)
            self.assert_intact()
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

    def test_sqlite_disk_full_limit_rolls_back_partial_transaction(self):
        with self.store.connect() as db:
            db.execute('CREATE TABLE fault_blob(value BLOB)')
        with self.assertRaisesRegex(sqlite3.OperationalError, 'full'):
            with self.store.connect() as db:
                pages = db.execute('PRAGMA page_count').fetchone()[0]
                db.execute('PRAGMA max_page_count=%d' % (pages + 1))
                db.execute('UPDATE memory SET body=? WHERE id=?', ('partial mutation', self.original))
                db.execute('INSERT INTO fault_blob VALUES(?)', (b'x' * 1024 * 1024,))
        self.assert_intact()
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM fault_blob').fetchone()[0], 0)

    def test_backup_failure_removes_partial_destination_preserves_source(self):
        destination = self.base / 'failed.sqlite3'
        connect = sqlite3.connect
        class FailedBackup(sqlite3.Connection):
            def backup(self, target, **kwargs):
                target.execute('CREATE TABLE partial_copy(value TEXT)')
                target.commit()
                raise sqlite3.OperationalError('simulated backup disk full')
        def connection(*args, **kwargs):
            return connect(*args, factory=FailedBackup, **kwargs)
        with mock.patch('ccx_workspace.store.sqlite3.connect', side_effect=connection):
            with self.assertRaisesRegex(sqlite3.OperationalError, 'simulated backup'):
                self.store.backup(destination)
        self.assertFalse(destination.exists())
        self.assert_intact()
        successful = self.base / 'successful.sqlite3'
        self.store.backup(successful)
        self.assertEqual(Store(successful).memories(self.pid)[0]['body'], 'original evidence')

    def test_corrupt_database_refused_without_replacing_evidence(self):
        path = self.store.path.parent / 'corrupted.sqlite3'
        payload = b'not a SQLite database\x00' * 100
        path.write_bytes(payload)
        path.chmod(0o600)
        with self.assertRaises(sqlite3.DatabaseError):
            Store(path)
        self.assertEqual(path.read_bytes(), payload)
        self.assert_intact()

    def test_unsupported_schema_refused_before_any_schema_write(self):
        path = self.store.path.parent / 'future.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE schema_versions(component TEXT PRIMARY KEY, version INTEGER NOT NULL)')
            db.execute("INSERT INTO schema_versions VALUES('knowledge',999)")
            db.execute('CREATE TABLE future_evidence(value TEXT)')
            db.execute("INSERT INTO future_evidence VALUES('retain this future-schema evidence')")
        path.chmod(0o600)
        original = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'Unsupported knowledge'):
            Store(path)
        self.assertEqual(path.read_bytes(), original, 'Unsupported schema was modified before refusal')

    def test_failed_schema_initialization_rolls_back_all_ddl(self):
        path = self.store.path.parent / 'migration-fault.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE existing_evidence(value TEXT)')
            db.execute("INSERT INTO existing_evidence VALUES('retain evidence')")
        path.chmod(0o600)
        original = path.read_bytes()
        connect = sqlite3.connect
        class FailedSchema(sqlite3.Connection):
            def executescript(self, script):
                script = script.replace('CREATE TABLE IF NOT EXISTS memory(', 'INVALID SQL; CREATE TABLE IF NOT EXISTS memory(', 1)
                return super().executescript(script)
        def connection(*args, **kwargs):
            return connect(*args, factory=FailedSchema, **kwargs)
        with mock.patch('ccx_workspace.store.sqlite3.connect', side_effect=connection):
            with self.assertRaises(sqlite3.OperationalError):
                Store(path)
        self.assertEqual(path.read_bytes(), original, 'Failed schema setup left committed partial DDL')

    def test_optional_fts_absence_falls_back_but_storage_errors_propagate(self):
        connect = sqlite3.connect
        for message in ('no such module: fts5', 'database or disk is full', 'database is locked', 'database disk image is malformed'):
            with self.subTest(message=message):
                path = self.store.path.parent / ('fts-%d.sqlite3' % len(message))
                class FaultFTS(sqlite3.Connection):
                    def execute(self, sql, *args):
                        if sql.startswith('CREATE VIRTUAL TABLE'):
                            raise sqlite3.OperationalError(message)
                        return super().execute(sql, *args)
                def connection(*args, **kwargs):
                    return connect(*args, factory=FaultFTS, **kwargs)
                with mock.patch('ccx_workspace.store.sqlite3.connect', side_effect=connection):
                    if message == 'no such module: fts5':
                        fallback = Store(path)
                        self.assertFalse(fallback.fts)
                        fallback.add_memory(None, 'global', 'Retained', 'ordinary storage still works')
                        self.assertEqual(fallback.memories(None)[0]['body'], 'ordinary storage still works')
                    else:
                        with self.assertRaisesRegex(sqlite3.OperationalError, message):
                            Store(path)
                if message != 'no such module: fts5':
                    with connect(path) as db:
                        self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 0)

    def test_contended_writers_wait_then_preserve_all_records(self):
        attempted = threading.Event()
        def write(index):
            attempted.set()
            return self.store.add_memory(self.pid, 'project', 'Contended %d' % index, 'committed_%d' % index)['id']
        with ThreadPoolExecutor(max_workers=4) as pool:
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                first = pool.submit(write, 0)
                self.assertTrue(attempted.wait(timeout=3))
                with self.assertRaises(TimeoutError):
                    first.result(timeout=.1)
            identifiers = [first.result(timeout=5)] + list(pool.map(write, range(1, 12)))
        self.assertEqual(len(set(identifiers)), 12)
        self.assertTrue(set(identifiers).issubset({r['id'] for r in Store(self.store.path).memories(self.pid)}))
        self.assert_intact()

    def test_deleting_replacement_does_not_resurrect_superseded_decision(self):
        replacement = self.store.add_memory(self.pid, 'project', 'New fact', 'replacement evidence',
                                            supersedes=self.original)['id']
        self.assertEqual([r['id'] for r in self.store.memories(self.pid)], [replacement])
        self.store.delete_memory(replacement, self.pid)
        self.assertEqual(self.store.memories(self.pid), [], 'Superseded decision silently became current again')
        self.assertEqual(self.store.search(self.pid, 'original evidence'), [])
        self.assertEqual(Store(self.store.path).memories(self.pid), [])


    def test_deleting_supersession_chain_preserves_history_and_never_extends_expiry(self):
        middle = self.store.add_memory(self.pid, 'project', 'Middle', 'middle evidence',
                                       supersedes=self.original)['id']
        final = self.store.add_memory(self.pid, 'project', 'Final', 'final evidence', supersedes=middle)['id']
        with self.store.connect() as db:
            db.execute('UPDATE memory SET expires_at=1 WHERE id=?', (self.original,))
        self.store.delete_memory(final, self.pid)
        self.assertEqual(self.store.memories(self.pid), [])
        self.store.delete_memory(middle, self.pid)
        self.assertEqual(self.store.memories(self.pid), [])
        with self.store.connect() as db:
            record = db.execute('SELECT body,expires_at FROM memory WHERE id=?', (self.original,)).fetchone()
        self.assertEqual(tuple(record), ('original evidence', 0))



    def test_deleted_supersession_stays_expired_after_clock_rollback(self):
        replacement = self.store.add_memory(self.pid, 'project', 'Latest', 'latest evidence',
                                            supersedes=self.original)['id']
        current = time.time()
        with mock.patch('ccx_workspace.store.stamp', return_value=current):
            self.store.delete_memory(replacement, self.pid)
        with mock.patch('ccx_workspace.store.stamp', return_value=current - 60):
            self.assertEqual(self.store.memories(self.pid), [])
            self.assertEqual(Store(self.store.path).memories(self.pid), [])



if __name__ == '__main__':
    unittest.main()
