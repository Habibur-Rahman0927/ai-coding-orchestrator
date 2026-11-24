"""Native end-to-end candidate CLI lifecycle in isolated Unicode directories."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]


class PortableCLI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx lifecycle café ')
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / 'home'
        self.home.mkdir()
        self.engine = self.base / 'engine'
        self.project = self.base / 'project ü space'
        self.project.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        LOCALAPPDATA=str(self.home / 'local'),
                        XDG_CONFIG_HOME=str(self.home / 'config'),
                        ORCHESTRATOR_CLAUDE_SESSION_ID=str(uuid.uuid4()))
        self.env.pop('ORCHESTRATOR_FAULT', None)
        self.env.pop('ORCHESTRATOR_INSTALL_FAULT', None)
        self.run_command([sys.executable, '-I', str(ROOT / 'engine/lib/ccx_install.py'),
                          'install', '--prefix', str(self.engine), '--bin-dir', str(self.base / 'bin')])
        self.run_command(['git', 'init', '-q', str(self.project)])
        (self.project / 'CLAUDE.md').write_bytes('# Project notes\r\nKeep ü.\r\n'.encode('utf-8'))
        (self.project / '.claude').mkdir()
        self.settings = {'env': {'USER_VALUE': 'preserve'}, 'permissions': {'deny': ['Bash(secret)']}}
        (self.project / '.claude/settings.local.json').write_text(json.dumps(self.settings), encoding='utf-8')
        self.original = (self.project / 'CLAUDE.md').read_bytes()

    def tearDown(self):
        self.temp.cleanup()

    def run_command(self, command, expected=0, stdin=None):
        result = subprocess.run(command, cwd=self.project, env=self.env, input=stdin,
                                capture_output=True, text=True, encoding='utf-8', timeout=45)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def cli(self, *args, expected=0):
        return self.run_command([sys.executable, str(self.engine / 'orchestrator.py'), *args], expected)

    def script(self, name, *args):
        return self.run_command([sys.executable, str(self.project / '.claude/scripts' / name), *args])

    def init(self):
        self.cli('init', '--release', '4.3.0', '--allow-unverified')

    def test_complete_project_lifecycle_and_preservation(self):
        self.init()
        self.cli('doctor')
        self.cli('verify')
        self.assertFalse(json.loads(self.script('task-state.py', 'status').stdout)['active'])
        self.assertTrue(json.loads(self.script('task-state.py', 'start').stdout)['active'])
        self.script('task-state.py', 'pause')
        self.script('context-monitor.py')
        self.cli('status', '--all')
        self.cli('projects')
        self.cli('backup')
        backups = list((self.engine / 'backups/projects').glob('*/*-manual'))
        self.assertTrue(backups)
        self.cli('backups')
        self.cli('rollback', '--apply', '--yes', '--backup', backups[0].name)
        self.cli('verify')
        self.cli('uninstall', '--apply', '--yes')
        settings = json.loads((self.project / '.claude/settings.local.json').read_text(encoding='utf-8'))
        self.assertEqual(settings, self.settings)
        # Existing text merging normalizes newlines intentionally; content survives.
        self.assertIn('Keep ü.', (self.project / 'CLAUDE.md').read_text(encoding='utf-8'))
        self.assertFalse((self.project / '.claude/orchestration.json').exists())

    def test_profile_approval_revoked_by_command_change(self):
        (self.project / 'package.json').write_text('{"scripts":{"test":"echo ok"}}', encoding='utf-8')
        self.init()
        self.cli('profile-approve', 'root-test', '--yes')
        profiles = self.project / '.claude/orchestration-profiles.json'
        data = json.loads(profiles.read_text(encoding='utf-8'))
        data['profiles']['root-test']['command'].append('changed')
        profiles.write_text(json.dumps(data), encoding='utf-8')
        result = subprocess.run([sys.executable, str(self.project / '.claude/scripts/managed-exec.py'),
                                 'root-test'], cwd=self.project, env=self.env,
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list((self.home / '.local/state/claude-codex').glob('*/managed-executions/*.log')))

    def test_candidate_requires_explicit_opt_in(self):
        self.cli('init', '--release', '4.3.0', expected=3)
        self.assertFalse((self.project / '.claude/orchestration.json').exists())


if __name__ == '__main__':
    unittest.main()
