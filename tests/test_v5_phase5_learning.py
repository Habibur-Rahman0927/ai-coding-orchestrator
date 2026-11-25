"""Engine-verified error resolution learning, never automatic historical fix execution."""
import json
import unittest
import test_v5_workflows as fixtures

class VerifiedLearningTests(unittest.TestCase):
    setUp=fixtures.WorkflowTests.setUp
    tearDown=fixtures.WorkflowTests.tearDown
    create=fixtures.WorkflowTests.create
    authorize=fixtures.WorkflowTests.authorize
    def test_completed_correction_supersedes_observation_with_bound_evidence(self):
        identifier=self.create();self.authorize(identifier)
        result=self.engine.run(identifier,fixtures.MockRegistry(reject_once=True))
        self.assertEqual(result['status'],'COMPLETED')
        errors=[r for r in self.store.memories(self.pid) if r['scope']=='error']
        self.assertEqual(len(errors),1);record=errors[0]
        self.assertEqual(record['kind'],'verified');self.assertIsNotNone(record['supersedes'])
        payload=json.loads(record['body']);self.assertTrue(payload['resolved']);self.assertIn('verification_memory_id',payload)
        with self.store.connect() as db:
            original=db.execute('SELECT * FROM memory WHERE id=?',(record['supersedes'],)).fetchone()
            self.assertEqual(original['kind'],'observed');self.assertFalse(json.loads(original['body'])['resolved'])
        self.assertFalse(self.store._source_stale(self.pid,record['source'],record['source_hash']))
        (self.project/'app.txt').write_text('changed after verification')
        self.assertTrue(self.store._source_stale(self.pid,record['source'],record['source_hash']))
    def test_unfinished_correction_never_learns_verified_solution(self):
        identifier=self.create(budgets={'max_retries':0});self.authorize(identifier)
        result=self.engine.run(identifier,fixtures.MockRegistry(reject_once=True))
        self.assertEqual(result['status'],'BLOCKED')
        errors=[r for r in self.store.memories(self.pid) if r['scope']=='error']
        self.assertTrue(errors);self.assertTrue(all(r['kind']=='observed' for r in errors))
        self.assertTrue(all(not json.loads(r['body'])['resolved'] for r in errors))

if __name__=='__main__':unittest.main()
