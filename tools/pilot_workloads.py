#!/usr/bin/env python3
"""Isolated local pilot workloads: actual engine/tools, deterministic providers.

No live-provider implementation is reachable from this harness. Generated source
repositories and runtime databases live in separate temporary directories. The
executor emits scoped patch requests; it never edits project files directly.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine/lib'))
from ccx_workspace.store import Store
from ccx_workspace.workflows import WorkflowEngine


def scenarios():
    return {
        'A': {
            'name': 'Backend calculation defect and reviewer correction',
            'objective': 'Correct line totals including zero quantity without changing the function signature',
            'criteria': ['line_total multiplies price by quantity', 'zero quantity returns zero'],
            'initial': {'billing.py': 'def line_total(price, quantity):\n    return price + quantity\n'},
            'first': {'billing.py': 'def line_total(price, quantity):\n    return price * quantity if quantity else price\n'},
            'desired': {'billing.py': 'def line_total(price, quantity):\n    return price * quantity\n',
                        'test_acceptance.py': 'from billing import line_total\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_regular_total(self): self.assertEqual(line_total(7, 3), 21)\n    def test_zero_quantity(self): self.assertEqual(line_total(7, 0), 0)\n'},
            'tests': 'from billing import line_total\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_regular_total(self): self.assertEqual(line_total(7, 3), 21)\n',
            'review_defect': True,
        },
        'B': {'name': 'Frontend counter reset verified by actual browser interaction',
         'objective': 'Fix the counter Reset control while retaining increment behavior and '
                      'keyboard-native buttons',
         'criteria': ['Counter initially displays zero',
                      'Two Increment clicks display two',
                      'Reset click returns count to zero',
                      'Browser has no JavaScript exceptions'],
         'initial': {'index.html': '<!doctype html>\n'
                                   '<html lang="en"><head><meta charset="utf-8"><title>Isolated counter '
                                   'fixture</title></head>\n'
                                   '<body><h1>Counter</h1><output id="count">0</output>\n'
                                   '<button id="increment">Increment</button><button '
                                   'id="reset">Reset</button>\n'
                                   '<script>\n'
                                   'let count = 0;\n'
                                   "const output = document.querySelector('#count');\n"
                                   "document.querySelector('#increment').onclick = () => { count += 1; "
                                   'output.textContent = count; };\n'
                                   "document.querySelector('#reset').onclick = () => { count = 1; "
                                   'output.textContent = count; };\n'
                                   '</script></body></html>\n'},
         'desired': {'index.html': '<!doctype html>\n'
                                   '<html lang="en"><head><meta charset="utf-8"><title>Isolated counter '
                                   'fixture</title></head>\n'
                                   '<body><h1>Counter</h1><output id="count">0</output>\n'
                                   '<button id="increment">Increment</button><button '
                                   'id="reset">Reset</button>\n'
                                   '<script>\n'
                                   'let count = 0;\n'
                                   "const output = document.querySelector('#count');\n"
                                   "document.querySelector('#increment').onclick = () => { count += 1; "
                                   'output.textContent = count; };\n'
                                   "document.querySelector('#reset').onclick = () => { count = 0; "
                                   'output.textContent = count; };\n'
                                   '</script></body></html>\n'},
         'tests': '',
         'browser': True},
        'C': {
            'name': 'Local API handler failure contract (no HTTP listener)',
            'objective': 'Preserve successful lookup responses and normalize transient upstream failures',
            'criteria': ['Successful lookup retains status 200 and name', 'Timeout and connection failures return status 503 and temporary upstream error', 'Legacy empty-string names remain supported'],
            'convention': 'API lookup convention: preserve successful status 200; transient upstream exceptions return status 503 with a stable temporary upstream error.',
            'initial': {'api.py': 'def lookup(transport):\n    return {"status": 200, "name": transport()}\n'},
            'desired': {'api.py': 'def lookup(transport):\n    try:\n        return {"status": 200, "name": transport()}\n    except (TimeoutError, ConnectionError):\n        return {"status": 503, "error": "temporary upstream"}\n'},
            'tests': 'from api import lookup\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_success(self): self.assertEqual(lookup(lambda: "Ada"), {"status": 200, "name": "Ada"})\n    def test_legacy_empty_name(self): self.assertEqual(lookup(lambda: ""), {"status": 200, "name": ""})\n    def test_transient_errors(self):\n        for error in (TimeoutError, ConnectionError):\n            def fail(): raise error("synthetic unavailable")\n            self.assertEqual(lookup(fail), {"status": 503, "error": "temporary upstream"})\n',
        },
        'D': {'name': 'Stable deduplication algorithmic bottleneck',
         'objective': 'Reduce stable deduplication work for hashable values without changing result order '
                      'or edge behavior',
         'criteria': ['Stable deduplication preserves first occurrence order',
                      'Empty repeated and negative inputs retain correct results',
                      'For 1024 controlled values deduplication uses no more than 8192 equality and '
                      'hashing operations'],
         'initial': {'dedupe.py': 'def unique(items):\n'
                                  '    result = []\n'
                                  '    for item in items:\n'
                                  '        if item not in result:\n'
                                  '            result.append(item)\n'
                                  '    return result\n'},
         'desired': {'dedupe.py': 'def unique(items):\n    return list(dict.fromkeys(items))\n'},
         'performance': True,
         'correctness_test': 'test_acceptance.Acceptance.test_semantics',
         'tests': 'from dedupe import unique\n'
                  'import unittest\n'
                  'class Probe:\n'
                  '    work = 0\n'
                  '    def __init__(self, value): self.value = value\n'
                  '    def __hash__(self):\n'
                  '        Probe.work += 1\n'
                  '        return hash(self.value)\n'
                  '    def __eq__(self, other):\n'
                  '        Probe.work += 1\n'
                  '        return isinstance(other, Probe) and self.value == other.value\n'
                  'class Acceptance(unittest.TestCase):\n'
                  '    def test_semantics(self):\n'
                  '        for data, expected in (([], []), ([1, 1], [1]), ([2, -1, 2, 0, -1], [2, -1, '
                  '0])):\n'
                  '            self.assertEqual(unique(data), expected)\n'
                  '    def test_bounded_algorithm_work(self):\n'
                  '        data = [Probe(v) for v in list(range(512)) * 2]\n'
                  '        Probe.work = 0\n'
                  '        result = unique(data)\n'
                  '        work = Probe.work\n'
                  '        self.assertEqual([v.value for v in result], list(range(512)))\n'
                  "        self.assertLessEqual(work, 8192, 'deduplication exceeds public operation "
                  "budget')\n"},
        'E': {
            'name': 'Multi-file refactor with compatibility acceptance',
            'objective': 'Extract normalization into a reusable module while preserving render behavior',
            'criteria': ['normalization is supplied by normalize.py', 'render preserves trimmed uppercase output', 'Empty and Unicode input remain supported'],
            'initial': {'render.py': 'def render(value):\n    return value.strip().upper()\n'},
            'desired': {'normalize.py': 'def normalize(value):\n    return value.strip().upper()\n',
                        'render.py': 'from normalize import normalize\n\ndef render(value):\n    return normalize(value)\n'},
            'tests': 'from render import render\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_extract_and_compatibility(self):\n        from normalize import normalize\n        for value in (" hello ", "", " über "):\n            self.assertEqual(render(value), value.strip().upper())\n            self.assertEqual(render(value), normalize(value))\n',
        },
        'F': {
            'name': 'Deliberate regression mutation detected by actual tests',
            'objective': 'Double integers, including zero and negative values',
            'criteria': ['double returns twice its input for positive zero and negative integers'],
            'initial': {'maths.py': 'def double(value):\n    return value + 1\n'},
            'first': {'maths.py': 'def double(value):\n    return value - 1\n'},
            'desired': {'maths.py': 'def double(value):\n    return value * 2\n'},
            'tests': 'from maths import double\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_integer_edges(self):\n        for value in (1, 0, -2): self.assertEqual(double(value), value * 2)\n',
            'test_defect': True,
        },
        'G': {
            'name': 'Documentation and knowledge recovery through fresh controller',
            'objective': 'Document test and recovery procedures without losing the no-deployment rule',
            'criteria': ['README contains unittest command', 'README describes backup before recovery', 'No deployment rule remains present'],
            'convention': 'Project rule: no deployment is authorized; use a backup before recovery and run unittest acceptance.',
            'initial': {'README.md': '# Fixture project\n\nNo deployment is authorized.\n'},
            'desired': {'README.md': '# Fixture project\n\nNo deployment is authorized.\nRun python -m unittest discover for acceptance.\nCreate a backup before recovery.\n'},
            'tests': 'from pathlib import Path\nimport unittest\nclass Acceptance(unittest.TestCase):\n    def test_documented_procedures(self):\n        text = Path("README.md").read_text()\n        for item in ("No deployment", "python -m unittest discover", "backup before recovery"):\n            self.assertIn(item, text)\n',
            'pause': True,
        },
    }


class FileInspectingMockRegistry:
    """Deterministic protocol fixture, not independent model verification."""
    offline = True

    def __init__(self, scenario, pause_once=None):
        self.scenario = scenario
        self.calls = []
        self.reviews = []
        self.pause_once = pause_once

    def get(self, provider):
        if provider not in ('pilot_executor', 'pilot_reviewer'):
            raise ValueError('Only offline pilot fixture providers are available')
        class Adapter:
            def status(self):
                return {'available': True, 'model': 'deterministic-local-fixture',
                        'capabilities': {'scoped_tools': True}}
        return Adapter()

    def invoke(self, provider, request):
        self.get(provider)
        prompt = json.loads(request['prompt'])
        project = Path(request['project'])
        session = request.get('session_id') or str(uuid.uuid4())
        self.calls.append({'provider': provider, 'role': request['role'],
                           'session_id': session, 'resumed': bool(request.get('session_id'))})
        response = {'status': 'completed', 'output': '', 'session_id': session,
                    'usage': {}, 'history': request.get('history', [])}
        if request['role'] == 'planner':
            response['output']=json.dumps({'tasks':[{'title':self.scenario['objective'],'description':'Meet the stated acceptance criteria.'}]})
            return response
        if request['role'] == 'executor':
            corrected = bool(prompt.get('previous_review') or prompt.get('test_failures'))
            desired = self.scenario['desired'] if corrected else self.scenario.get('first', self.scenario['desired'])
            calls = []
            for name, content in desired.items():
                path = project / name
                old = path.read_text() if path.exists() else ''
                if old != content:
                    calls.append({'id': str(uuid.uuid4()), 'name': 'patch', 'arguments': {
                        'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else 'absent',
                        'old': old, 'new': content}})
            if calls:
                response.update(status='tool_calls', tool_calls=calls)
            else:
                response['output'] = 'Scoped changes are ready for engine acceptance and independent role review.'
                if self.pause_once:
                    action, self.pause_once = self.pause_once, None
                    action()
            return response
        if request['role'] != 'reviewer':
            raise ValueError('Pilot fixture uses the explicit single-task policy')
        inspected = {}
        for name, content in self.scenario['desired'].items():
            path = project / name
            inspected[name] = path.is_file() and path.read_text() == content
        tests = prompt.get('test_evidence', {})
        test_passed = tests.get('passed') is True and bool(tests.get('commands')) and all(
            command.get('exit_code') == 0 for command in tests['commands'])
        approved = all(inspected.values()) and test_passed
        self.reviews.append({'decision': 'approve' if approved else 'changes_requested',
                             'file_checks': inspected, 'engine_tests_passed': test_passed})
        response['output'] = json.dumps({'decision': self.reviews[-1]['decision'],
            'snapshot_hash': prompt['snapshot_hash'],
            'rationale': 'Deterministic reviewer inspected actual source files and engine command evidence.',
            'criteria': [{'criterion': item, 'met': approved,
                          'evidence': 'Actual desired file comparisons and engine acceptance command exit codes'}
                         for item in prompt['criteria']]})
        return response


def measure_deduplication(project):
    """Measure comparable function calls; startup/import time is excluded."""
    script = """import json, statistics, time
