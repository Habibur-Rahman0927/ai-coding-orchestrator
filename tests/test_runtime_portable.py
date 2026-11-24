"""Real host runtime checks; no platform simulation or agent authentication."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'engine/releases/4.3.0'
SCRIPTS = PAYLOAD / 'scripts'


class PortableRuntimeTests(unittest.TestCase):
    def run_controller(self, source, *options):
        return subprocess.run([sys.executable, str(SCRIPTS / 'recovery-controller.py'),
                               '--timeout', '8', *options, '--', sys.executable, '-c', source],
                              capture_output=True, text=True, timeout=25)

    def test_success_and_both_streams(self):
        result = self.run_controller('import sys; print("hello"); print("error",file=sys.stderr)')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('hello', result.stdout)
        self.assertIn('error', result.stderr)
        self.assertIn('EXECUTION_SUCCESS', result.stdout)

    def test_timeout_cleans_child_tree(self):
        with tempfile.TemporaryDirectory(prefix='ccx tree ü ') as temporary:
            marker = Path(temporary) / 'escaped'
            source = ('import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'
                      + repr('import time; from pathlib import Path; time.sleep(4); Path(' + repr(str(marker)) + ').touch()')
                      + ']); time.sleep(30)')
            result = self.run_controller(source, '--timeout', '1')
            self.assertEqual(result.returncode, 124, result.stdout + result.stderr)
            time.sleep(4)
            self.assertFalse(marker.exists())

    def test_parent_termination_cleans_owned_child(self):
        with tempfile.TemporaryDirectory(prefix='ccx parent ') as temporary:
            base = Path(temporary)
            ready, escaped = base / 'ready', base / 'escaped'
            child = ('from pathlib import Path; import time; Path(' + repr(str(ready))
                     + ').touch(); time.sleep(3); Path(' + repr(str(escaped)) + ').touch(); time.sleep(30)')
            command = [sys.executable, str(SCRIPTS / 'recovery-controller.py'), '--timeout', '10',
                       '--', sys.executable, '-c', child]
            launcher = subprocess.Popen([sys.executable, '-c',
                'import subprocess,time; subprocess.Popen(' + repr(command) +
                ',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); time.sleep(30)'])
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue(ready.exists())
                launcher.terminate()
                launcher.wait(timeout=5)
                time.sleep(3)
                self.assertFalse(escaped.exists())
            finally:
                if launcher.poll() is None:
                    launcher.kill()
                    launcher.wait(timeout=5)

    @unittest.skipIf(os.name == 'nt', 'Fault exercises the POSIX group adapter; Windows containment uses Job API')
    def test_initial_monitor_failure_still_cleans_owned_child(self):
        with tempfile.TemporaryDirectory(prefix='ccx monitor fault ') as temporary:
            base = Path(temporary)
            scripts = base / 'scripts'
            shutil.copytree(SCRIPTS, scripts)
            module = scripts / 'ccx_platform.py'
            with module.open('a', encoding='utf-8') as handle:
                handle.write('\n_original_snapshot = group_snapshot\n_fault_calls = 0\ndef group_snapshot(group_id):\n'
                             '    global _fault_calls\n    _fault_calls += 1\n'
                             '    if _fault_calls <= 2: raise OSError("controlled monitoring failure")\n'
                             '    return _original_snapshot(group_id)\n')
            escaped = base / 'escaped'
            child = 'import time; from pathlib import Path; time.sleep(2); Path(' + repr(str(escaped)) + ').touch()'
            result = subprocess.run([sys.executable, str(scripts / 'recovery-controller.py'), '--timeout', '5',
                                     '--', sys.executable, '-c', child], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 125, result.stdout + result.stderr)
            time.sleep(2)
            self.assertFalse(escaped.exists())
            self.assertIn('SUPERVISION_FAILED', result.stdout)

    def test_safe_lock_handles_retain_handoff_path(self):
        with tempfile.TemporaryDirectory(prefix='ccx lock metadata ') as temporary:
            lock = Path(temporary) / 'session.lock'
            source = ('import sys; from pathlib import Path; sys.path.insert(0,' + repr(str(SCRIPTS)) + '); '
                      'from ccx_runtime import safe_open; '
                      'h=safe_open(Path(' + repr(str(lock)) + '),"a"); '
                      'assert h.ccx_path == Path(' + repr(str(lock)) + ').resolve(); h.close()')
            result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows guardian handoff locking')
    def test_windows_caller_retains_management_lock_through_tail(self):
        with tempfile.TemporaryDirectory(prefix='ccx caller lock ') as temporary:
            directory = Path(temporary)
            source = (
                'import sys,subprocess; from pathlib import Path; sys.path.insert(0,' + repr(str(SCRIPTS)) + '); '
                'import ccx_platform as p; from ccx_runtime import serialize_session; '
                'handles=serialize_session(Path(' + repr(str(directory)) + '),"test-session"); '
                'assert len(handles)==2; '
                'probe=' + repr(
                    'import sys; from pathlib import Path; sys.path.insert(0,' + repr(str(SCRIPTS)) + '); '
                    'import ccx_platform as p; from ccx_runtime import safe_open; '
                    'h=safe_open(Path(' + repr(str(directory / 'management.lock')) + '),"a"); '
                    'p.flock(h,p.LOCK_EX|p.LOCK_NB)') + '; '
                'busy=subprocess.run([sys.executable,"-c",probe],capture_output=True); assert busy.returncode!=0; '
                '[h.close() for h in handles]; '
                'free=subprocess.run([sys.executable,"-c",probe],capture_output=True); assert free.returncode==0,free.stderr'
            )
            result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_atomic_state_write_does_not_follow_temporary_or_destination_links(self):
        with tempfile.TemporaryDirectory(prefix='ccx atomic state ') as temporary:
            base = Path(temporary)
            target, outside = base / 'state.json', base / 'outside'
            outside.write_bytes(b'untouched')
            try:
                target.with_suffix('.tmp').symlink_to(outside)
            except OSError as error:
                self.skipTest('Host does not permit file symlinks: ' + str(error))
            source = ('import sys; from pathlib import Path; sys.path.insert(0,' + repr(str(SCRIPTS)) + '); '
                      'from ccx_runtime import atomic_write; atomic_write(Path(' + repr(str(target)) + '),"new state")')
            result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outside.read_bytes(), b'untouched')
            self.assertEqual(target.read_text(), 'new state')
            self.assertFalse(list(base.glob('.ccx-state-*')))
            target.unlink()
            target.symlink_to(outside)
            refused = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn('link/reparse', refused.stderr)
            self.assertEqual(outside.read_bytes(), b'untouched')

    def test_watchdog_observes_real_process(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / 'watchdog.py'), '--pid', str(os.getpid()), '--once'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PROCESS_ALIVE', result.stdout)

    def test_retry_requires_explicit_idempotency(self):
        result = self.run_controller('pass', '--retries', '1')
        self.assertEqual(result.returncode, 2)
        self.assertIn('idempotent', result.stderr)

    def test_workflow_default_activation_gate_pause(self):
        with tempfile.TemporaryDirectory(prefix='ccx workflow ü ') as temporary:
            base = Path(temporary)
            project = base / 'project with spaces'
            shutil.copytree(PAYLOAD / 'scripts', project / '.claude/scripts')
            shutil.copytree(PAYLOAD / 'hooks', project / '.claude/hooks')
            session = str(uuid.uuid4())
            env = dict(os.environ, HOME=str(base / 'home'), USERPROFILE=str(base / 'home'),
                       LOCALAPPDATA=str(base / 'local'), ORCHESTRATOR_CLAUDE_SESSION_ID=session)
            (base / 'home').mkdir()
            task = project / '.claude/scripts/task-state.py'
            def run(*args):
                result = subprocess.run([sys.executable, str(task), *args], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            self.assertFalse(run('status')['active'])
            self.assertTrue(run('start')['active'])
            run('add', '--id', 'portable', '--title', 'Portable task')
            gate = subprocess.run([sys.executable, str(project / '.claude/hooks/completion-gate.py')],
                                  input=json.dumps({'session_id': session}), env=env,
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(gate.returncode, 0, gate.stderr)
            self.assertEqual(json.loads(gate.stdout)['decision'], 'block')
            self.assertFalse(run('pause')['active'])

    def test_mock_agent_persists_exact_session_without_authentication(self):
        with tempfile.TemporaryDirectory(prefix='ccx mocked agent ü ') as temporary:
            base = Path(temporary)
            project = base / 'project'
            shutil.copytree(PAYLOAD / 'scripts', project / '.claude/scripts')
            shutil.copytree(PAYLOAD / 'hooks', project / '.claude/hooks')
            home = base / 'home'
            home.mkdir()
            session, codex_id = str(uuid.uuid4()), str(uuid.uuid4())
            env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                       LOCALAPPDATA=str(base / 'local'), CODEX_HOME=str(home / '.codex'),
                       ORCHESTRATOR_CLAUDE_SESSION_ID=session)
            fake = project / 'fake_agent.py'
            fake.write_text(
                'import json,sys\nfrom pathlib import Path\n'
                'with Path(__file__).with_suffix(".calls").open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                'print(json.dumps({"type":"thread.started","thread_id":' + repr(codex_id) + '}),flush=True)\n'
                'print(json.dumps({"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}),flush=True)\n',
                encoding='utf-8')
            # Controlled agent mock only: all locking, containment, stream parsing,
            # integrity checks and persisted mapping use the real runtime.
            module = project / '.claude/scripts/ccx_platform.py'
            with module.open('a', encoding='utf-8') as handle:
                handle.write('\n_original_command_argv = command_argv\ndef command_argv(command):\n'
                             '    if command[0] == "codex": return [sys.executable, ' + repr(str(fake)) + '] + command[1:]\n'
                             '    return _original_command_argv(command)\n')
            project_id = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:16]
            state_root = ((base / 'local/claude-codex-orchestrator/state') if os.name == 'nt'
                          else home / '.local/state/claude-codex')
            manifest = state_root / project_id / 'integrity/manifest.json'
            manifest.parent.mkdir(parents=True)
            files = {path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (project / '.claude').rglob('*.py')}
            manifest.write_text(json.dumps({'project':str(project.resolve()),'files':files}), encoding='utf-8')
            script = project / '.claude/scripts/codex-session.py'
            for prompt in ('First read-only task', 'Continue the same task'):
                result = subprocess.run([sys.executable, str(script), prompt], cwd=project, env=env,
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in fake.with_suffix('.calls').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][0], 'exec')
            self.assertNotIn('resume', calls[0])
            self.assertEqual(calls[1][:2], ['exec', 'resume'])
            self.assertIn(codex_id, calls[1])
            self.assertNotIn('--last', calls[1])
            mapping = json.loads((state_root / project_id / (session + '.json')).read_text(encoding='utf-8'))
            self.assertEqual(mapping['codex_session_id'], codex_id)

    def test_session_start_exports_validated_identifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'session.env'
            session = str(uuid.uuid4())
            env = dict(os.environ, CLAUDE_ENV_FILE=str(path))
            result = subprocess.run([sys.executable, str(PAYLOAD / 'hooks/session-init.py')],
                                    input=json.dumps({'session_id':session}), env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), "export ORCHESTRATOR_CLAUDE_SESSION_ID='%s'\n" % session)

if __name__ == '__main__':
    unittest.main(verbosity=2)
