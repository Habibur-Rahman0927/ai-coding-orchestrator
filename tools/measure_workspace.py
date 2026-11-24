#!/usr/bin/env python3
"""Small reproducible local measurements. Provider work is explicitly mocked."""
import http.client
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
try:import resource
except ImportError:resource=None
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine/lib'))
sys.path.insert(0,str(ROOT/'tests'))
from ccx_workspace.store import Store
from ccx_workspace.server import create_server
from ccx_workspace.workflows import WorkflowEngine
from test_v5_workflows import MockRegistry


def peak_bytes():
    if resource is None:return None
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value if sys.platform=='darwin' else value*1024


def measured(action):
    start=time.perf_counter();result=action()
    return result,round((time.perf_counter()-start)*1000,3)


def main():
    with tempfile.TemporaryDirectory(prefix='ccx-resource-check-') as temporary:
        base=Path(temporary).resolve();project=base/'project'
        subprocess.run(['git','init','-q',str(project)],check=True,capture_output=True)
        (project/'app.txt').write_text('good')
        for i in range(100):(project/('module%d.py'%i)).write_text('def symbol_%d():\n    return %d\n'%(i,i))
        start=time.perf_counter()
        store=Store(base/'private/workspace.sqlite3');engine=WorkflowEngine(store)
        server=create_server(store,registry=MockRegistry(),engine=engine)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        startup=round((time.perf_counter()-start)*1000,3)
        try:
            pid=store.register(project)['id']
            first,first_ms=measured(lambda:store.index(pid))
            second,second_ms=measured(lambda:store.index(pid))
            latencies=[]
            for i in range(20):_,elapsed=measured(lambda:store.context(pid,'symbol_42',budget=300));latencies.append(elapsed)
            before=store.path.stat().st_size
            cpu=time.process_time();wall=time.monotonic();time.sleep(1)
            idle_percent=100*(time.process_time()-cpu)/(time.monotonic()-wall)
            http_times=[]
            for unused in range(20):
                connection=http.client.HTTPConnection('127.0.0.1',server.server_address[1],timeout=3)
                mark=time.perf_counter();connection.request('GET','/');response=connection.getresponse();response.read()
                assert response.status==200
                http_times.append((time.perf_counter()-mark)*1000);connection.close()
            flow=engine.create(pid,'Verify the existing small fixture',['app.txt contains good'],providers={'planner':'codex','executor':'codex','reviewer':'claude'})
            for provider in ('codex','claude'):engine.approve(flow['id'],'sharing',{'provider':provider})
            engine.approve(flow['id'],'command',{'name':'test','argv':[sys.executable,'-c','from pathlib import Path; assert Path("app.txt").read_text()=="good"']})
            registry=MockRegistry(reject_once=True)
            cpu=time.process_time();result,active_ms=measured(lambda:engine.run(flow['id'],registry));active_cpu=time.process_time()-cpu
            events,event_ms=measured(lambda:engine.checkpoints(flow['id']))
            report={'platform':{'os':platform.system(),'architecture':platform.machine(),'python':platform.python_version()},
                    'fixture':{'source_files':101,'mock_providers':True,'live_provider_calls':0},
                    'startup_to_bound_backend_ms':startup,'idle_sample_seconds':1,'idle_process_cpu_percent':round(idle_percent,3),
                    'process_peak_rss_bytes':peak_bytes(),'memory_measurement':'peak for entire measurement process, not isolated steady-state RSS',
                    'initial_index_ms':first_ms,'repeat_index_ms':second_ms,'repeat_index_bytes_read':second['bytes_read'],
                    'context_latency_median_ms':round(statistics.median(latencies),3),
                    'static_http_median_ms':round(statistics.median(http_times),3),
                    'mock_workflow_duration_ms':active_ms,'mock_workflow_process_cpu_seconds':round(active_cpu,4),
                    'workflow_status':result['status'],'correction_rounds':sum(t['attempts'] for t in result['tasks']),
                    'checkpoint_count':len(events),'checkpoint_read_ms':event_ms,
                    'database_growth_during_workflow_bytes':store.path.stat().st_size-before,
                    'limitations':['single short local sample','CPU excludes test child processes and providers','no before/after optimization claim','browser responsiveness covered separately by interaction tests']}
            assert result['status']=='COMPLETED'
            print(json.dumps(report,indent=2))
        finally:
            server.shutdown();server.application.close();server.server_close();thread.join()


if __name__=='__main__':main()