from dedupe import unique
from test_acceptance import Probe
values = list(range(512)) * 2
samples = []
for unused in range(7):
    start = time.perf_counter()
    result = unique(values)
    samples.append(time.perf_counter() - start)
    assert result == list(range(512))
Probe.work = 0
result = unique([Probe(v) for v in values])
assert [item.value for item in result] == list(range(512))
print(json.dumps({'sample_count': len(samples), 'median_seconds': statistics.median(samples),
                  'samples_seconds': samples, 'equality_and_hash_operations': Probe.work,
                  'input_values': len(values), 'unique_values': 512}))
"""
    result = subprocess.run([sys.executable, '-B', '-c', script], cwd=project,
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise AssertionError('Algorithm measurement failed')
    return json.loads(result.stdout)


def run_workload(key, live=False, execution_policy='single_task', context_mode='retrieved'):
    if live:
        raise PermissionError('Live providers are not supported by the isolated mock harness')
    scenario = scenarios()[key]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='ccx-phase4-source-') as source_dir, tempfile.TemporaryDirectory(prefix='ccx-phase4-runtime-') as runtime_dir:
        project = Path(source_dir) / 'project'
        subprocess.run(['git', 'init', '-q', str(project)], check=True, capture_output=True)
        for name, body in scenario['initial'].items():
            (project / name).write_text(body, encoding='utf-8')
        if scenario['tests']:
            (project / 'test_acceptance.py').write_text(scenario['tests'], encoding='utf-8')
        acceptance_command = [sys.executable, '-B', '-m', 'unittest', 'discover', '-p', 'test_acceptance.py']
        acceptance_timeout = 15
        browser_report = Path(runtime_dir) / 'browser-report.json'
        if scenario.get('browser'):
            acceptance_command = ['node', str(ROOT / 'tests/browser/test_workspace_cdp.cjs'),
                '--frontend-project=' + str(project), '--report=' + str(browser_report)]
            acceptance_timeout = 60
        baseline_correctness = None
        performance_before = None
        if scenario.get('performance'):
            correctness = subprocess.run([sys.executable, '-B', '-m', 'unittest', scenario['correctness_test']],
                cwd=project, capture_output=True, text=True, timeout=15)
            baseline_correctness = correctness.returncode
            if baseline_correctness:
                raise AssertionError('Performance fixture baseline must already be semantically correct')
            performance_before = measure_deduplication(project)
        initial_tests = subprocess.run(acceptance_command,
            cwd=project, capture_output=True, text=True, timeout=acceptance_timeout)
        if initial_tests.returncode == 0:
            raise AssertionError('Fixture must expose the original defect or missing requirement')
        store = Store(Path(runtime_dir) / 'private' / 'workspace.sqlite')
        project_id = store.register(project)['id']
        if scenario.get('convention'):
            store.add_memory(project_id, 'project', 'Project convention', scenario['convention'], kind='user_instruction')
        engine = WorkflowEngine(store)
        workflow = engine.create(project_id, scenario['objective'], scenario['criteria'],
            providers={'planner': 'pilot_executor', 'executor': 'pilot_executor', 'reviewer': 'pilot_reviewer'},
            budgets={'max_provider_calls': 16, 'max_retries': 2}, execution_policy=execution_policy, context_mode=context_mode)
        identifier = workflow['id']
        for provider in ('pilot_executor', 'pilot_reviewer'):
            engine.approve(identifier, 'sharing', {'provider': provider})
        engine.approve(identifier, 'operations', {'operations': ['patch']})
        engine.approve(identifier, 'command', {'name': 'acceptance',
            'argv': acceptance_command, 'timeout': acceptance_timeout})
        registry = FileInspectingMockRegistry(scenario, (lambda: engine.pause(identifier)) if scenario.get('pause') else None)
        result = engine.run(identifier, registry)
        resumed = False
        paused_sessions = []
        patch_count_before_restart = None
        if scenario.get('pause'):
            if result['status'] != 'PAUSED':
                raise AssertionError('Expected deliberate checkpoint pause: ' + result['status'])
            paused_sessions = result['sessions']
            with store.connect() as db:
                patch_count_before_restart = db.execute("SELECT COUNT(*) FROM w5_actions WHERE workflow_id=? AND role='tool:patch'", (identifier,)).fetchone()[0]
            store = Store(store.path)
            engine = WorkflowEngine(store)
            engine.resume(identifier)
            # A fresh adapter fixture has no in-memory conversation state.
            # Durable engine sessions/checkpoints supply continuation context.
            previous_calls, previous_reviews = registry.calls, registry.reviews
            registry = FileInspectingMockRegistry(scenario)
            result = engine.run(identifier, registry)
            registry.calls = previous_calls + registry.calls
            registry.reviews = previous_reviews + registry.reviews
            resumed = True
        if result['status'] != 'COMPLETED':
            raise AssertionError('Workload did not complete: ' + result['status'] + ': ' + str(result.get('reason')))
        for name, expected in scenario['desired'].items():
            if (project / name).read_text() != expected:
                raise AssertionError('Final source does not meet acceptance: ' + name)
        task = result['tasks'][0]
        if not engine.verify_task(identifier, task['id'])['verified']:
            raise AssertionError('Current engine evidence is not verified')
        final_tests = subprocess.run(acceptance_command,
            cwd=project, capture_output=True, text=True, timeout=acceptance_timeout)
        if final_tests.returncode:
            raise AssertionError('Independent final acceptance failed')
        with store.connect() as db:
            actions = [dict(row) for row in db.execute('SELECT role,state,response FROM w5_actions WHERE workflow_id=? ORDER BY started_at', (identifier,))]
            integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        test_outcomes = [json.loads(a['response']).get('exit_code') for a in actions if a['role'].startswith('test:')]
        patch_actions = [a for a in actions if a['role'] == 'tool:patch']
        if scenario.get('test_defect') and not any(code != 0 for code in test_outcomes):
            raise AssertionError('Controlled regression mutation was not detected by real tests')
        if scenario.get('review_defect') and not any(review['decision'] == 'changes_requested' and review['engine_tests_passed'] for review in registry.reviews):
            raise AssertionError('Reviewer did not detect the implementation defect missed by the limited acceptance test')
        performance_after = measure_deduplication(project) if scenario.get('performance') else None
        fresh = Store(store.path)
        memories = fresh.memories(project_id)
        verified = [m for m in memories if m['kind'] == 'verified' and m['source'] == 'workflow:' + identifier]
        if not verified:
            raise AssertionError('Verified project knowledge did not survive reopening')
        if scenario.get('convention') and not any(m['body'] == scenario['convention'] for m in memories):
            raise AssertionError('Project convention was lost')
        if resumed:
            if len(patch_actions) != patch_count_before_restart:
                raise AssertionError('Checkpoint continuation repeated scoped edits')
            if any(session not in result['sessions'] for session in paused_sessions):
                raise AssertionError('Checkpoint continuation lost provider session references')
        from ccx_workspace.benchmark import usage_report
        usage=usage_report(store,identifier)
        return {'workload': key, 'name': scenario['name'], 'status': result['status'],
            'evidence_class': 'MOCK_TESTED_WITH_REAL_LOCAL_EFFECTS','execution_policy':execution_policy,'context_mode':context_mode,
            'usage':usage,'workflow_verification_records':sum(m['scope']=='verification' for m in verified),
            'verified_solution_records':sum(m['scope']=='error' for m in verified), 'live_provider_calls': 0,
            'live_provider_status': 'BLOCKED_NO_AUTHORIZED_LIVE_RUN_IN_THIS_HARNESS',
            'workflow_id': identifier, 'session_ids': [s['session_id'] for s in result['sessions']],
            'provider_mock_calls': len(registry.calls), 'calls': registry.calls,
            'correction_rounds': task['attempts'], 'review_observations': registry.reviews,
            'acceptance_kind': 'actual_browser_cdp' if scenario.get('browser') else 'python_unittest_subprocess',
            'browser_acceptance': json.loads(browser_report.read_text()) if scenario.get('browser') else None,
            'baseline_correctness_exit_code': baseline_correctness,
            'performance_before': performance_before, 'performance_after': performance_after,
            'initial_acceptance_exit_code': initial_tests.returncode,
            'engine_acceptance_exit_codes': test_outcomes, 'final_acceptance_exit_code': final_tests.returncode,
            'scoped_patch_count': len(patch_actions), 'verified_memory_records': len(verified),
            'fresh_controller_continuation': resumed, 'patch_replay_count_after_restart': 0 if resumed else None,
            'database_integrity': integrity, 'fixture_approval_grants': len(engine.approvals(identifier)),
            'synthetic_operator_actions': 6 if resumed else 4,
            'operator_measurement': 'Harness-issued approval grants plus deliberate pause/resume; not measured human effort',
            'duration_seconds': round(time.monotonic() - started, 3),
            'final_source_hashes': {name: hashlib.sha256((project / name).read_bytes()).hexdigest() for name in scenario['desired']},
            'limitations': ['Deterministic providers and source-comparison reviewer, not live model quality',
                'No real tokens, cost savings, native session continuity or human superiority claimed',
                'All source/runtime data were generated and removed by the fixture']}


def run_all(keys=None):
    selected = keys if keys is not None else [key for key, scenario in scenarios().items() if not scenario.get('browser')]
    return {'schema': 1, 'date': '2026-11-25', 'live_provider_calls': 0,
            'workloads': [run_workload(key) for key in selected]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--workload', choices=sorted(scenarios()), action='append',
                        help='Select specific workload(s); B requires native Chrome/CDP process permissions')
    args = parser.parse_args()
    report = run_all(args.workload)
    rendered = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(rendered, encoding='utf-8')
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
