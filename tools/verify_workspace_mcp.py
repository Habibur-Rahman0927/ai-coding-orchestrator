#!/usr/bin/env python3
"""No-cost MCP transport check and optional native Codex config resolution."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine/lib'))
from ccx_workspace.store import Store


def main():
    with tempfile.TemporaryDirectory(prefix='ccx-mcp-check-') as temporary:
        base=Path(temporary).resolve();project=base/'project'
        subprocess.run(['git','init','-q',str(project)],check=True,capture_output=True)
        store=Store(base/'private/workspace.sqlite3');pid=store.register(project)['id']
        store.add_memory(pid,'project','Approved decision','Use a bounded queue')
        arguments=['-B',str(ROOT/'engine/orchestrator.py'),'workspace','--database',str(store.path),'mcp','--project',pid]
        requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'local-check','version':'1'}}},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'search_project_memory','arguments':{'query':'bounded'}}}]
        result=subprocess.run([sys.executable]+arguments,input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,timeout=15)
        assert result.returncode==0,'MCP transport failed'
        replies=[json.loads(line) for line in result.stdout.splitlines()]
        assert len(replies)==3 and 'result' in replies[0]
        names=[t['name'] for t in replies[1]['result']['tools']]
        assert 'delegate_task' in names and not any(n in names for n in ('approve','approve_workflow'))
        assert 'bounded queue' in replies[2]['result']['content'][0]['text']
        report={'stdio_initialize':True,'tool_discovery':True,'project_memory_retrieval':True,
                'tool_count':len(names),'human_approval_tool_exposed':False,
                'native_codex_config_resolution':None,'native_agent_invocation':False,
                'provider_calls':0,'global_configuration_modified':False}
        codex=shutil.which('codex')
        if codex:
            command=[codex,'-c','mcp_servers.ccx_phase2_check.command='+json.dumps(sys.executable),
                     '-c','mcp_servers.ccx_phase2_check.args='+json.dumps(arguments),
                     'mcp','get','ccx_phase2_check','--json']
            check=subprocess.run(command,capture_output=True,text=True,timeout=15)
            if check.returncode==0:
                configuration=json.loads(check.stdout)
                report['native_codex_config_resolution']=configuration.get('name')=='ccx_phase2_check'
            else:report['native_codex_config_resolution']=False
        print(json.dumps(report,indent=2))


if __name__=='__main__':main()
