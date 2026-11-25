"""Verify the soak harness cannot pass with disabled assertions/unbounded backups."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tools/soak_workspace.py'
spec = importlib.util.spec_from_file_location('soak_workspace', SCRIPT)
soak = importlib.util.module_from_spec(spec)
spec.loader.exec_module(soak)


class SoakHarnessTests(unittest.TestCase):
    def test_optimization_flag_and_environment_refused_before_artifacts(self):
        with tempfile.TemporaryDirectory(prefix='ccx-soak-guard-') as temporary:
            output = Path(temporary) / 'report.json'
            for flags, value in ((['-O'], ''), ([], '1')):
                with self.subTest(flags=flags, value=value):
                    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=value)
                    result = subprocess.run([sys.executable, '-B', *flags, str(SCRIPT), '--duration', '1',
                                             '--quiet-seconds', '0', '--output', str(output)],
                                            capture_output=True, text=True, env=environment, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('requires assertions enabled', result.stderr)
                    self.assertFalse(output.exists())

    def test_backup_bytes_and_free_space_are_explicit_bounds(self):
        with tempfile.TemporaryDirectory(prefix='ccx-soak-cap-') as temporary:
            root = Path(temporary)
            (root / 'backup-0.sqlite3').write_bytes(b'123456')
            with mock.patch.object(soak.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=100)):
                self.assertEqual(soak.resource_budget(root, 10, 10, 5)['backup_skip_reason'], 'backup_byte_budget')
                self.assertTrue(soak.resource_budget(root, 11, 10, 5)['backup_allowed'])
                self.assertEqual(soak.resource_budget(root, 100, 90, 15)['backup_skip_reason'], 'free_space_headroom')
            with mock.patch.object(soak.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=9)):
                with self.assertRaises(soak.ResourceLimit):
                    soak.resource_budget(root, 100, 10)

    def test_real_smoke_reports_backup_budget_skip_and_enabled_assertions(self):
        with tempfile.TemporaryDirectory(prefix='ccx-soak-smoke-') as temporary:
            output = Path(temporary) / 'report.json'
            environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE='0')
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--duration', '1', '--quiet-seconds', '0',
                                     '--output', str(output), '--max-backup-bytes', '1'],
                                    capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(output.read_text())
            self.assertEqual(report['status'], 'PASSED')
            self.assertGreaterEqual(report['elapsed_seconds'], 1)
            self.assertEqual(report['python_optimize'], 0)
            self.assertGreater(report['completed_workflows'], 0)
            self.assertEqual(report['workflows'][0]['backup_skipped'], 'backup_byte_budget')
            self.assertTrue(all(sample['backup_bytes'] <= 1 for sample in report['samples']))
            self.assertEqual(report['live_provider_calls'], 0)


if __name__ == '__main__':
    unittest.main()
