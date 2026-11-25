"""Phase2 recovery and context tests; all providers are deterministic mocks."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock
import test_v5_workflows as fixtures

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine/lib'))
from ccx_workspace.workflows import WorkflowEngine, classify_failure
from ccx_workspace.mcp import Bridge
from ccx_workspace.benchmark import usage_report, compare_workflows


class ReliabilityTests(unittest.TestCase):
    setUp=fixtures.WorkflowTests.setUp
    tearDown=fixtures.WorkflowTests.tearDown
    create=fixtures.WorkflowTests.create
    authorize=fixtures.WorkflowTests.authorize

    def test_malformed_plan_continues_bounded_and_reuses_session(self):
        identifier=self.create(task=False);self.authorize(identifier)
        registry=fixtures.MockRegistry();original=registry.invoke
        seen=[]
        def invoke(provider,request):
            result=original(provider,request);seen.append(request.get('session_id'))
            if len(seen)==1:result['output']='incomplete JSON'
            return result
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertIsNotNone(seen[1])
        self.assertEqual(result['provider_calls'],4)

    def test_no_progress_stops_incomplete_repetition(self):
        identifier=self.create(task=False);self.authorize(identifier)
        registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            result=original(provider,request);result.update(status='incomplete',output='same partial plan');return result
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'BLOCKED')
        self.assertEqual(result['provider_calls'],2)
        self.assertIn('no progress',result['reason'])

    def test_provider_call_cap_prevents_review_dispatch(self):
        identifier=self.create(budgets={'max_provider_calls':1});self.authorize(identifier)
        registry=fixtures.MockRegistry()
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'BUDGET_EXHAUSTED')
        self.assertEqual(len(registry.calls),1)

    def test_error_classification_does_not_retry_unknown_effects(self):
        self.assertEqual(classify_failure({'error':'HTTP status 429'}),'usage_limit')
        identifier=self.create();self.authorize(identifier)
        registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            result=original(provider,request);result.update(status='failed',error='network connection lost');return result
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'RECOVERY_REQUIRED')
        self.assertEqual(len(registry.calls),1)
        with self.assertRaises(PermissionError):self.engine.resume(identifier)

    def test_reviewer_handoff_preserves_executor_session_and_work(self):
        identifier=self.create();self.authorize(identifier,('codex','claude','minimax'))
        registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if provider=='claude' and request['role']=='reviewer':result.update(status='failed',error='weekly usage limit')
            return result
        registry.invoke=invoke
        blocked=self.engine.run(identifier,registry)
        executor=next(s for s in blocked['sessions'] if s['role']=='executor')
        with self.assertRaises(PermissionError):self.engine.transition_role(identifier,'reviewer','minimax')
        self.engine.approve(identifier,'failover',{'role':'reviewer','to_provider':'minimax'})
        self.engine.transition_role(identifier,'reviewer','minimax')
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertEqual(registry.executions,1)
        self.assertIn(executor,result['sessions'])

    def test_request_and_advisory_review_cannot_grant_or_verify(self):
        identifier=self.create();task=self.engine.status(identifier)['tasks'][0]
        bridge=Bridge(self.store,self.pid,engine=self.engine,registry=fixtures.MockRegistry())
        reply=bridge.call('request_approval',{'workflow_id':identifier,'kind':'sharing','scope':{'provider':'codex'},'reason':'Need executor access'})
        self.assertFalse(reply['grants_permission']);self.assertEqual(self.engine.approvals(identifier),[])
        bridge.call('submit_review',{'workflow_id':identifier,'task_id':task['id'],'review':'I declare this task approved'})
        self.assertFalse(bridge.call('verify_task',{'workflow_id':identifier,'task_id':task['id']})['verified'])
        self.assertEqual(self.engine.status(identifier)['tasks'][0]['status'],'PENDING')

    def test_dependency_is_project_bound_and_executes_in_order(self):
        identifier=self.create(task=False);other=self.create()
        first=self.engine.create_task(identifier,'First implementation')
        second=self.engine.create_task(identifier,'Second implementation',depends_on=[first['id']])
        with self.assertRaises(ValueError):
            self.engine.create_task(identifier,'Invalid',depends_on=[self.engine.status(other)['tasks'][0]['id']])
        self.authorize(identifier);registry=fixtures.MockRegistry()
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertEqual([call[2]['task']['title'] for call in registry.calls if call[1]=='executor'],['First implementation','Second implementation'])
        self.assertEqual(second['depends_on'],[first['id']])

    def test_automatic_index_and_root_instruction_context(self):
        (self.project/'AGENTS.md').write_text('Do not deploy. Follow the project style.')
        identifier=self.create();self.authorize(identifier);registry=fixtures.MockRegistry()
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertIn('Do not deploy',registry.calls[0][2]['context']['content'])
        self.assertTrue(self.store.search(self.pid,'Follow the project style'))
        self.assertEqual(self.store.index(self.pid)['bytes_read'],0)

    def test_workflow_overrides_and_single_task_policy_preserve_review(self):
        identifier=self.engine.create(self.pid,'Make correct',['app.txt contains good'],
                    model_overrides={'executor':'explicit-model'},execution_policy='single_task')['id']
        self.authorize(identifier);registry=fixtures.MockRegistry();original=registry.invoke;requests=[]
        def invoke(provider,request):requests.append(request);return original(provider,request)
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertEqual([r['role'] for r in requests],['executor','reviewer'])
        self.assertEqual(requests[0]['model'],'explicit-model')

    def test_visible_events_are_bounded_and_secret_redacted(self):
        identifier=self.create();self.authorize(identifier);registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            for i in range(100):request['event_callback']({'type':'text','text':'password=abcdefghijklmnop' if i==0 else 'progress'})
            request['event_callback']({'type':'history','history':[{'content':'internal'}]})
            return original(provider,request)
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        events=[e for e in self.engine.checkpoints(identifier) if e['event']=='PROVIDER_EVENT']
        self.assertEqual(len(events),128)
        self.assertNotIn('abcdefghijklmnop',json.dumps(events))
        self.assertNotIn('internal',json.dumps(events))

    def test_usage_report_includes_reviews_corrections_and_rejects_mock_savings(self):
        identifier=self.create();self.authorize(identifier)
        self.engine.run(identifier,fixtures.MockRegistry(reject_once=True))
        report=usage_report(self.store,identifier)
        self.assertEqual(report['provider_calls'],4)
        self.assertEqual(report['reported_totals']['input_tokens'],80)
        self.assertIsNone(report['reported_totals']['cached_tokens'])
        self.assertFalse(report['live_execution'])
        comparison=compare_workflows(self.store,identifier,identifier)
        self.assertFalse(comparison['optimization_verified'])
        self.assertIsNone(comparison['input_token_reduction'])

    def test_full_context_is_explicit_and_rejects_over_budget(self):
        self.store.index(self.pid)
        self.assertIn('good',self.store.full_context(self.pid)['content'])
        (self.project/'long.md').write_text('long document\n'*100)
        self.store.index(self.pid)
        with self.assertRaises(ValueError):self.store.full_context(self.pid,budget=64)

    def test_repeat_approval_reuses_existing_bounded_scope(self):
        identifier=self.create()
        first=self.engine.approve(identifier,'sharing',{'provider':'codex'})
        second=self.engine.approve(identifier,'sharing',{'provider':'codex'})
        self.assertEqual(first['id'],second['id'])
        self.assertEqual(len(self.engine.approvals(identifier)),1)

    def test_preapproved_role_fallback_is_bounded_and_never_resets_executor(self):
        identifier=self.create();self.authorize(identifier,('codex','claude','minimax'))
        self.engine.approve(identifier,'failover',{'role':'reviewer','to_provider':'minimax'})
        registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if provider=='claude':result.update(status='failed',error_kind='usage_limit',output='')
            return result
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertEqual(registry.executions,1)
        self.assertEqual(result['tasks'][0]['reviewer'],'minimax')
        self.assertTrue(any(e['event']=='AUTOMATIC_ROLE_HANDOFF' for e in self.engine.checkpoints(identifier)))

    def test_workflow_cannot_claim_or_resume_chat_session(self):
        identifier=self.create();self.authorize(identifier)
        import uuid
        session=str(uuid.uuid4())
        with self.store.connect() as db:
            db.execute('CREATE TABLE chats(id TEXT,provider TEXT,session_id TEXT)')
            db.execute('INSERT INTO chats VALUES(?,?,?)',('other','codex',session))
        registry=fixtures.MockRegistry();original=registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if provider=='codex':result['session_id']=session
            return result
        registry.invoke=invoke
        result=self.engine.run(identifier,registry)
        self.assertEqual(result['status'],'RECOVERY_REQUIRED')
        self.assertEqual(result['sessions'],[])

    def test_operator_resolves_requests_idempotently_without_model_grants(self):
        identifier=self.create();other=self.create()
        request=self.engine.request_approval(identifier,'sharing',{'provider':'codex'},'Use chosen executor')
        with self.assertRaises(PermissionError):self.engine.resolve_request(identifier,request['id'],actor='model')
        with self.assertRaises(KeyError):self.engine.resolve_request(other,request['id'])
        accepted=self.engine.resolve_request(identifier,request['id'])
        self.assertEqual(accepted['status'],'APPROVED')
        self.assertTrue(self.engine.resolve_request(identifier,request['id'])['reused'])
        self.assertEqual(len(self.engine.approvals(identifier)),1)
        second=self.engine.request_approval(identifier,'sharing',{'provider':'minimax'},'Optional executor')
        self.assertEqual(self.engine.resolve_request(identifier,second['id'],'deny')['status'],'DENIED')
        self.assertEqual(self.engine.status(identifier)['approval_requests'],[])
        with self.assertRaises(ValueError):self.engine.resolve_request(identifier,second['id'],'approve')
        invalid=self.engine.request_approval(identifier,'cost',{'provider':'minimax','max_cost':1},'Missing reservation')
        with self.assertRaises(ValueError):self.engine.resolve_request(identifier,invalid['id'])
        self.assertEqual(self.engine.status(identifier)['approval_requests'][0]['status'],'PENDING')

    @unittest.skipIf(os.name=='nt','Native Windows reparse setup needs separate environment')
    def test_snapshot_refuses_replaced_project_root(self):
        from ccx_workspace.workflows import snapshot
        original=self.project
        moved=self.base/'moved';original.rename(moved);original.symlink_to(moved,target_is_directory=True)
        try:
            with self.assertRaises(PermissionError):snapshot(original)
        finally:original.unlink();moved.rename(original)

    def _leased(self,identifier,pid=12345,birth=111,expiry=None,unknown=True):
        with self.store.connect() as db:
            db.execute("UPDATE w5_workflows SET status='RUNNING',lease_owner='fixture-owner',lease_pid=?,lease_start_ticks=?,lease_until=? WHERE id=?",
                       (pid,birth,time.time()+60 if expiry is None else expiry,identifier))
            if unknown:
                db.execute("INSERT INTO w5_actions(id,workflow_id,role,provider,state,request,before_hash,started_at) VALUES(?,?,'executor','codex','RUNNING','{}','snapshot',?)",
                           ('fixture-'+identifier,identifier,time.time()))

    def test_dead_or_reused_owner_reconciles_immediately_without_dispatch(self):
        for returned in (None,{'state':'Z','start_ticks':111},{'state':'R','start_ticks':222}):
            identifier=self.create();self._leased(identifier)
            registry=fixtures.MockRegistry()
            with mock.patch('ccx_workspace.workflows.native.process_info',return_value=returned):
                result=self.engine.run(identifier,registry)
            self.assertEqual(result['status'],'RECOVERY_REQUIRED')
            self.assertIsNone(result['lease_until'])
            self.assertEqual(result['pending_actions'][0]['state'],'UNCERTAIN')
            self.assertEqual(registry.calls,[])

    def test_live_owner_survives_expired_heartbeat_and_dashboard_reconcile(self):
        identifier=self.create();self._leased(identifier,expiry=time.time()-60)
        with mock.patch('ccx_workspace.workflows.native.process_info',return_value={'state':'R','start_ticks':111}):
            self.assertEqual(self.engine.reconcile_ownership()['reconciled'],[])
            registry=fixtures.MockRegistry();result=self.engine.run(identifier,registry)
        self.assertTrue(result['busy'])
        self.assertEqual(result['status'],'RUNNING')
        self.assertEqual(result['health'],'heartbeat_late')
        self.assertEqual(registry.calls,[])
        with self.assertRaises(ValueError):self.engine.create_task(identifier,'Do not modify live plan')

    def test_unknown_process_identity_waits_for_ttl_then_pauses_without_replay(self):
        identifier=self.create();self._leased(identifier,unknown=False)
        with mock.patch('ccx_workspace.workflows.native.process_info',side_effect=PermissionError('Cannot inspect')):
            self.assertEqual(self.engine.reconcile_ownership()['reconciled'],[])
            with self.store.connect() as db:
                db.execute('UPDATE w5_workflows SET lease_until=? WHERE id=?',(time.time()-1,identifier))
            report=self.engine.reconcile_ownership()
        self.assertEqual(report['reconciled'][0]['status'],'PAUSED')
        self.assertEqual(self.engine.status(identifier)['status'],'PAUSED')

    def test_other_workflow_unknown_outcome_keeps_project_blocked(self):
        old=self.create();self._leased(old)
        new=self.create();self.authorize(new);registry=fixtures.MockRegistry()
        with mock.patch('ccx_workspace.workflows.native.process_info',return_value=None):
            result=self.engine.run(new,registry)
        self.assertTrue(result['busy'])
        self.assertEqual(self.engine.status(old)['status'],'RECOVERY_REQUIRED')
        self.assertEqual(registry.calls,[])
        # Explicitly abandoning a dead owner's workflow must not make the
        # project permanently unusable; cancelled work itself cannot resume.
        self.engine.cancel(old)
        self.assertEqual(self.engine.run(new,registry)['status'],'COMPLETED')
        self.assertEqual(self.engine.status(old)['status'],'CANCELLED')
        with self.assertRaises(ValueError):self.engine.resume(old)


if __name__=='__main__':unittest.main(verbosity=2)
