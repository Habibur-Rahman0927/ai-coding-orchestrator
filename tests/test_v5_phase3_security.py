"""Offline credential-boundary and special-file regressions; synthetic secrets only."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.tools import ScopedTools
from ccx_workspace.security import sensitive_content


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ccx-phase3-security-')
        self.base = Path(self.tmp.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True)
        self.store = Store(self.base / 'state/workspace.sqlite')
        self.pid = self.store.register(self.project)['id']
        self.fake = 'ghp_' + 'A' * 32

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_search_match_index_secret_policy(self):
        tools = ScopedTools(self.project, ['read_file', 'search'])
        for value in (self.fake, 'github_pat_' + 'B' * 32,
                      'password=abcdefghijklmnop', 'api_key=abcdefghijklmnop',
                      'AKIA' + 'A' * 16):
            with self.subTest(family=value.split('=')[0][:8]):
                (self.project / 'settings.txt').write_text(value)
                indexed = self.store.index(self.pid)
                self.assertEqual(indexed['updated'], 0)
                self.assertEqual(indexed['excluded'], 1)
                self.assertEqual(self.store.search(self.pid, value[:8]), [])
                with self.assertRaises(PermissionError):
                    tools.execute('read_file', {'path': 'settings.txt'})
                self.assertEqual(tools.execute('search', {'query': value[:8]})['matches'], [])

    def test_nested_transcripts_and_structured_credential_values(self):
        self.assertTrue(sensitive_content({'history': [{'content': self.fake}]}))
        self.assertTrue(sensitive_content({'api_key': 'abcdefghijklmnop'}))
        self.assertTrue(sensitive_content({self.fake: 'ordinary value'}))
        self.assertFalse(sensitive_content({'history': [{'content': 'ordinary source text'}]}))

    def test_patch_cannot_introduce_recognizable_credential(self):
        path = self.project / 'app.txt'
        path.write_text('safe')
        tools = ScopedTools(self.project, ['patch'])
        with self.assertRaises(PermissionError):
            tools.execute('patch', {'path': 'app.txt', 'sha256': hashlib.sha256(b'safe').hexdigest(),
                                    'old': 'safe', 'new': self.fake})
        self.assertEqual(path.read_text(), 'safe')

    def test_historical_diff_credential_is_not_returned(self):
        path = self.project / 'app.txt'
        path.write_text(self.fake)
        subprocess.run(['git', '-C', str(self.project), 'add', 'app.txt'], check=True)
        path.write_text('safe')
        with self.assertRaises(PermissionError):
            ScopedTools(self.project, ['git_diff']).execute('git_diff', {})

    def test_command_output_credential_is_not_returned(self):
        tools = ScopedTools(self.project, ['run_command'], {'test': {
            'argv': [sys.executable, '-c', 'print("ghp_" + "A" * 32)'], 'timeout': 5}})
        with self.assertRaises(PermissionError):
            tools.execute('run_command', {'name': 'test'})

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_fifo_reads_are_rejected_without_blocking(self):
        os.mkfifo(self.project / 'input.txt')
        code = '''import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from ccx_workspace.tools import ScopedTools
from ccx_workspace.store import read_source
try:
    if sys.argv[3] == 'tool':
        ScopedTools(Path(sys.argv[2]), ['read_file']).execute('read_file', {'path':'input.txt'})
    else:
        read_source(Path(sys.argv[2]), 'input.txt')
except PermissionError:
    raise SystemExit(0)
raise SystemExit(1)
'''
        for mode in ('tool', 'store'):
            with self.subTest(mode=mode):
                try:
                    result = subprocess.run([sys.executable, '-B', '-c', code,
                        str(ROOT / 'engine/lib'), str(self.project), mode], timeout=3,
                        capture_output=True, text=True)
                except subprocess.TimeoutExpired:
                    self.fail('FIFO read blocked instead of rejecting nonregular file')
                self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_fifo_swap_during_open_is_rejected_without_blocking(self):
        path = self.project / 'app.txt'
        path.write_text('safe')
        code = """import os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
from ccx_workspace.security import read_regular_bytes
path = Path(sys.argv[2])
original = os.open
def swap(name, flags):
    path.unlink()
    os.mkfifo(path)
    return original(name, flags)
try:
    with patch('ccx_workspace.security.os.open', side_effect=swap):
        read_regular_bytes(path, 1024)
except PermissionError:
    raise SystemExit(0)
raise SystemExit(1)
"""
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code,
                str(ROOT / 'engine/lib'), str(path)], timeout=3,
                capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            self.fail('FIFO swap blocked during open')
        self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Named pipes require POSIX')
    def test_indexed_source_replaced_by_fifo_is_stale(self):
        path = self.project / 'app.txt'
        path.write_text('needle')
        self.store.index(self.pid)
        path.unlink()
        os.mkfifo(path)
        code = '''import sys
sys.path.insert(0, sys.argv[1])
from ccx_workspace.store import Store
result = Store(sys.argv[2]).search(sys.argv[3], 'needle')
assert len(result) == 1 and result[0]['stale'] is True
'''
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code,
                str(ROOT / 'engine/lib'), str(self.store.path), self.pid], timeout=3,
                capture_output=True, text=True)
        except subprocess.TimeoutExpired:
            self.fail('Context freshness blocked on replaced FIFO')
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
