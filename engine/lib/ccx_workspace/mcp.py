"""Project-bound MCP stdio tool server. Human approval is intentionally absent.

Protocol: https://modelcontextprotocol.io/specification/2025-11-25/server/tools
No sockets, cloud registration, provider credentials or automatic live calls.
"""
import json
import sys

SCHEMAS={
 'discover_providers':{},
 'get_project_context':{'query':'string','budget':'integer'},
 'search_project_memory':{'query':'string'},
 'get_workflow_status':{'workflow_id':'string'},
 'create_workflow':{'objective':'string','criteria':'array'},
 'create_task':{'workflow_id':'string','title':'string'},
 'delegate_task':{'workflow_id':'string','task_id':'string','to_provider':'string'},
 'pause_workflow':{'workflow_id':'string'},
 'resume_workflow':{'workflow_id':'string'},
 'run_workflow':{'workflow_id':'string'},
}

class Bridge:
    def __init__(self,store,project_id,engine=None,registry=None):
        store.project(project_id)
        self.store,self.project_id=store,project_id
        if engine is None:
            from .workflows import WorkflowEngine
            engine=WorkflowEngine(store)
        if registry is None:
            from .settings import registry_for
            registry=registry_for(store)
        self.engine,self.registry=engine,registry
        self.initialized=False

    def call(self,name,args):
        if not isinstance(name,str) or name not in SCHEMAS: raise ValueError('Unknown or unauthorized tool')
        spec=SCHEMAS[name]
        if not isinstance(args,dict) or set(args)-set(spec): raise ValueError('Unexpected arguments')
        for key,kind in spec.items():
            if key not in args:
                if key=='budget':continue
                raise ValueError('Missing required argument')
            value=args[key]
            if (kind=='string' and not isinstance(value,str)) or (kind=='integer' and type(value)!=int) or (kind=='array' and (not isinstance(value,list) or not all(isinstance(x,str) for x in value))):
                raise ValueError('Incorrect argument type')
        if 'workflow_id' in args:
            state=self.engine.status(args['workflow_id'])
            if state.get('project_id')!=self.project_id:raise PermissionError('Workflow outside selected project')
        if name=='discover_providers':return self.registry.discover()
        if name=='get_project_context':return self.store.context(self.project_id,args['query'],args.get('budget',2000))
        if name=='search_project_memory':return self.store.search(self.project_id,args['query'])
        if name=='create_workflow':return self.engine.create(self.project_id,args['objective'],args['criteria'])
        if name=='create_task':return self.engine.create_task(args['workflow_id'],args['title'])
        if name=='delegate_task':
            if not any(task.get('id')==args['task_id'] for task in state.get('tasks',[])):
                raise PermissionError('Task outside selected workflow')
            return self.engine.delegate(args['task_id'],args['to_provider'])
        if name=='get_workflow_status':return state
        if name=='pause_workflow':return self.engine.pause(args['workflow_id'])
        if name=='resume_workflow':return self.engine.resume(args['workflow_id'])
        if name=='run_workflow':return self.engine.run(args['workflow_id'],self.registry)
        raise ValueError('Unsupported tool')

    def message(self,request):
        mid=request.get('id')
        if mid is None:return None
        response={'jsonrpc':'2.0','id':mid}
        try:
            method=request.get('method')
            if request.get('jsonrpc')!='2.0':raise ValueError('Invalid JSON-RPC version')
            params=request.get('params',{})
            if not isinstance(params,dict):raise ValueError('Request params must be an object')
            if method=='initialize':
                self.initialized=True
                result={'protocolVersion':'2025-11-25','capabilities':{'tools':{'listChanged':False}},'serverInfo':{'name':'ccx-workspace','version':'5.0.0-dev'}}
            elif not self.initialized:raise ValueError('Initialize first')
            elif method=='ping':result={}
            elif method=='tools/list':
                result={'tools':[{'name':name,'description':name.replace('_',' ')+' within the explicitly selected project',
                                  'inputSchema':{'type':'object','properties':{k:({'type':v,'items':{'type':'string'}} if v=='array' else {'type':v}) for k,v in schema.items()},'required':[k for k in schema if k!='budget'],'additionalProperties':False}}
                                  for name,schema in SCHEMAS.items()]}
            elif method=='tools/call':
                try:
                    value=self.call(params.get('name'),params.get('arguments',{}))
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=True)}],'isError':False}
                except (ValueError,KeyError,PermissionError,RuntimeError) as error:
                    result={'content':[{'type':'text','text':'Operation refused: '+str(error)}],'isError':True}
            else:raise ValueError('Unsupported method')
            response['result']=result
        except (ValueError,TypeError,KeyError):response['error']={'code':-32602,'message':'Invalid or unsupported request'}
        return response

def serve(store,project_id):
    bridge=Bridge(store,project_id)
    while True:
        line=sys.stdin.readline(1048577)
        if not line:break
        if len(line)>1048576:raise ValueError('MCP request exceeds size limit')
        try:
            request=json.loads(line)
            if not isinstance(request,dict):raise ValueError()
            response=bridge.message(request)
        except ValueError:response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Invalid JSON'}}
        if response is not None:print(json.dumps(response,ensure_ascii=True),flush=True)
