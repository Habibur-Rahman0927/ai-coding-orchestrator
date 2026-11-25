"""Representative generated dogfood workloads; no real provider integrations."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pilot_workloads', ROOT / 'tools/pilot_workloads.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class PilotWorkloads(unittest.TestCase):
    def check_workload(self, key):
        result = pilot.run_workload(key)
        self.assertEqual(result['status'], 'COMPLETED')
        self.assertNotEqual(result['initial_acceptance_exit_code'], 0)
        self.assertEqual(result['final_acceptance_exit_code'], 0)
        self.assertEqual(result['live_provider_calls'], 0)
        self.assertGreater(result['scoped_patch_count'], 0)
        self.assertEqual(result['workflow_verification_records'], 1)
        self.assertEqual(result['verified_memory_records'], 1 + result['verified_solution_records'])
        if result['correction_rounds']:
            self.assertGreater(result['verified_solution_records'], 0)
        self.assertEqual(result['database_integrity'], 'ok')
        return result

    def test_backend_bug_reviewer_detects_actual_defect_and_corrects(self):
        result = self.check_workload('A')
        self.assertEqual(result['correction_rounds'], 1)
        self.assertEqual([r['decision'] for r in result['review_observations']], ['changes_requested', 'approve'])
        self.assertTrue(result['review_observations'][0]['engine_tests_passed'])
        self.assertFalse(all(result['review_observations'][0]['file_checks'].values()))

    def test_local_api_failure_and_legacy_inputs(self):
        result = self.check_workload('C')
        self.assertEqual(result['correction_rounds'], 0)

    def test_performance_work_budget_improves_without_semantic_regression(self):
        result = self.check_workload('D')
        self.assertEqual(result['baseline_correctness_exit_code'], 0)
        self.assertGreater(result['performance_before']['equality_and_hash_operations'], 8192)
        self.assertLessEqual(result['performance_after']['equality_and_hash_operations'], 8192)
        for measurement in (result['performance_before'], result['performance_after']):
            self.assertEqual(measurement['sample_count'], 7)
            self.assertEqual(len(measurement['samples_seconds']), 7)
            self.assertGreaterEqual(measurement['median_seconds'], 0)

    def test_multifile_refactor_keeps_actual_acceptance(self):
        result = self.check_workload('E')
        self.assertEqual(result['scoped_patch_count'], 2)
        self.assertEqual(len(result['final_source_hashes']), 2)

    def test_regression_mutation_really_fails_then_corrects(self):
        result = self.check_workload('F')
        self.assertEqual(result['correction_rounds'], 1)
        self.assertNotEqual(result['engine_acceptance_exit_codes'][0], 0)
        self.assertEqual(result['engine_acceptance_exit_codes'][-1], 0)

    def test_documentation_knowledge_survives_fresh_controller(self):
        result = self.check_workload('G')
        self.assertTrue(result['fresh_controller_continuation'])
        self.assertEqual(result['patch_replay_count_after_restart'], 0)
        self.assertEqual(result['synthetic_operator_actions'], 6)

    def test_harness_refuses_live_execution(self):
        with self.assertRaises(PermissionError):
            pilot.run_workload('A', live=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
