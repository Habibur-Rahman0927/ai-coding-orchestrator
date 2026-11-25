#!/usr/bin/env python3
"""Bounded real-time local soak with isolated runtime/projects and mock providers.

No provider CLI or network API is invoked. Time is never accelerated. Progress is
written atomically at least every 15 seconds independently of active commands.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
try:
    import resource
except ImportError:
    resource = None

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


class FixtureRegistry:
    offline = True

    def __init__(self, mode='normal'):
        self.mode = mode
        self.calls = 0
        self.executions = 0
        self.reviews = 0

    def get(self, name):
        class Adapter:
            def status(self):
                return {'capabilities': {'scoped_tools': True}, 'model': 'deterministic-soak-fixture'}
        return Adapter()

    def invoke(self, provider, request):
        self.calls += 1
        role = request['role']
        prompt = json.loads(request['prompt'])
        result = {'status': 'completed', 'session_id': request.get('session_id') or str(uuid.uuid4()),
                  'usage': {'input_tokens': 20, 'output_tokens': 10}, 'output': ''}
        if self.mode == 'no_progress':
            result.update(status='incomplete', output='same incomplete response')
        elif role == 'planner':
            result['output'] = json.dumps({'tasks': [{'title': 'Validate the fixture'}]})
        elif role == 'executor':
            self.executions += 1
            path = Path(request['project']) / 'app.txt'
            if path.read_text() == 'bad':
                result.update(status='tool_calls', tool_calls=[{'id': 'repair-app', 'name': 'patch',
                    'arguments': {'path': 'app.txt', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'old': 'bad', 'new': 'good'}}])
            else:
                result['output'] = 'Ready for real engine test and separate mock review.'
        elif role == 'reviewer':
            self.reviews += 1
            accepted = not (self.mode == 'correction' and self.reviews == 1)
            result['output'] = json.dumps({'decision': 'approve' if accepted else 'changes_requested',
                'rationale': 'Deterministic review fixture; not live model verification.',
                'snapshot_hash': prompt['snapshot_hash'],
                'criteria': [{'criterion': criterion, 'met': accepted,
                              'evidence': 'Actual engine test exit status and exact source snapshot'}
                             for criterion in prompt['criteria']]})
        return result


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.pending')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    os.replace(temporary, path)



class ResourceLimit(RuntimeError):
    """A configured local resource floor prevents further fixture work."""


def resource_budget(directory, max_backup_bytes, minimum_free_bytes, next_backup_bytes=0):
    directory = Path(directory)
    backups = list(directory.glob('backup-*.sqlite3'))
    retained = sum(path.stat().st_size for path in backups)
    free = shutil.disk_usage(directory).free
    if free < minimum_free_bytes:
        raise ResourceLimit('Filesystem free space fell below the configured floor')
    reason = None
    if retained + next_backup_bytes > max_backup_bytes:
        reason = 'backup_byte_budget'
    elif free - next_backup_bytes < minimum_free_bytes:
        reason = 'free_space_headroom'
    return {'backup_count': len(backups), 'backup_bytes': retained, 'filesystem_free_bytes': free,
            'backup_allowed': reason is None, 'backup_skip_reason': reason}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--duration', type=float, default=900)
    parser.add_argument('--quiet-seconds', type=float, default=75)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--max-workflows', type=int, default=2000)
    parser.add_argument('--max-backup-bytes', type=int, default=256 * 1024 * 1024)
    parser.add_argument('--minimum-free-bytes', type=int, default=512 * 1024 * 1024)
    args = parser.parse_args(argv)
    if sys.flags.optimize or not __debug__:
        parser.error('Soak verification requires assertions enabled; remove -O and PYTHONOPTIMIZE')
    if args.max_backup_bytes < 0 or args.minimum_free_bytes < 1:
        parser.error('Use nonnegative max-backup-bytes and positive minimum-free-bytes')
    if not 1 <= args.duration <= 7200 or not 0 <= args.quiet_seconds <= min(600, args.duration):
        parser.error('Use duration1..7200 and quiet-seconds0..min(600,duration)')
    if not 1 <= args.max_workflows <= 5000:
        parser.error('max-workflows must be1..5000')
    started = time.monotonic()
    report = {'status': 'RUNNING', 'target_duration_seconds': args.duration, 'elapsed_seconds': 0,
              'platform': {'os': platform.system(), 'architecture': platform.machine(), 'python': platform.python_version()},
              'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'python_optimize': sys.flags.optimize, 'PYTHONOPTIMIZE': os.environ.get('PYTHONOPTIMIZE'),
              'max_backup_bytes': args.max_backup_bytes, 'minimum_free_bytes': args.minimum_free_bytes,
              'live_provider_calls': 0, 'providers': 'deterministic mocks only', 'runtime_isolated': True,
              'projects': 3, 'workflows': [], 'samples': [], 'failure': None,
              'quiet_command_seconds': args.quiet_seconds,
              'limitations': ['No live provider or native agent execution', 'No machine reboot',
                             'No30/60minute claim unless elapsed time meets that threshold',
                             'Resource samples belong to this harness and its owned local test children']}
    guard = threading.Lock()
    stopped = threading.Event()
    active = {'workflow': None, 'lease_observations': 0, 'last_lease': None}
    with tempfile.TemporaryDirectory(prefix='ccx-phase4-soak-') as temporary:
        base = Path(temporary).resolve()
        resource_budget(base, args.max_backup_bytes, args.minimum_free_bytes)
        runtime = base / 'runtime'
        shutil.copytree(ROOT / 'engine/lib', runtime / 'engine/lib')
        shutil.copytree(ROOT / 'engine/releases/4.3.0', runtime / 'engine/releases/4.3.0')
        sys.path.insert(0, str(runtime / 'engine/lib'))
        from ccx_workspace.store import Store
        from ccx_workspace.workflows import WorkflowEngine
        database = base / 'state/workspace.sqlite3'
        store = Store(database)
        projects = []
        for index in range(3):
            project = base / ('source-project-%d' % index)
            subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True)
            (project / 'app.txt').write_text('good')
            (project / 'AGENTS.md').write_text('Never deploy. Preserve project boundaries.\n')
            pid = store.register(project)['id']
            store.add_memory(pid, 'project', 'Architecture', 'isolated_architecture_%d' % index, kind='user_instruction')
            store.index(pid)
            projects.append((project, pid))
        report['runtime_source_sha256'] = hashlib.sha256(b''.join(
            p.relative_to(runtime).as_posix().encode() + p.read_bytes()
            for p in sorted(runtime.rglob('*')) if p.is_file())).hexdigest()

        def sample():
            sample = {'elapsed_seconds': round(time.monotonic() - started, 3),
                      'process_cpu_seconds': round(time.process_time(), 4),
                      'database_bytes': database.stat().st_size if database.exists() else 0}
            sample.update(resource_budget(base, args.max_backup_bytes, args.minimum_free_bytes))
            if resource:
                usage = resource.getrusage(resource.RUSAGE_SELF)
                sample['process_peak_rss_bytes'] = usage.ru_maxrss * (1 if sys.platform == 'darwin' else 1024)
                child = resource.getrusage(resource.RUSAGE_CHILDREN)
                sample['completed_child_cpu_seconds'] = round(child.ru_utime + child.ru_stime, 4)
            if Path('/proc/self/statm').exists():
                sample['process_current_rss_bytes'] = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
            with store.connect() as db:
                sample['memory_records'] = db.execute('SELECT COUNT(*) FROM memory').fetchone()[0]
                sample['context_packages'] = db.execute('SELECT COUNT(*) FROM context_packages').fetchone()[0]
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'w5_checkpoints' in tables:
                    sample['checkpoint_records'] = db.execute('SELECT COUNT(*) FROM w5_checkpoints').fetchone()[0]
                    sample['checkpoint_payload_bytes'] = db.execute('SELECT COALESCE(SUM(LENGTH(data)),0) FROM w5_checkpoints').fetchone()[0]
                with guard:
                    identifier = active['workflow']
                if identifier and 'w5_workflows' in tables:
                    row = db.execute('SELECT status,lease_until FROM w5_workflows WHERE id=?', (identifier,)).fetchone()
                    if row:
                        sample['active_status'] = row['status']
                        if row['status'] == 'RUNNING' and row['lease_until'] != active['last_lease']:
                            active['lease_observations'] += 1
                            active['last_lease'] = row['lease_until']
            with guard:
                report['elapsed_seconds'] = sample['elapsed_seconds']
                report['samples'].append(sample)
                report['healthy_lease_observations'] = active['lease_observations']
                report['progress_json_bytes_before_write'] = args.output.stat().st_size if args.output.exists() else 0
                atomic_json(args.output, report)

        def monitor():
            while not stopped.wait(15):
                try:
                    sample()
                except Exception as error:
                    with guard:
                        report['monitor_error'] = type(error).__name__ + ': ' + str(error)
                    stopped.set()
                    return

        thread = threading.Thread(target=monitor, daemon=True)
        sample()
        thread.start()
        try:
            index = 0
            while time.monotonic() - started < args.duration and index < args.max_workflows and not stopped.is_set():
                resource_budget(base, args.max_backup_bytes, args.minimum_free_bytes)
                project, pid = projects[index % 3]
                # Every workflow gets a fresh controller/store instance.
                fresh = Store(database)
                engine = WorkflowEngine(fresh)
                context = fresh.context(pid, 'Architecture', budget=400)
                assert 'isolated_architecture_%d' % (index % 3) in context['content']
                assert all('isolated_architecture_%d' % other not in context['content'] for other in range(3) if other != index % 3)
                mode = 'normal' if index == 0 else 'failed_test' if index % 11 == 0 else 'no_progress' if index % 7 == 0 else 'correction' if index % 5 == 0 else 'normal'
                quiet = args.quiet_seconds if index == 0 else min(1, max(0, args.duration - (time.monotonic() - started)))
                if mode == 'correction':
                    (project / 'app.txt').write_text('bad')
                flow = engine.create(pid, 'Keep app.txt correct', ['app.txt contains good'],
                    providers={'planner': 'codex', 'executor': 'codex', 'reviewer': 'minimax'},
                    budgets={'max_seconds': max(30, int(quiet) + 30), 'call_timeout': max(15, int(quiet) + 15),
                             'max_retries': 0 if mode == 'failed_test' else 2, 'max_provider_calls': 12})
                if mode != 'no_progress':
                    engine.create_task(flow['id'], 'Validate fixture and retained context')
                for provider in ('codex', 'minimax'):
                    engine.approve(flow['id'], 'sharing', {'provider': provider})
                engine.approve(flow['id'], 'operations', {'operations': ['patch']})
                command = ('import time; from pathlib import Path; time.sleep(%r); assert Path("app.txt").read_text()=="good"' % quiet)
                if mode == 'failed_test':
                    command = 'raise SystemExit(9)'
                engine.approve(flow['id'], 'command', {'name': 'acceptance', 'argv': [sys.executable, '-B', '-c', command], 'timeout': max(15, int(quiet) + 15)})
                registry = FixtureRegistry(mode)
                with guard:
                    active['workflow'] = flow['id']
                mark = time.monotonic()
                result = engine.run(flow['id'], registry)
                expected = 'BLOCKED' if mode in ('failed_test', 'no_progress') else 'COMPLETED'
                assert result['status'] == expected, '%s expected%s got%s: %s' % (mode, expected, result['status'], result.get('reason'))
                if mode == 'no_progress':
                    assert registry.calls <= 2, 'No-progress loop exceeded bounded fixture contract'
                if expected == 'COMPLETED':
                    assert result['tasks'][0]['status'] == 'VERIFIED'
                    assert result['tasks'][0]['evidence']['tests']['passed']
                    assert any(m['source'] == 'workflow:' + flow['id'] for m in Store(database).memories(pid))
                    if mode == 'correction':
                        assert registry.reviews == 2 and (project / 'app.txt').read_text() == 'good'
                else:
                    assert not any(t['status'] == 'VERIFIED' for t in result['tasks'])
                with fresh.connect() as db:
                    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                item = {'id': flow['id'], 'project_index': index % 3, 'mode': mode, 'status': result['status'],
                        'provider_mock_calls': registry.calls, 'duration_seconds': round(time.monotonic() - mark, 3),
                        'executor_calls': registry.executions, 'reviewer_calls': registry.reviews}
                if index % 10 == 0:
                    capacity = resource_budget(base, args.max_backup_bytes, args.minimum_free_bytes,
                                               next_backup_bytes=database.stat().st_size)
                    if capacity['backup_allowed']:
                        backup = base / ('backup-%d.sqlite3' % index)
                        fresh.backup(backup)
                        recovered = Store(backup)
                        assert recovered.memories(pid) == fresh.memories(pid)
                        item['backup_reopen_verified'] = True
                    else:
                        item['backup_skipped'] = capacity['backup_skip_reason']
                with guard:
                    report['workflows'].append(item)
                    active['workflow'] = None
                index += 1
                sample()
            if report.get('monitor_error'):
                raise RuntimeError(report['monitor_error'])
            elapsed = time.monotonic() - started
            report['status'] = 'PASSED' if elapsed >= args.duration else 'CAPPED_EARLY'
            report['elapsed_seconds'] = round(elapsed, 3)
            report['actual_duration_met'] = elapsed >= args.duration
        except BaseException as error:
            report['status'] = 'RESOURCE_LIMIT' if isinstance(error, ResourceLimit) else 'FAILED'
            report['failure'] = {'type': type(error).__name__, 'message': str(error)}
        finally:
            stopped.set()
            thread.join(timeout=20)
            with guard:
                active['workflow'] = None
            try:
                sample()
            except ResourceLimit:
                report['elapsed_seconds'] = round(time.monotonic() - started, 3)
            report['completed_workflows'] = sum(w['status'] == 'COMPLETED' for w in report['workflows'])
            report['expected_blocked_workflows'] = sum(w['status'] == 'BLOCKED' for w in report['workflows'])
            report['total_workflows'] = len(report['workflows'])
            atomic_json(args.output, report)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text('# Controlled local soak\n\n'
            'Status: **%s**. Actual wall duration: **%.3f seconds**; target: %.0f seconds.\n\n'
            '%d workflows: %d completed and verified by engine checks with mock reviewers; '
            '%d intentionally blocked. Live provider calls: **0**.\n\n'
            'The runtime was copied into a disposable directory and exercised three separate generated Git projects. '
            'Actual SQLite, approved subprocesses, scoped patches, context retrieval, controller reopen, and backups were used. '
            'A %.0f-second quiet command exercised healthy running lease renewal. '
            'No-progress and failed-test fixtures were required to stop in bounded blocked states.\n\n'
            'Progress JSON: `%s`. It contains measured memory/CPU/database/checkpoint growth, workflow IDs and outcomes. '
            'RSS is a process observation, not proof of absence of leaks. Provider decisions are deterministic fixtures, '
            'not real independent-model acceptance. No machine reboot, native Windows/macOS soak, or 30/60-minute run is claimed.\n'
            % (report['status'], report['elapsed_seconds'], args.duration, report['total_workflows'],
               report['completed_workflows'], report['expected_blocked_workflows'], args.quiet_seconds, args.output))
    print(json.dumps({key: report.get(key) for key in ('status', 'elapsed_seconds', 'total_workflows', 'failure')}))
    return 0 if report['status'] == 'PASSED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
