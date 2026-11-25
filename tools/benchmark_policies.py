#!/usr/bin/env python3
"""Measure existing routing policies on identical generated tasks; offline only."""
import argparse
import json
from pathlib import Path
import statistics
import sys
sys.dont_write_bytecode=True
from pilot_workloads import run_workload


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    rows=[]
    for key,repeats in (('C',3),('A',1)):
        for policy in ('standard','single_task'):
            for repetition in range(repeats):
                row=run_workload(key,execution_policy=policy);row['repetition']=repetition;rows.append(row)
    groups=[]
    for key in ('C','A'):
        for policy in ('standard','single_task'):
            selected=[r for r in rows if r['workload']==key and r['execution_policy']==policy]
            groups.append({'workload':key,'policy':policy,'runs':len(selected),
                'median_seconds':statistics.median(r['duration_seconds'] for r in selected),
                'provider_fixture_calls':[r['provider_mock_calls'] for r in selected],
                'correction_rounds':[r['correction_rounds'] for r in selected],
                'context_bytes_prepared':[r['usage']['context_bytes_prepared'] for r in selected],
                'synthetic_approval_actions':[r['synthetic_operator_actions'] for r in selected],
                'all_acceptance_passed':all(r['final_acceptance_exit_code']==0 for r in selected)})
    result={'scope':'Existing explicit policies, deterministic providers, actual scoped patches/tests/review fixtures. Not a live A/B/C token or human-effort comparison.',
        'live_provider_calls':0,'provider_reported_tokens':None,'human_effort':None,'cost':None,'groups':groups,'runs':rows}
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(groups))
if __name__=='__main__':main()
