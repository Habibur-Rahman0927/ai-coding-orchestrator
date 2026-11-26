"""Agent-selected commands remain tied to a task grant and real execution evidence."""
import json
import sys
import time
import unittest
import test_v5_easy_tasks as fixtures

class AgentCommands(unittest.TestCase):
    setUp=fixtures.EasyTasks.setUp
    tearDown=fixtures.EasyTasks.tearDown
    file=fixtures.EasyTasks.file
    wait=fixtures.EasyTasks.wait
    start_body=fixtures.EasyTasks.start_body

    def proposal(self):
        data=dict(self.data)
        for key in ('commands','max_cost','max_call_cost'):data.pop(key)
        return self.app.tasks.preview(data)

    def test_default_selects_and_executes_checks_without_manual_fields(self):
        proposal=self.proposal()
        self.assertEqual(proposal['blockers'],[])
        self.assertIn({'kind':'agent_commands','scope':{'mode':'project'}},proposal['approvals'])
        result=self.wait(self.app.tasks.start(self.start_body(proposal))['workflow_id'])
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        tests=result['tasks'][0]['evidence']['tests']
        self.assertEqual(tests['commands'][0]['exit_code'],0)
        self.assertEqual(tests['verification_mode'],'commands')

    def test_documentation_only_records_review_only_not_test_pass_claim(self):
        self.registry.tool=False
        self.file('app.txt','good')
        original=self.registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if request['role']=='executor' and result['status']=='completed':
                result['output']=json.dumps({'verification':{'commands':[],'reason':'Only progress documentation changed; inspect the file'}})
            return result
        self.registry.invoke=invoke
        result=self.wait(self.app.tasks.start(self.start_body(self.proposal()))['workflow_id'])
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        evidence=result['tasks'][0]['evidence']
        self.assertEqual(evidence['tests']['verification_mode'],'review_only')
        self.assertEqual(evidence['tests']['commands'],[])
        self.assertEqual(evidence['review']['decision'],'approve')

    def test_missing_verification_never_counts_as_completed(self):
        original=self.registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if request['role']=='executor' and result['status']=='completed':result['output']='Everything works!'
            return result
        self.registry.invoke=invoke
        result=self.wait(self.app.tasks.start(self.start_body(self.proposal()))['workflow_id'])
        self.assertEqual(result['status'],'BLOCKED')
        self.assertFalse(any(t['status']=='VERIFIED' for t in result['tasks']))

    def test_command_output_is_persisted_before_process_finishes(self):
        original=self.registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if request['role']=='executor' and result['status']=='completed':
                result['output']=json.dumps({'verification':{'commands':[{'name':'slow-check','argv':[sys.executable,'-u','-c','import time; print("CHECK STARTED",flush=True); time.sleep(2)'],'cwd':'.','timeout':10}],'reason':'Observed check'}})
            return result
        self.registry.invoke=invoke
        identifier=self.app.tasks.start(self.start_body(self.proposal()))['workflow_id']
        deadline=time.monotonic()+10;observed=False
        while time.monotonic()<deadline:
            events=self.app.engine.checkpoints(identifier)
            if any(e['event']=='COMMAND_OUTPUT' and e['data'].get('phase')=='running' and 'CHECK STARTED' in e['data'].get('text','') for e in events):
                observed=True;break
            time.sleep(.03)
        self.assertTrue(observed,'Output must arrive before the command finishes')
        self.assertIn(identifier,self.app.jobs)
        self.assertEqual(self.wait(identifier)['status'],'COMPLETED')

    def test_agent_can_choose_implementation_command_without_exact_command_approval(self):
        original=self.registry.invoke
        def invoke(provider,request):
            result=original(provider,request)
            if request['role']=='executor' and self.registry.executions==2:
                result.update(status='tool_calls',tool_calls=[{'id':'chosen-command','name':'run_command',
                    'arguments':{'name':'inspect','argv':[sys.executable,'-c','print("AGENT CHOSE THIS")'],'cwd':'.','timeout':10}}])
            return result
        self.registry.invoke=invoke
        result=self.wait(self.app.tasks.start(self.start_body(self.proposal()))['workflow_id'])
        self.assertEqual(result['status'],'COMPLETED',result['reason'])
        self.assertEqual(self.app.engine._approved(result['id'],'command'),[])
        events=self.app.engine.checkpoints(result['id'])
        self.assertTrue(any(e['event']=='COMMAND_OUTPUT' and 'AGENT CHOSE THIS' in e['data'].get('text','') for e in events))
