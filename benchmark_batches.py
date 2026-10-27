"""Replay normalized daily batches locally; no network or applicant export.

Input: pools, totals, confirmation, batches[{date, events[{op, student|student_id}]}].
The adapter must document provenance, capacities, ranking and exclusion rules.
No per-applicant records are written to results. See BENCHMARK.md.
"""
import argparse
import csv
import gc
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter_ns
from benchmark_admissions import student_from_json, full_rebuild, wave_rebuild, check_equal, quantile
from university_admissions import Pool


def replay(pools, totals, confirmation, batches, repeat):
    current = {}
    local = full_rebuild(pools, totals, confirmation, current)
    results = []
    for seq, batch in enumerate(batches):
        prepared=[]
        local_index_routes=0
        for event in batch['events']:
            op=event['op']
            if op not in {'add','replace','remove'}:
                raise ValueError('Unknown operation')
            payload=event['student_id'] if op=='remove' else student_from_json(event['student'])
            sid=payload if op=='remove' else payload.id
            if op=='add' and sid in current:
                raise ValueError('Duplicate addition')
            if op in {'replace','remove'} and sid not in current:
                raise ValueError('Missing applicant')
            if sid in current:
                local_index_routes+=len(current[sid].offers)
            if op=='remove':
                del current[sid]
            else:
                current[sid]=payload
                local_index_routes+=len(payload.offers)
            prepared.append((op,payload))
        calls=['local','full','wave']
        shift=(repeat+seq)%3
        calls=calls[shift:]+calls[:shift]
        times={}; engines={}; local_checks=0; deltas=0
        for method in calls:
            start=perf_counter_ns()
            if method=='local':
                for op,payload in prepared:
                    changed=getattr(local,op)(payload)
                    deltas+=len(changed)
                    local_checks+=local.last_checks
                result=local
            elif method=='full':
                result=full_rebuild(pools,totals,confirmation,current)
            else:
                result=wave_rebuild(pools,totals,confirmation,current)
            times[method]=(perf_counter_ns()-start)/1e6
            engines[method]=result
        check_equal(local,engines['full'])
        check_equal(local,engines['wave'])
        E=sum(len(s.offers) for s in current.values())
        row={'repeat':repeat,'batch':seq,'date':batch['date'],'events':len(prepared),
             'N':len(current),'E':E,'equal':True,'local_checks':local_checks,
             'full_checks':engines['full'].last_checks,'wave_checks':engines['wave'].last_checks,
             'waves_both_scenarios':engines['wave'].last_waves,
             'local_index_routes':local_index_routes,'full_index_routes':E,'wave_index_routes':E,
             'changed_assignments':deltas}
        row.update({m+'_ms':t for m,t in times.items()})
        results.append(row)
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--repeats',type=int,default=5)
    args=parser.parse_args()
    if args.repeats<1: parser.error('Positive repeats required')
    raw=args.input.read_bytes(); data=json.loads(raw.decode('utf-8-sig'))
    pools=[Pool(**p) for p in data['pools']]
    batches=data['batches']
    if not batches: raise ValueError('No batches')
    replay(pools,data['totals'],data.get('confirmation','consent'),batches,-1)
    rows=[]
    for repeat in range(args.repeats):
        rows+=replay(pools,data['totals'],data.get('confirmation','consent'),batches,repeat)
        print(f'Repeat {repeat+1}/{args.repeats}: {len(batches)} batches; assignments and rankings equal',flush=True)
    args.out.mkdir(parents=True,exist_ok=True)
    with (args.out/'batch_latencies.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    metrics={}
    for method in ('local','full','wave'):
        vals=[r[method+'_ms'] for r in rows]
        checks=[sum(r[method+'_checks'] for r in rows if r['repeat']==i) for i in range(args.repeats)]
        assert len(set(checks))==1
        indexed=[sum(r[method+'_index_routes'] for r in rows if r['repeat']==i) for i in range(args.repeats)]
        metrics[method]={'p50_ms':quantile(vals,.5),'p95_ms':quantile(vals,.95),
                         'max_ms':max(vals),'total_ms_per_replay':sum(vals)/args.repeats,
                         'proposal_checks_per_replay':checks[0],
                         'index_route_operations_per_replay':indexed[0]}
    try:
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=Path(__file__).parent,text=True,stderr=subprocess.DEVNULL).strip()
    except (OSError,subprocess.CalledProcessError): commit=None
    sources=['university_admissions.py','ranking_index.py','benchmark_admissions.py','benchmark_batches.py']
    summary={'unit':'daily batch, both all and confirmed views','N':rows[-1]['N'],'E':rows[-1]['E'],
             'G':len(pools),'batches':len(batches),'events_per_replay':sum(len(b['events']) for b in batches),
             'repeats':args.repeats,'measurements_per_method':len(rows),'all_equal':True,
             'python':sys.version,'platform':platform.platform(),'processor':platform.processor(),
             'gc_enabled':gc.isenabled(),'timer':'perf_counter_ns','git_commit_before_run':commit,
             'input_sha256':hashlib.sha256(raw).hexdigest(),
             'source_sha256':{n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources},
             'metrics':metrics}
    (args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
