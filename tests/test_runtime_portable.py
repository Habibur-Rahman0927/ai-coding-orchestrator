"""Real host runtime checks; no platform simulation or agent authentication."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
import tempfile
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = ROOT / 'engine/releases/4.3.0'
SCRIPTS = PAYLOAD / 'scripts'


class PortableRuntimeTests(unittest.TestCase):
    @unittest.skipIf(os.name == 'nt', 'POSIX state permissions')
    def test_private_state_repairs_umask_and_legacy_modes_without_bytecode(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory(prefix='ccx private state ') as temporary:
                base = Path(temporary)
                home = base / 'home'
                project = base / 'project'
                shutil.copytree(PAYLOAD / 'scripts', project / '.claude/scripts')
                home.mkdir()
                ancestors = [home, home / '.local', home / '.local/state']
                for path in ancestors:
                    path.mkdir(mode=0o775, exist_ok=True)
                    path.chmod(0o775)
                root = home / '.local/state/claude-codex'
                project_id = hashlib.sha256(str(project.resolve()).encode()).hexdigest()[:16]
                if existing:
                    (root / project_id / 'tasks').mkdir(parents=True, mode=0o775)
                    for path in (root, root / project_id, root / project_id / 'tasks'):
                        path.chmod(0o775)
                env = dict(os.environ, HOME=str(home), ORCHESTRATOR_CLAUDE_SESSION_ID=str(uuid.uuid4()))
                env.pop('PYTHONPYCACHEPREFIX', None)
                env.pop('PYTHONDONTWRITEBYTECODE', None)
                # Explicitly remove Apple's cache prefix and enable bytecode: the
                # entry script, not the test interpreter's -B, must prevent it.
                source = ('import sys,os,runpy; sys.pycache_prefix=None; sys.dont_write_bytecode=False; '
                          'os.umask(0o002); script=sys.argv[1]; sys.argv=sys.argv[1:]; '
                          'sys.path.insert(0,os.path.dirname(script)); runpy.run_path(script,run_name="__main__")')
                for name, args in (('task-state.py', ['start']), ('codex-session.py', ['--status'])):
                    result = subprocess.run([sys.executable, '-c', source,
                                             str(project / '.claude/scripts' / name), *args],
                                            env=env, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse(list(project.rglob('__pycache__')))
                for path in (root, root / project_id, root / project_id / 'tasks'):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o700)
                for path in ancestors:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o775)

    @unittest.skipIf(os.name == 'nt', 'POSIX state links')
    def test_private_state_refuses_symlink_root_and_descendant(self):
        for link_root in (True, False):
            with self.subTest(link_root=link_root), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                home = base / 'home'
                root = home / '.local/state/claude-codex'
                outside = base / 'outside'
                outside.mkdir(mode=0o775)
                outside.chmod(0o775)
                link = root if link_root else root / 'project'
                link.parent.mkdir(parents=True)
                link.symlink_to(outside, target_is_directory=True)
                source = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                          'from ccx_runtime import private_directory; private_directory(Path(sys.argv[2]))')
                result = subprocess.run([sys.executable, '-B', '-c', source, str(SCRIPTS), str(link)],
                                        env=dict(os.environ, HOME=str(home)), capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('link', result.stderr)
                self.assertTrue(link.is_symlink())
                self.assertEqual(outside.stat().st_mode & 0o777, 0o775)
                self.assertEqual(list(outside.iterdir()), [])

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
            launcher = subprocess.Popen([sys.executable, '-B', '-c',
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
            result = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True, timeout=10)
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
                'busy=subprocess.run([sys.executable,"-B","-c",probe],capture_output=True); assert busy.returncode!=0; '
                '[h.close() for h in handles]; '
                'free=subprocess.run([sys.executable,"-B","-c",probe],capture_output=True); assert free.returncode==0,free.stderr'
            )
            result = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True, timeout=15)
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
            result = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(outside.read_bytes(), b'untouched')
            self.assertEqual(target.read_text(), 'new state')
            self.assertFalse(list(base.glob('.ccx-state-*')))
            target.unlink()
            target.symlink_to(outside)
            refused = subprocess.run([sys.executable, '-B', '-c', source], capture_output=True, text=True, timeout=10)
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
            bootstrap = ('import sys,os,runpy; sys.pycache_prefix=None; sys.dont_write_bytecode=False; '
                         'script=sys.argv[1]; sys.argv=sys.argv[1:]; '
                         'sys.path.insert(0,os.path.dirname(script)); runpy.run_path(script,run_name="__main__")')
            def run(*args):
                result = subprocess.run([sys.executable, '-c', bootstrap, str(task), *args], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return json.loads(result.stdout)
            self.assertFalse(run('status')['active'])
            self.assertTrue(run('start')['active'])
            run('add', '--id', 'portable', '--title', 'Portable task')
            gate = subprocess.run([sys.executable, '-c', bootstrap, str(project / '.claude/hooks/completion-gate.py')],
                                  input=json.dumps({'session_id': session}), env=env,
                                  capture_output=True, text=True, timeout=10)
            self.assertEqual(gate.returncode, 0, gate.stderr)
            self.assertEqual(json.loads(gate.stdout)['decision'], 'block')
            self.assertFalse(run('pause')['active'])
            self.assertFalse(list(project.rglob('__pycache__')))

    def test_mock_agent_persists_exact_session_without_authentication(self):
        self.check_mock_agent_session()

    def test_candidate_inherits_config_without_tomllib(self):
        self.check_mock_agent_session(block_tomllib=True)

    def check_mock_agent_session(self, block_tomllib=False):
        if os.name != 'nt':
            previous_umask = os.umask(0o002)
            self.addCleanup(os.umask, previous_umask)
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
            if block_tomllib:
                config = home / '.codex/config.toml'
                config.parent.mkdir()
                config_bytes = (b'model = "saved-model"\nmodel_reasoning_effort = "high"\n'
                                b'service_tier = "priority"\n')
                config.write_bytes(config_bytes)
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
            if os.name != 'nt':
                state_root.chmod(0o775)
            files = {path.relative_to(project).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (project / '.claude').rglob('*.py')}
            manifest.write_text(json.dumps({'project':str(project.resolve()),'files':files}), encoding='utf-8')
            script = project / '.claude/scripts/codex-session.py'
            command = [sys.executable, str(script)]
            if block_tomllib:
                bootstrap = ('import sys,runpy; from pathlib import Path; '
                             'sys.modules["tomllib"]=None; script=sys.argv[1]; sys.argv=sys.argv[1:]; '
                             'sys.path.insert(0,str(Path(script).parent)); '
                             'namespace=runpy.run_path(script,run_name="__main__"); '
                             'assert namespace["tomllib"] is None; '
                             'assert namespace["load_codex_defaults"]()=={}')
                command = [sys.executable, '-B', '-c', bootstrap, str(script)]
            for prompt in ('First read-only task', 'Continue the same task'):
                result = subprocess.run([*command, prompt], cwd=project, env=env,
                                        capture_output=True, text=True, timeout=25)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            calls = [json.loads(line) for line in fake.with_suffix('.calls').read_text(encoding='utf-8').splitlines()]
            self.assertEqual(len(calls), 2)
            if block_tomllib:
                self.assertEqual(config.read_bytes(), config_bytes)
                for call in calls:
                    self.assertNotIn('--model', call)
                    self.assertFalse(any(arg.startswith(('model_reasoning_effort=', 'service_tier='))
                                         for arg in call))
            if os.name != 'nt':
                self.assertEqual(state_root.stat().st_mode & 0o777, 0o700)
                self.assertEqual((state_root / project_id).stat().st_mode & 0o777, 0o700)
            self.assertFalse(list(project.rglob('__pycache__')))
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
