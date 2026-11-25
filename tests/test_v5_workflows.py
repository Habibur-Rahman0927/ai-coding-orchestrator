"""Offline orchestration tests with real SQLite, filesystem, and test subprocesses."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.workflows import WorkflowEngine, snapshot


class MockRegistry:
    offline = True
    def __init__(self, reject_once=False, same_session=False, crash=False, tool=False):
        self.calls = []
        self.reject_once, self.same_session, self.crash, self.tool = reject_once, same_session, crash, tool
        self.reviews = 0
        self.executions = 0

    def get(self, name):
        class Adapter:
            def status(self):
                return {'capabilities': {'scoped_tools': True}}
        return Adapter()

    def invoke(self, provider, request):
        prompt = json.loads(request['prompt'])
        self.calls.append((provider, request['role'], prompt))
        role = request['role']
        session = request.get('session_id') or ('same' if self.same_session else str(uuid.uuid4()))
        result = {'status': 'completed', 'session_id': session, 'usage': {'input_tokens': 20, 'output_tokens': 10}, 'output': ''}
        if role == 'planner':
            result['output'] = json.dumps({'tasks': [{'title': 'Implement the criterion'}]})
        elif role == 'executor':
            self.executions += 1
            if self.crash:
                self.crash = False
                raise RuntimeError('simulated connection loss after dispatch')
            if self.tool and self.executions == 1:
                path = Path(request['project']) / 'app.txt'
                call = {'id': 'edit-1', 'name': 'patch', 'arguments': {'path': 'app.txt',
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'old': 'bad', 'new': 'good'}}
                result.update(status='tool_calls', tool_calls=[call], output='')
            else:
                result['output'] = 'Executor claims completion; engine must independently test.'
        elif role == 'reviewer':
            self.reviews += 1
            decision = 'changes_requested' if self.reject_once and self.reviews == 1 else 'approve'
            result['output'] = json.dumps({'decision': decision, 'rationale': 'Inspected actual project and trusted test record',
                'snapshot_hash': prompt['snapshot_hash'],
                'criteria': [{'criterion': c, 'met': decision == 'approve', 'evidence': 'app.txt content and test exit code'} for c in prompt['criteria']]})
        return result


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ccx-v5-workflow-')
        self.base = Path(self.temp.name).resolve()
        self.project = self.base / 'project with spaces'
        self.project.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.project)], check=True, capture_output=True)
        (self.project / 'app.txt').write_text('good', encoding='utf-8')
        self.store = Store(self.base / 'state/workspace.sqlite')
        self.pid = self.store.register(self.project)['id']
        self.engine = WorkflowEngine(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, executor='codex', reviewer='claude', budgets=None, task=True):
        workflow = self.engine.create(self.pid, 'Make the app correct', ['app.txt contains good'],
            providers={'executor': executor, 'reviewer': reviewer}, budgets=budgets)
        if task:
            self.engine.create_task(workflow['id'], 'Correct app.txt')
        return workflow['id']

    def authorize(self, identifier, providers=('claude', 'codex'), test=True):
        for provider in providers:
            self.engine.approve(identifier, 'sharing', {'provider': provider})
        if test:
            self.engine.approve(identifier, 'command', {'name': 'acceptance', 'argv': [sys.executable, '-c',
                'from pathlib import Path; assert Path("app.txt").read_text()=="good"'], 'timeout': 15})

    def test_all_six_cross_provider_delegation_directions(self):
        for source, destination in itertools.permutations(('claude', 'codex', 'minimax'), 2):
            with self.subTest(source=source, destination=destination):
                identifier = self.create(source, destination)
                task = self.engine.status(identifier)['tasks'][0]
                delegated = self.engine.delegate(task['id'], destination, source)
                self.assertEqual((delegated['executor'], delegated['reviewer']), (destination, source))
                self.authorize(identifier, (source, destination))
                registry = MockRegistry()
                result = self.engine.run(identifier, registry)
                self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
                self.assertEqual([c[:2] for c in registry.calls], [(destination, 'executor'), (source, 'reviewer')])
                self.assertTrue(result['tasks'][0]['evidence']['tests']['passed'])

    def test_independent_review_correction_loop_is_bounded_and_durable(self):
        identifier = self.create()
        self.authorize(identifier)
        registry = MockRegistry(reject_once=True)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual((registry.executions, registry.reviews), (2, 2))
        self.assertEqual(result['tasks'][0]['attempts'], 1)
        reopened = WorkflowEngine(Store(self.store.path)).status(identifier)
        self.assertEqual(reopened['tasks'][0]['status'], 'VERIFIED')
        self.assertTrue(any(c['event'] == 'CORRECTION_REQUIRED' for c in self.engine.checkpoints(identifier)))
        memories = self.store.memories(self.pid)
        self.assertTrue(any(m['scope'] == 'verification' and m['kind'] == 'verified' for m in memories))

    def test_same_provider_requires_distinct_actual_review_session(self):
        identifier = self.create('codex', 'codex')
        self.authorize(identifier, ('codex',))
        result = self.engine.run(identifier, MockRegistry())
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        identifier = self.create('codex', 'codex')
        self.authorize(identifier, ('codex',))
        result = self.engine.run(identifier, MockRegistry(same_session=True))
        self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
        self.assertNotEqual(result['tasks'][0]['status'], 'VERIFIED')

    def test_executor_claim_cannot_replace_real_test_evidence(self):
        identifier = self.create(budgets={'max_retries': 0})
        self.authorize(identifier, test=False)
        self.engine.approve(identifier, 'command', {'name': 'failing', 'argv': [sys.executable, '-c', 'raise SystemExit(9)']})
        registry = MockRegistry()
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(registry.reviews, 0)
        self.assertEqual(result['tasks'][0]['evidence']['tests']['commands'][0]['exit_code'], 9)

    def test_stale_review_snapshot_is_not_verification(self):
        identifier = self.create(budgets={'max_retries': 0})
        self.authorize(identifier)
        class BadReview(MockRegistry):
            def invoke(self, provider, request):
                result = super().invoke(provider, request)
                if request['role'] == 'reviewer':
                    value = json.loads(result['output']); value['snapshot_hash'] = 'stale'
                    result['output'] = json.dumps(value)
                return result
        self.assertEqual(self.engine.run(identifier, BadReview())['status'], 'BLOCKED')

    def test_unknown_provider_outcome_requires_explicit_recovery_not_auto_replay(self):
        identifier = self.create()
        self.authorize(identifier)
        registry = MockRegistry(crash=True)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'RECOVERY_REQUIRED')
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'RECOVERY_REQUIRED')
        self.assertEqual(len(registry.calls), 1)
        with self.assertRaises(PermissionError):
            self.engine.resume(identifier)
        action = result['pending_actions'][0]['id']
        self.engine.approve(identifier, 'recovery', {'action_id': action, 'decision': 'retry'})
        self.engine.resume(identifier)
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'COMPLETED')

    def test_checkpoint_replays_saved_result_without_repeating_executor(self):
        identifier = self.create()
        self.authorize(identifier)
        registry = MockRegistry()
        original = self.engine._task_evidence
        def interrupt(task_id, status, *args, **kwargs):
            if status == 'TESTING':
                raise KeyboardInterrupt('crash after provider result committed')
            return original(task_id, status, *args, **kwargs)
        self.engine._task_evidence = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.engine.run(identifier, registry)
        reopened = WorkflowEngine(Store(self.store.path))
        result = reopened.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual(registry.executions, 1)

    def test_model_cannot_grant_approval_or_write_without_operator_scope(self):
        identifier = self.create()
        registry = MockRegistry(tool=True)
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'APPROVAL_REQUIRED')
        self.assertEqual(registry.calls, [])
        with self.assertRaises(PermissionError):
            self.engine.approve(identifier, 'sharing', {'provider': 'codex'}, actor='provider')
        self.authorize(identifier)
        (self.project / 'app.txt').write_text('bad', encoding='utf-8')
        self.engine.approve(identifier, 'operations', {'operations': ['patch']})
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'COMPLETED')
        self.assertEqual((self.project / 'app.txt').read_text(), 'good')
        self.assertTrue(any(c['event'] == 'SCOPED_TOOL_STARTED' for c in self.engine.checkpoints(identifier)))

    def test_automatic_planning_and_task_relevant_context(self):
        self.store.index(self.pid)
        identifier = self.create(task=False)
        self.authorize(identifier)
        registry = MockRegistry()
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual(registry.calls[0][1], 'planner')
        for _, _, prompt in registry.calls:
            self.assertIn('Make the app correct', prompt['context']['content'])
            self.assertIn('app.txt contains good', prompt['context']['content'])
            self.assertNotIn('machine', prompt['context'])

    def test_future_provider_does_not_require_core_edit(self):
        identifier = self.create('future_adapter', 'claude')
        self.authorize(identifier, ('future_adapter', 'claude'))
        self.assertEqual(self.engine.run(identifier, MockRegistry())['status'], 'COMPLETED')

    def test_unknown_cost_is_reserved_not_silently_zero(self):
        identifier = self.create(budgets={'max_cost': 1.0})
        self.authorize(identifier)
        registry = MockRegistry(); registry.offline = False
        for provider in ('claude', 'codex'):
            self.engine.approve(identifier, 'cost', {'provider': provider, 'max_cost': 1.0, 'max_call_cost': .2})
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertAlmostEqual(result['cost_used'], .4)

    def test_task_depth_count_token_and_concurrency_guards(self):
        identifier = self.create(budgets={'max_tasks': 2, 'max_depth': 0, 'max_tokens': 64})
        task = self.engine.status(identifier)['tasks'][0]
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier, 'Too deep', parent_id=task['id'])
        self.engine.create_task(identifier, 'Second task')
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier, 'Third task')
        self.authorize(identifier)
        registry = MockRegistry()
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'BUDGET_EXHAUSTED')
        self.assertFalse(registry.calls)

    def test_failover_requires_transition_and_destination_sharing_approvals(self):
        identifier = self.create()
        task = self.engine.status(identifier)['tasks'][0]
        with self.assertRaises(PermissionError):
            self.engine.failover(task['id'], 'minimax')
        self.engine.approve(identifier, 'failover', {'task_id': task['id'], 'to_provider': 'minimax'})
        self.engine.failover(task['id'], 'minimax')
        registry = MockRegistry()
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'APPROVAL_REQUIRED')
        self.assertFalse(registry.calls)
        self.authorize(identifier, ('minimax', 'codex'))
        self.assertEqual(self.engine.run(identifier, registry)['status'], 'COMPLETED')

    def test_project_lease_blocks_overlap_and_cancel_is_preserved(self):
        identifier = self.create()
        other = self.create()
        self.authorize(identifier)
        self.authorize(other)
        entered = threading.Event()
        class WaitingRegistry(MockRegistry):
            def invoke(inner, provider, request):
                entered.set()
                deadline = time.monotonic() + 5
                while not request['cancel_event'].is_set() and time.monotonic() < deadline:
                    time.sleep(.02)
                return {'status': 'cancelled', 'session_id': 'cancelled-session', 'output': '', 'usage': {}}
        result = {}
        thread = threading.Thread(target=lambda: result.update(self.engine.run(identifier, WaitingRegistry())))
        thread.start()
        self.assertTrue(entered.wait(3))
        second = MockRegistry()
        self.assertTrue(self.engine.run(other, second)['busy'])
        self.assertFalse(second.calls)
        self.engine.cancel(identifier)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertNotEqual(result['tasks'][0]['status'], 'VERIFIED')

    def test_nonfinite_budget_and_unapproved_patch_are_rejected(self):
        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                self.create(budgets={'max_cost': value})
        identifier = self.create(budgets={'max_retries': 0})
        self.authorize(identifier)
        (self.project / 'app.txt').write_text('bad', encoding='utf-8')
        result = self.engine.run(identifier, MockRegistry(tool=True))
        self.assertEqual((self.project / 'app.txt').read_text(), 'bad')
        self.assertEqual(result['status'], 'BLOCKED')

    def test_custom_exclusions_are_not_fingerprinted(self):
        (self.project / 'internal.txt').write_text('private', encoding='utf-8')
        before = snapshot(self.project, exclusions=['internal.txt'])['hash']
        (self.project / 'internal.txt').write_text('changed private', encoding='utf-8')
        self.assertEqual(snapshot(self.project, exclusions=['internal.txt'])['hash'], before)

    def test_multitask_plan_executes_all_steps_before_final_acceptance(self):
        identifier = self.create()
        self.engine.create_task(identifier, 'Second necessary step')
        self.authorize(identifier, test=False)
        self.engine.approve(identifier, 'command', {'name': 'both_steps', 'argv': [sys.executable, '-c',
            'from pathlib import Path; assert Path("step1.txt").exists() and Path("step2.txt").exists()']})
        class MultiStep(MockRegistry):
            def invoke(inner, provider, request):
                result = super().invoke(provider, request)
                if request['role'] == 'executor':
                    (Path(request['project']) / ('step%d.txt' % inner.executions)).write_text('done', encoding='utf-8')
                return result
        registry = MultiStep()
        result = self.engine.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual(registry.executions, 2)
        self.assertEqual([c[1] for c in registry.calls[:2]], ['executor', 'executor'])

    def test_concurrent_task_creation_cannot_exceed_count_budget(self):
        identifier = self.create(budgets={'max_tasks': 2})
        barrier = threading.Barrier(3)
        results = []
        def add():
            barrier.wait()
            try:
                self.engine.create_task(identifier, 'Concurrent task')
                results.append('created')
            except ValueError:
                results.append('refused')
        threads = [threading.Thread(target=add) for _ in range(2)]
        for thread in threads: thread.start()
        barrier.wait()
        for thread in threads: thread.join(timeout=5)
        self.assertEqual(sorted(results), ['created', 'refused'])
        self.assertEqual(len(self.engine.status(identifier)['tasks']), 2)

    def test_crash_after_test_dispatch_requires_recovery_without_reexecuting_agent(self):
        identifier = self.create()
        self.authorize(identifier)
        registry = MockRegistry()
        original = self.engine._tools
        class InterruptedTool:
            def __init__(self, real): self.real = real
            def execute(self, name, arguments):
                self.real.execute(name, arguments)
                raise KeyboardInterrupt('crash before trusted test result checkpoint')
        self.engine._tools = lambda *args, **kwargs: InterruptedTool(original(*args, **kwargs))
        with self.assertRaises(KeyboardInterrupt):
            self.engine.run(identifier, registry)
        reopened = WorkflowEngine(Store(self.store.path))
        state = reopened.run(identifier, registry)
        self.assertEqual(state['status'], 'RECOVERY_REQUIRED')
        action = reopened.status(identifier)['pending_actions'][0]
        self.assertTrue(action['role'].startswith('test:'))
        reopened.approve(identifier, 'recovery', {'action_id': action['id'], 'decision': 'retry'})
        reopened.resume(identifier)
        result = reopened.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual(registry.executions, 1)

    def test_completed_test_checkpoint_is_reused_before_evidence_commit(self):
        (self.project / '.gitignore').write_text('count.txt\n', encoding='utf-8')
        identifier = self.create()
        self.authorize(identifier, test=False)
        self.engine.approve(identifier, 'command', {'name': 'counted_test', 'argv': [sys.executable, '-c',
            'from pathlib import Path; p=Path("count.txt"); p.write_text(str(int(p.read_text())+1) if p.exists() else "1"); assert Path("app.txt").read_text()=="good"']})
        original = self.engine._execute_tool
        def crash(*args, **kwargs):
            result = original(*args, **kwargs)
            raise KeyboardInterrupt('crash after command result durable but before test evidence')
        self.engine._execute_tool = crash
        registry = MockRegistry()
        with self.assertRaises(KeyboardInterrupt):
            self.engine.run(identifier, registry)
        reopened = WorkflowEngine(Store(self.store.path))
        result = reopened.run(identifier, registry)
        self.assertEqual(result['status'], 'COMPLETED', result.get('reason'))
        self.assertEqual((self.project / 'count.txt').read_text(), '1')
        self.assertEqual(registry.executions, 1)
        self.assertTrue(result['tasks'][0]['evidence']['tests']['commands'][0]['replayed'])

    def test_sensitive_files_excluded_from_snapshot(self):
        before = snapshot(self.project)['hash']
        (self.project / '.env').write_text('password=private-value-never-read', encoding='utf-8')
        self.assertEqual(snapshot(self.project)['hash'], before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
