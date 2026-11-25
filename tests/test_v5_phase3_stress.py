"""Bounded local stress with real storage/processes and deterministic providers.

Set CCX_STRESS_REPORT to retain machine-readable measurements. These are local
samples, not paid-provider benchmarks or claims of long-duration soak coverage.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

import test_v5_workflows as fixtures
from ccx_workspace.store import Store
from ccx_workspace.workflows import WorkflowEngine
from ccx_workspace.tools import ScopedTools


class StressTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    create = fixtures.WorkflowTests.create
    authorize = fixtures.WorkflowTests.authorize
    measurements = []

    @classmethod
    def tearDownClass(cls):
        destination = os.environ.get('CCX_STRESS_REPORT')
        if destination:
            Path(destination).write_text(json.dumps({'live_provider_calls': 0,
                'mock_providers': True, 'measurements': cls.measurements}, indent=2) + '\n')

    def test_repeated_workflows_preserve_history_and_bound_context_cache(self):
        before = self.store.path.stat().st_size
        started = time.monotonic()
        identifiers = []
        calls = 0
        for number in range(12):
            identifier = self.create()
            self.authorize(identifier)
            registry = fixtures.MockRegistry(reject_once=number % 3 == 0)
            result = self.engine.run(identifier, registry)
            self.assertEqual(result['status'], 'COMPLETED', result['reason'])
            identifiers.append(identifier)
            calls += len(registry.calls)
            for task in result['tasks']:
                self.assertTrue(self.engine.verify_task(identifier, task['id'])['verified'])
        restored = WorkflowEngine(Store(self.store.path))
        self.assertEqual({w['id'] for w in restored.list(self.pid)}, set(identifiers))
        for identifier in identifiers:
            self.assertTrue(restored.checkpoints(identifier))
            self.assertTrue(restored.action_results(identifier))
        with self.store.connect() as db:
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM context_packages WHERE project_id=?', (self.pid,)).fetchone()[0], 20)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            actions = db.execute('SELECT COUNT(*) FROM w5_actions').fetchone()[0]
        self.measurements.append({'scenario': '12 sequential workflows; four correction rounds',
            'duration_seconds': round(time.monotonic() - started, 3), 'provider_mock_calls': calls,
            'durable_actions': actions, 'database_growth_bytes': self.store.path.stat().st_size - before})

    def test_duplicate_starts_are_blocked_while_other_project_runs(self):
        identifier = self.create()
        self.authorize(identifier)
        same_project = self.create()
        self.authorize(same_project)
        other_root = self.base / 'independent project'
        subprocess.run(['git', 'init', '-q', str(other_root)], check=True, capture_output=True)
        (other_root / 'app.txt').write_text('good')
        other_pid = self.store.register(other_root)['id']
        other = self.engine.create(other_pid, 'Verify independent app', ['app.txt contains good'])['id']
        self.engine.create_task(other, 'Verify independent app')
        self.authorize(other)
        entered, release = threading.Event(), threading.Event()
        registry = fixtures.MockRegistry()
        original = registry.invoke
        def waiting(provider, request):
            if request['role'] == 'executor':
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('Test barrier expired')
            return original(provider, request)
        registry.invoke = waiting
        result = []
        thread = threading.Thread(target=lambda: result.append(self.engine.run(identifier, registry)))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            for candidate in (identifier, identifier, same_project):
                blocked_registry = fixtures.MockRegistry()
                self.assertTrue(self.engine.run(candidate, blocked_registry)['busy'])
                self.assertEqual(blocked_registry.calls, [])
            independent = self.engine.run(other, fixtures.MockRegistry())
            self.assertEqual(independent['status'], 'COMPLETED', independent['reason'])
            self.assertTrue(thread.is_alive(), 'first project was not held at the test barrier')
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result[0]['status'], 'COMPLETED')
        self.assertEqual(registry.executions, 1)

    def test_pause_and_cancel_at_review_return_cannot_mark_verified(self):
        for operation in ('pause', 'cancel'):
            with self.subTest(operation=operation):
                identifier = self.create()
                self.authorize(identifier)
                entered, release = threading.Event(), threading.Event()
                registry = fixtures.MockRegistry()
                original = registry.invoke
                def waiting(provider, request):
                    response = original(provider, request)
                    if request['role'] == 'reviewer':
                        entered.set()
                        if not release.wait(10):
                            raise RuntimeError('Test barrier expired')
                    return response
                registry.invoke = waiting
                result = []
                thread = threading.Thread(target=lambda: result.append(self.engine.run(identifier, registry)))
                thread.start()
                try:
                    self.assertTrue(entered.wait(5))
                    getattr(self.engine, operation)(identifier)
                finally:
                    release.set()
                    thread.join(10)
                self.assertFalse(thread.is_alive())
                self.assertEqual(result[0]['status'], 'PAUSED' if operation == 'pause' else 'CANCELLED')
                self.assertNotEqual(result[0]['tasks'][0]['status'], 'VERIFIED')
                self.assertFalse(any(e['event'] == 'WORKFLOW_COMPLETED' for e in self.engine.checkpoints(identifier)))

    def test_quiet_healthy_command_runs_to_natural_completion(self):
        marker = self.base / 'quiet-complete'
        tools = ScopedTools(self.project, allowed_operations=['run_command'], approved_commands={
            'quiet': {'argv': [sys.executable, '-c',
                'import time; from pathlib import Path; time.sleep(1.5); Path(%r).write_text("done")' % str(marker)], 'timeout': 8}})
        started = time.monotonic()
        result = tools.execute('run_command', {'name': 'quiet'})
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(marker.read_text(), 'done')
        self.measurements.append({'scenario': 'healthy command with 1.5 seconds without output',
            'duration_seconds': round(time.monotonic() - started, 3), 'exit_code': result['exit_code']})

    def test_repeated_preapproved_failover_is_depth_bounded(self):
        identifier = self.create(budgets={'max_depth': 2, 'max_provider_calls': 8})
        self.authorize(identifier, ('codex', 'claude', 'minimax'))
        for provider in ('claude', 'minimax'):
            self.engine.approve(identifier, 'failover', {'role': 'reviewer', 'to_provider': provider})
        registry = fixtures.MockRegistry()
        original = registry.invoke
        def unavailable(provider, request):
            result = original(provider, request)
            if request['role'] == 'reviewer':
                result.update(status='failed', error_kind='usage_limit', output='')
            return result
        registry.invoke = unavailable
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(registry.executions, 1)
        self.assertEqual(registry.reviews, 3)
        self.assertEqual(sum(e['event'] == 'AUTOMATIC_ROLE_HANDOFF' for e in self.engine.checkpoints(identifier)), 2)
        self.engine.run(identifier, registry)
        self.assertEqual(len(registry.calls), 4)
        self.assertNotEqual(result['tasks'][0]['status'], 'VERIFIED')

    def test_malformed_usage_after_real_effect_requires_reconciliation(self):
        identifier = self.create()
        self.authorize(identifier)
        marker = self.base / 'effect-count'
        registry = fixtures.MockRegistry()
        original = registry.invoke
        def malformed(provider, request):
            result = original(provider, request)
            if request['role'] == 'executor':
                marker.write_text(str(int(marker.read_text()) + 1) if marker.exists() else '1')
                result['usage'] = {'input_tokens': {'invalid': 'shape'}}
            return result
        registry.invoke = malformed
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
        for unused in range(3):
            self.assertEqual(self.engine.run(identifier, registry)['status'], 'RECOVERY_REQUIRED')
        self.assertEqual(marker.read_text(), '1')
        self.assertEqual(registry.executions, 1)
        self.assertTrue(result['pending_actions'])

    def test_post_completion_edit_invalidates_current_evidence_without_deleting_history(self):
        identifier = self.create()
        self.authorize(identifier)
        result = self.engine.run(identifier, fixtures.MockRegistry())
        self.assertEqual(result['status'], 'COMPLETED')
        task = result['tasks'][0]['id']
        self.assertTrue(self.engine.verify_task(identifier, task)['verified'])
        checkpoints = self.engine.checkpoints(identifier)
        actions = self.engine.action_results(identifier)
        (self.project / 'app.txt').write_text('changed after verification')
        verification = WorkflowEngine(Store(self.store.path)).verify_task(identifier, task)
        self.assertFalse(verification['verified'])
        self.assertTrue(verification['recorded_verified'])
        self.assertNotEqual(verification['recorded_snapshot'], verification['current_snapshot'])
        self.assertEqual(self.engine.checkpoints(identifier), checkpoints)
        self.assertEqual(self.engine.action_results(identifier), actions)
        current = self.store.context(self.pid, 'Workflow verification')
        self.assertFalse(any(r['source'] == 'workflow:' + identifier for r in current['references']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
