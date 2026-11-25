"""Reject recognizable credentials before workflow input reaches durable state."""
import sys
import unittest
import test_v5_workflows as fixtures


class WorkflowInputTests(unittest.TestCase):
    setUp = fixtures.WorkflowTests.setUp
    tearDown = fixtures.WorkflowTests.tearDown
    create = fixtures.WorkflowTests.create

    def assert_not_stored(self, marker):
        with self.store.connect() as db:
            self.assertFalse(any(marker in line for line in db.iterdump()),
                             'sensitive input reached durable state')

    def test_workflow_objective_rejected_before_persistence(self):
        marker = 'ghp_' + 'A' * 32
        with self.assertRaises(ValueError):
            self.engine.create(self.pid, 'Repair ' + marker, ['passes'])
        self.assert_not_stored(marker)
        self.assertEqual(self.engine.list(self.pid), [])

    def test_workflow_criterion_rejected_before_persistence(self):
        marker = 'github_pat_' + 'B' * 32
        with self.assertRaises(ValueError):
            self.engine.create(self.pid, 'Repair app', ['passes', marker])
        self.assert_not_stored(marker)
        self.assertEqual(self.engine.list(self.pid), [])

    def test_task_title_rejected_before_persistence(self):
        identifier = self.create(task=False)
        marker = 'ghp_' + 'C' * 32
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier, 'Repair ' + marker)
        self.assert_not_stored(marker)
        self.assertEqual(self.engine.status(identifier)['tasks'], [])

    def test_task_description_rejected_before_persistence(self):
        identifier = self.create(task=False)
        marker = 'ghp_' + 'D' * 32
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier, 'Repair', description=marker)
        self.assert_not_stored(marker)
        self.assertEqual(self.engine.status(identifier)['tasks'], [])

    def test_nontext_task_description_rejected(self):
        identifier = self.create(task=False)
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier, 'Repair', description={'instruction': 'ambiguous'})
        self.assertEqual(self.engine.status(identifier)['tasks'], [])

    def test_existing_advisory_input_boundaries_use_shared_detector(self):
        identifier = self.create()
        task = self.engine.status(identifier)['tasks'][0]['id']
        for marker in ('ghp_' + 'E' * 32, 'password=' + 'Z' * 16):
            with self.subTest(kind=marker[:3]):
                with self.assertRaises(ValueError):
                    self.engine.submit_review(identifier, task, marker)
                with self.assertRaises(ValueError):
                    self.engine.request_correction(identifier, task, marker)
                with self.assertRaises(ValueError):
                    self.engine.request_approval(identifier, 'sharing', {'provider': 'codex'}, marker)
                self.assert_not_stored(marker)

    def test_approval_scopes_reject_credentials_before_persistence(self):
        identifier = self.create()
        marker = 'ghp_' + 'F' * 32
        cases = (
            ('sharing', {'provider': 'codex', 'api_key': marker}),
            ('command', {'name': 'test', 'argv': [sys.executable, '-c', 'print(' + repr(marker) + ')']}),
            ('sharing', {'provider': 'codex', 'extra': {'api_key': 'Z' * 24}}),
            ('command', {'name': 'test', 'argv': [sys.executable, '-c', 'password="disposable-fixture"']}),
        )
        for kind, scope in cases:
            with self.subTest(kind=kind, fields=sorted(scope)):
                with self.assertRaises(ValueError):
                    self.engine.approve(identifier, kind, scope)
                self.assert_not_stored(marker)
                self.assert_not_stored('Z' * 24)
                self.assert_not_stored('disposable-fixture')
                self.assertEqual(self.engine.approvals(identifier), [])

    def test_approval_requests_reject_credentials_before_persistence(self):
        identifier = self.create()
        marker = 'ghp_' + 'G' * 32
        for kind, scope in (
            ('sharing', {'provider': 'codex', 'api_key': marker}),
            ('command', {'name': 'test', 'argv': [sys.executable, '-c', 'print(' + repr(marker) + ')']}),
            ('sharing', {'provider': 'codex', 'extra': {'api_key': 'Y' * 24}}),
        ):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    self.engine.request_approval(identifier, kind, scope, 'Please review scope')
                self.assert_not_stored(marker)
                self.assert_not_stored('Y' * 24)
                self.assertEqual(self.engine.status(identifier)['approval_requests'], [])
                self.assertEqual(self.engine.approvals(identifier), [])

    def test_benign_exact_command_permissions_are_preserved(self):
        identifier = self.create()
        # Benign command syntax remains exact; literal credentials are refused.
        argv = [sys.executable, '-c', 'policy="require-approval"; assert len(policy) > 8']
        self.engine.approve(identifier, 'command', {'name': 'fixture', 'argv': argv})
        self.assertEqual(self.engine.approvals(identifier)[0]['scope']['argv'], argv)


if __name__ == '__main__':
    unittest.main(verbosity=2)
