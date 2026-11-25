"""Independent comparability regressions; all usage records/providers are synthetic."""
import copy
import json
import unittest
from unittest import mock
import test_v5_workflows as fixtures
from ccx_workspace.benchmark import compare_workflows


class ComparisonContractTests(unittest.TestCase):
    def reports(self):
        baseline = {
            'objective': 'Same task', 'criteria': ['Same criterion'],
            'providers': dict.fromkeys(('planner', 'executor', 'reviewer'), 'minimax'),
            'live_execution': True, 'verification_success': True, 'context_mode': 'full_index',
            'reported_totals': {'input_tokens': 100, 'output_tokens': 50, 'cached_tokens': 90},
            'calls': [
                {'provider': 'minimax', 'role': 'executor', 'model': 'modelA',
                 'initial_snapshot': 'same-source', 'execution_contract_hash': 'same-contract'},
                {'provider': 'minimax', 'role': 'reviewer', 'model': 'modelB',
                 'initial_snapshot': 'same-source', 'execution_contract_hash': 'same-contract'},
            ],
        }
        optimized = copy.deepcopy(baseline)
        optimized.update(context_mode='retrieved', reported_totals={
            'input_tokens': 90, 'output_tokens': 40, 'cached_tokens': 0})
        return baseline, optimized

    def compare(self, baseline, optimized):
        # Deliberate synthetic return values exercise the comparison predicate;
        # these records are not stored or reported as live measurement evidence.
        with mock.patch('ccx_workspace.benchmark.usage_report', side_effect=[baseline, optimized]):
            return compare_workflows(None, 'baseline-fixture', 'optimized-fixture')

    def test_swapped_role_models_cannot_verify_optimization(self):
        baseline, optimized = self.reports()
        optimized['calls'][0]['model'] = 'modelB'
        optimized['calls'][1]['model'] = 'modelA'
        result = self.compare(baseline, optimized)
        self.assertFalse(result['comparable'])
        self.assertFalse(result['optimization_verified'])
        self.assertIsNone(result['total_token_reduction'])
        self.assertIn('Provider/model selections differ', result['limitations'])

    def test_equivalent_contract_does_not_subtract_cached_tokens(self):
        result = self.compare(*self.reports())
        self.assertTrue(result['comparable'])
        self.assertEqual(result['input_token_reduction'], 10)
        self.assertEqual(result['total_token_reduction'], 20)
        self.assertFalse(result['cached_tokens_treated_as_eliminated'])

    def test_missing_or_different_dispatch_contract_withholds_reduction(self):
        for changed in (None, 'different-actual-output-cap'):
            with self.subTest(contract=changed):
                baseline, optimized = self.reports()
                for call in optimized['calls']:
                    call['execution_contract_hash'] = changed
                result = self.compare(baseline, optimized)
                self.assertFalse(result['comparable'])
                self.assertIsNone(result['input_token_reduction'])
                self.assertFalse(result['optimization_verified'])


class DispatchedBudgetContractTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    authorize = fixtures.WorkflowTests.authorize

    def test_contract_hash_binds_actual_output_cap_after_budget_clipping(self):
        (self.project / 'unrelated.md').write_text('unrelated background ' + 'noise ' * 300)
        requests = []
        for mode in ('full_index', 'retrieved'):
            identifier = self.engine.create(self.pid, 'Correct app.txt', ['app.txt contains good'],
                context_mode=mode, budgets={'max_tokens': 2000, 'max_output_tokens': 1500,
                                           'max_context_tokens': 2000})['id']
            self.engine.create_task(identifier, 'Correct app.txt')
            self.authorize(identifier)
            result = self.engine.run(identifier, fixtures.MockRegistry())
            self.assertEqual(result['status'], 'COMPLETED', result['reason'])
            with self.store.connect() as db:
                row = db.execute("SELECT request FROM w5_actions WHERE workflow_id=? AND role='executor'", (identifier,)).fetchone()
            requests.append(json.loads(row[0]))
        baseline, optimized = requests
        self.assertLess(baseline['max_output_tokens'], optimized['max_output_tokens'])
        self.assertEqual(optimized['max_output_tokens'], 1500)
        self.assertNotEqual(baseline['execution_contract_hash'], optimized['execution_contract_hash'])
        for request in requests:
            self.assertEqual(request['context_accounting']['output_reserved_tokens'], request['max_output_tokens'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
