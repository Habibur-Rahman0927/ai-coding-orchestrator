#!/usr/bin/env python3
"""Comparable generated-corpus context quality/cost probe. Never calls a provider."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def evaluate(runtime, sizes=(32, 256, 1024), repeats=3):
    sys.path.insert(0, str(runtime))
    import ccx_workspace.store as module
    rows = []
    for count in sizes:
        with tempfile.TemporaryDirectory(prefix='ccx-context-eval-') as tmp:
            base = Path(tmp); root = base/'project'; root.mkdir()
            subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
            contents = {'AGENTS.md': 'Never deploy. Keep approval boundaries. Preserve every acceptance criterion.\n',
                'architecture.md': 'Architecture: ledger writes use atomic transactions. Decision: ledger version two.\n',
                'zz_target.py': 'def reconcile_ledger():\n    """ledger transaction recovery exact_target_evidence"""\n    return True\n',
                'config/runtime-map.txt': 'routing_convention = isolated\n',
                'errors.md': 'timeout_signature: validated bounded retry preserves idempotency. verified_solution_evidence\n',
                'tests/test_ledger.py': 'from zz_target import reconcile_ledger\ndef test_transaction():\n    assert reconcile_ledger() # acceptance_test_evidence\n',
                'spread.py': 'def begin_payment():\n    return "payment_start_evidence"\n' + '\n'.join('# neutral paragraph' for _ in range(65)) + '\ndef finish_payment():\n    return "payment_finish_evidence"\n'}
            for n in range(count): contents['noise%04d.md'%n]='ledger background common description.\n'*12
            for name, body in contents.items():
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(body)
            store=module.Store(base/'private/workspace.sqlite3'); pid=store.register(root)['id']
            def measure(fn):
                counts={'source_reads':0,'git_processes':0}; original_read=module.read_source; original_run=module.subprocess.run
                def read(*a,**kw): counts['source_reads']+=1;return original_read(*a,**kw)
                def run(*a,**kw):
                    if a and a[0] and a[0][0]=='git': counts['git_processes']+=1
                    return original_run(*a,**kw)
                start=time.perf_counter();cpu=time.process_time()
                with patch.object(module,'read_source',read),patch.object(module.subprocess,'run',run): value=fn()
                return value,dict(counts,wall_ms=round((time.perf_counter()-start)*1000,3),cpu_ms=round((time.process_time()-cpu)*1000,3))
            initial,initial_cost=measure(lambda:store.index(pid))
            unchanged,unchanged_cost=measure(lambda:store.index(pid))
            p=root/'zz_target.py';os.utime(p,ns=(p.stat().st_atime_ns,p.stat().st_mtime_ns+1000000000))
            touch,touch_cost=measure(lambda:store.index(pid))
            p.write_text(contents['zz_target.py']+'# small change\n')
            incremental,incremental_cost=measure(lambda:store.index(pid))
            for _ in range(10):store.add_memory(pid,'project','Ledger decision','Use atomic ledger transactions',kind='observed',source='decision:ledger')
            cases=[{'name':'architecture','query':'atomic transactions architecture','required':['atomic transactions'],'sources':['architecture.md','decision:ledger','AGENTS.md']},
                {'name':'rare_symbol_among_common_matches','query':'ledger reconcile_ledger','required':['exact_target_evidence'],'sources':['zz_target.py','AGENTS.md','architecture.md','decision:ledger']},
                {'name':'explicit_path','query':'config/runtime-map.txt','required':['routing_convention'],'sources':['config/runtime-map.txt','AGENTS.md']},
                {'name':'distributed_symbols','query':'begin_payment finish_payment','required':['payment_start_evidence','payment_finish_evidence'],'sources':['spread.py','AGENTS.md']},
                {'name':'historical_solution','query':'timeout_signature idempotency','required':['verified_solution_evidence'],'sources':['errors.md','AGENTS.md']},
                {'name':'dependency_and_test','query':'test_transaction zz_target','required':['acceptance_test_evidence','reconcile_ledger'],'sources':['tests/test_ledger.py','zz_target.py','AGENTS.md']},
                {'name':'persistent_decision','query':'atomic ledger transactions','required':['Use atomic ledger transactions'],'sources':['decision:ledger','architecture.md','zz_target.py','AGENTS.md']},
                {'name':'mandatory_nonmatching_constraint','query':'unrelated_subject','required':['Never deploy.'],'sources':['AGENTS.md']}]
            case_rows=[]
            for case in cases:
                samples=[];outputs=[]
                for _ in range(repeats):
                    package,cost=measure(lambda:store.context(pid,case['query'],budget=1000,critical=['Preserve approval boundaries','Verify acceptance criteria']))
                    samples.append(cost);outputs.append(package)
                package=outputs[-1];refs=package['references'];matches=[token in package['content'] for token in case['required']]
                case_rows.append(dict(case,recall=sum(matches)/len(matches),constraint_preserved='Never deploy.' in package['content'] and 'Verify acceptance criteria' in package['content'],
                    irrelevant_reference_count=sum(r['source'] not in case['sources'] for r in refs),reference_count=len(refs),bytes=package['bytes'],estimated_tokens=package['estimated_tokens'],
                    median_ms=statistics.median(s['wall_ms'] for s in samples),samples=samples,references=refs))
            (root/'zz_target.py').write_text('def replaced(): return False\n')
            stale=store.context(pid,'reconcile_ledger',budget=1000)
            fresh=module.Store(store.path)
            reopened=fresh.context(pid,'atomic transactions',budget=1000)
            other=base/'other';other.mkdir();subprocess.run(['git','init','-q',str(other)],check=True,capture_output=True)
            other_id=store.register(other)['id'];store.add_memory(other_id,'project','Private','foreign_project_marker')
            isolated=store.context(pid,'foreign_project_marker',budget=1000)
            try:
                import resource
                peak_rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*(1 if sys.platform=='darwin' else 1024)
            except ImportError: peak_rss=None
            with store.connect() as db:
                indexed_count=db.execute('SELECT COUNT(*) FROM documents WHERE project_id=?',(pid,)).fetchone()[0]
                indexed_body_bytes=db.execute('SELECT SUM(length(CAST(body AS BLOB))) FROM documents WHERE project_id=?',(pid,)).fetchone()[0]
                cache_count=db.execute('SELECT COUNT(*) FROM context_packages WHERE project_id=?',(pid,)).fetchone()[0]

            rows.append({'generated_noise_files':count,'indexed_files':indexed_count,'indexed_body_bytes':indexed_body_bytes,'context_package_count':cache_count,'process_peak_rss_bytes':peak_rss,'fresh_controller_decision_recovered':'Use atomic ledger transactions' in reopened['content'],'cross_project_isolated':'foreign_project_marker' not in isolated['content'],'corpus_sha256':hashlib.sha256(json.dumps(contents,sort_keys=True).encode()).hexdigest(),
                'initial':dict(result=initial,cost=initial_cost),'unchanged':dict(result=unchanged,cost=unchanged_cost),'same_content_touch':dict(result=touch,cost=touch_cost),
                'one_file_edit':dict(result=incremental,cost=incremental_cost),'cases':case_rows,'duplicate_memory_records':len(fresh.memories(pid)),
                'stale_rejected':'exact_target_evidence' not in stale['content'],'database_bytes':store.path.stat().st_size,'context_cache_limit':20})
    return {'schema':1,'scope':'Synthetic generated repositories; no provider calls, token savings or human-effort claims',
        'runtime_store_sha256':hashlib.sha256((runtime/'ccx_workspace/store.py').read_bytes()).hexdigest(),'repeats':repeats,'sizes':rows,'provider_reported_usage':None,'cost':None}


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-lib',type=Path,default=ROOT/'engine/lib');p.add_argument('--output',type=Path,required=True);p.add_argument('--sizes',default='32,256,1024');p.add_argument('--repeats',type=int,default=3);a=p.parse_args()
    sizes=tuple(int(x) for x in a.sizes.split(','))
    if not sizes or any(x<1 or x>5000 for x in sizes) or not 1<=a.repeats<=10:p.error('Bound sizes to 1..5000 and repeats to 1..10')
    result=evaluate(a.runtime_lib,sizes,a.repeats);a.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'sizes':len(result['sizes']),'recall':[[(c['name'],c['recall']) for c in row['cases']] for row in result['sizes']]}))
if __name__=='__main__':main()
