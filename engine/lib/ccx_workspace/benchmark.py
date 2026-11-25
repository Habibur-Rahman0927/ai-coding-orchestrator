"""Comparable local context benchmark; no fabricated provider usage or costs."""
import math
import time
import json


def usage_report(store, workflow_id):
    """Aggregate every provider stage, including retries, reviews and correction.

    Missing usage stays missing. Cached/reasoning counts remain separate metadata,
    never subtracted from input/output totals. This performs no provider calls.
    """
    from .workflows import WorkflowEngine
    workflow=WorkflowEngine(store).status(workflow_id)
    fields=('input_tokens','output_tokens','cached_tokens','reasoning_tokens')
    totals={name:0 for name in fields};missing={name:0 for name in fields};calls=[]
    with store.connect() as db:
        rows=list(db.execute("SELECT * FROM w5_actions WHERE workflow_id=? AND role IN ('planner','executor','reviewer') ORDER BY started_at",(workflow_id,)))
    for row in rows:
        request=json.loads(row['request']);response=json.loads(row['response'] or '{}');usage=response.get('usage') or {}
        aliases={'input_tokens':'prompt_tokens','output_tokens':'completion_tokens','cached_tokens':'cached_input_tokens'}
        measured={}
        for name in fields:
            value=usage.get(name,usage.get(aliases.get(name,'')))
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0:
                totals[name]+=value;measured[name]=value
            else: missing[name]+=1;measured[name]=None
        calls.append({'action_id':row['id'],'provider':row['provider'],'role':row['role'],'state':row['state'],
                      'model':request.get('provider_model'),'offline_mock':request.get('offline_mock',True),
                      'session_id':response.get('session_id'),'usage':measured,
                      'initial_snapshot':row['before_hash'], 'context_bytes':len(json.loads(request['prompt']).get('context',{}).get('content','').encode())})
    return {'workflow_id':workflow_id,'status':workflow['status'],'objective':workflow['objective'],
            'criteria':workflow['criteria'],'providers':workflow['providers'],'context_mode':workflow.get('context_mode','retrieved'),
            'provider_calls':len(calls),'all_roles_included':True,'calls':calls,
            'reported_totals':{name:totals[name] if missing[name]==0 and calls else None for name in fields},
            'reported_partial_totals':totals,'missing_usage_calls':missing,
            'local_tokens_accounted':workflow['tokens_used'],'cost_accounting':workflow['cost_accounting'],
            'duration_seconds':round(workflow['updated_at']-workflow['started_at'],3) if workflow['started_at'] else None,
            'correction_rounds':sum(t['attempts'] for t in workflow['tasks']),
            'verification_success':workflow['status']=='COMPLETED',
            'live_execution':bool(calls) and not any(c['offline_mock'] for c in calls),
            'cost_savings':None}


def compare_workflows(store, baseline_id, optimized_id):
    baseline=usage_report(store,baseline_id);optimized=usage_report(store,optimized_id)
    reasons=[]
    if baseline_id==optimized_id: reasons.append('Two distinct runs are required')
    for field in ('objective','criteria','providers'):
        if baseline[field]!=optimized[field]: reasons.append('Mismatched '+field)
    if baseline['context_mode']!='full_index' or optimized['context_mode']!='retrieved':
        reasons.append('Use explicit full_index baseline and retrieved optimized context modes')
    for run in (baseline,optimized):
        if not run['live_execution']: reasons.append('Mocked or unrecorded live execution')
        if not run['verification_success']: reasons.append('Both runs must pass completion gates')
        if any(run['reported_totals'][f] is None for f in ('input_tokens','output_tokens')):
            reasons.append('Provider-reported input/output usage is incomplete')
        if any(not c['model'] for c in run['calls']): reasons.append('Exact model/settings not fully recorded')
    if baseline['calls'] and optimized['calls']:
        if baseline['calls'][0]['initial_snapshot']!=optimized['calls'][0]['initial_snapshot']:
            reasons.append('Source revisions differ')
        models=lambda run: sorted(set((c['provider'],c['model'] or '') for c in run['calls']))
        if models(baseline)!=models(optimized): reasons.append('Provider/model selections differ')
    # Native reasoning/speed settings may be inherited externally; until adapters
    # provide a measured settings fingerprint, do not assert strict comparability.
    if any(c['provider'] in ('codex','claude') for r in (baseline,optimized) for c in r['calls']):
        reasons.append('Inherited native reasoning/speed settings need independent comparison evidence')
    result={'baseline':baseline,'optimized':optimized,'comparable':not reasons,
            'limitations':sorted(set(reasons)),'input_token_reduction':None,'total_token_reduction':None,
            'optimization_verified':False,'cached_tokens_treated_as_eliminated':False}
    if not reasons:
        before=baseline['reported_totals'];after=optimized['reported_totals']
        result['input_token_reduction']=before['input_tokens']-after['input_tokens']
        result['total_token_reduction']=sum(before[f]-after[f] for f in ('input_tokens','output_tokens'))
        result['optimization_verified']=result['total_token_reduction']>0 and result['input_token_reduction']>0
    return result

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
