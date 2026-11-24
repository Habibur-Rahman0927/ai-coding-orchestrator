"""Comparable local context benchmark; no fabricated provider usage or costs."""
import math
import time

def benchmark(store, project_id, queries, budget=2000):
    store.project(project_id)
    with store.connect() as db:
        baseline='\n'.join(r[0] for r in db.execute('SELECT body FROM documents WHERE project_id=? ORDER BY path',(project_id,)))
    rows=[]
    for query in queries:
        start=time.monotonic()
        package=store.context(project_id,query,budget=budget,critical=['Preserve acceptance criteria and verify changes.'])
        rows.append({'query':query,'baseline_bytes':len(baseline.encode()),'optimized_bytes':package['bytes'],
                     'baseline_estimated_tokens':math.ceil(len(baseline.encode())/4),
                     'optimized_estimated_tokens':package['estimated_tokens'],
                     'retrieval_ms':round((time.monotonic()-start)*1000,3),
                     'reference_count':len(package['references']),
                     'provider_reported_usage':None,'cached_tokens':None,
                     'quality_measure':'source references and critical constraints retained; no live task-quality claim'})
    before=sum(r['baseline_bytes'] for r in rows);after=sum(r['optimized_bytes'] for r in rows)
    return {'runs':rows,'baseline_bytes':before,'optimized_bytes':after,
            'context_byte_reduction':before-after,'context_byte_reduction_percent':round(100*(before-after)/before,2) if before else None,
            'token_counts':'estimated, not provider-reported','cost_savings':None,
            'comparison':'same indexed corpus and queries; baseline repeats full indexed context per query'}
