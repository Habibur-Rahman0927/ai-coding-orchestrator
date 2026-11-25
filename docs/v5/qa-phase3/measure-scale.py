import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'engine/lib'))
from ccx_workspace.store import Store

def measured(call):
 start=time.perf_counter();result=call();return result,round((time.perf_counter()-start)*1000,3)
report={'platform':platform.platform(),'python':platform.python_version(),'provider_calls':0,'runs':[],'limitations':['single measurement per size','generated tiny source files','context samples repeated five times','not live provider performance','file metadata discovery remains proportional to repository file count']}
for count in (10,100,1000):
 with tempfile.TemporaryDirectory(prefix='ccx-phase3-scale-') as temporary:
  base=Path(temporary).resolve();root=base/'project';root.mkdir()
  subprocess.run(['git','init','-q',str(root)],check=True,capture_output=True)
  for number in range(count):
   (root/('module_%04d.py'%number)).write_text('def symbol_%04d():\n    return %d\n'%(number,number))
  store=Store(base/'state/workspace.sqlite3');pid=store.register(root)['id']
  initial,initial_ms=measured(lambda:store.index(pid))
  repeated,repeated_ms=measured(lambda:store.index(pid))
  path=root/'module_0000.py';path.write_text('def symbol_0000():\n    return 9999\n')
  incremental,incremental_ms=measured(lambda:store.index(pid))
  latencies=[]
  for _ in range(5):
   context,elapsed=measured(lambda:store.context(pid,'symbol_0000',budget=300));latencies.append(elapsed)
  assert initial['updated']==count and repeated['bytes_read']==0
  assert incremental['updated']==1 and incremental['bytes_read']==path.stat().st_size
  assert 'return 9999' in context['content']
  report['runs'].append({'files':count,'initial_index_ms':initial_ms,'repeat_index_ms':repeated_ms,'one_file_index_ms':incremental_ms,'initial_bytes_read':initial['bytes_read'],'repeat_bytes_read':repeated['bytes_read'],'one_file_bytes_read':incremental['bytes_read'],'one_file_updated':incremental['updated'],'context_median_ms':round(statistics.median(latencies),3),'context_bytes':context['bytes'],'database_bytes':store.path.stat().st_size})
Path('/tmp/ccx-phase3-scale.json').write_text(json.dumps(report,indent=2)+'\n')
