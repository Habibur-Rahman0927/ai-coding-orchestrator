"""Usage fidelity and dispatch envelope checks without live providers."""
import json
import unittest
import test_v5_workflows as fixtures
from ccx_workspace.providers import normalized_usage, normalize_cli
from ccx_workspace.benchmark import usage_report, compare_workflows

class UsageFidelityTests(unittest.TestCase):
    def test_nested_responses_cache_and_reasoning_are_preserved(self):
        value=normalized_usage({'input_tokens':100,'output_tokens':20,'input_tokens_details':{'cached_tokens':70},'output_tokens_details':{'reasoning_tokens':5}})
        self.assertEqual(value['cached_input_tokens'],70);self.assertEqual(value['reasoning_tokens'],5)
        self.assertEqual(value['input_tokens'],100)
    def test_claude_uncached_input_is_not_total_input(self):
        events=normalize_cli('claude',{'type':'result','subtype':'success','usage':{'input_tokens':10,'cache_read_input_tokens':90,'cache_creation_input_tokens':20,'output_tokens':5}})
        usage=next(e['usage'] for e in events if e['type']=='usage')
        self.assertEqual(usage['input_tokens'],120);self.assertEqual(usage['uncached_input_tokens'],10)
        self.assertEqual(usage['cached_input_tokens'],90)
    def test_nonfinite_usage_not_reported(self):
        self.assertNotIn('input_tokens',normalized_usage({'input_tokens':float('inf')}))

class WorkflowUsageTests(unittest.TestCase):
    setUp=fixtures.WorkflowTests.setUp
    tearDown=fixtures.WorkflowTests.tearDown
    create=fixtures.WorkflowTests.create
    authorize=fixtures.WorkflowTests.authorize
    def test_partial_usage_accounts_missing_input_estimate(self):
        identifier=self.create();self.authorize(identifier);reg=fixtures.MockRegistry();original=reg.invoke
        def invoke(provider,request):
            result=original(provider,request);result['usage']={'output_tokens':1};return result
        reg.invoke=invoke;result=self.engine.run(identifier,reg)
        self.assertEqual(result['status'],'COMPLETED');self.assertGreater(result['tokens_used'],2)
        report=usage_report(self.store,identifier);self.assertIsNone(report['reported_totals']['input_tokens'])
        self.assertEqual(report['reported_totals']['output_tokens'],2)
        self.assertEqual(report['role_totals']['executor']['provider_calls'],1)
        self.assertTrue(all(c['usage_accounting']=='mixed_reported_and_estimated' for c in report['calls']))
    def test_request_envelope_blocks_large_transcript_before_provider_call(self):
        identifier=self.create(budgets={'max_request_tokens':512});self.authorize(identifier)
        with self.store.connect() as db:
            db.execute('INSERT INTO w5_sessions(workflow_id,task_id,provider,role,session_id,history) VALUES(?,?,?,?,?,?)',(identifier,self.engine.status(identifier)['tasks'][0]['id'],'codex','executor',None,json.dumps([{'role':'user','content':'long '*1000}])))
        reg=fixtures.MockRegistry();result=self.engine.run(identifier,reg)
        self.assertEqual(result['status'],'BUDGET_EXHAUSTED');self.assertEqual(reg.calls,[])
        self.assertIn('request',result['reason'].lower())
    def test_zero_reported_usage_remains_reported_not_missing(self):
        identifier=self.create();self.authorize(identifier);reg=fixtures.MockRegistry();original=reg.invoke
        def invoke(provider,request):
            result=original(provider,request);result['usage']={'input_tokens':0,'output_tokens':0};return result
        reg.invoke=invoke;self.engine.run(identifier,reg)
        report=usage_report(self.store,identifier);self.assertEqual(report['reported_totals']['input_tokens'],0)
        self.assertTrue(all(c['usage_accounting']=='reported' for c in report['calls']))

if __name__=='__main__':unittest.main()
