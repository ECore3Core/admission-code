"""Repeat the article's synthetic batch experiment with a fixed 50-case grid.

One excluded warm-up, then nine measured repeats by default. Local sequential
replacements versus one full rebuild, both views; equality checks outside timer.
The grid was selected in the 29 October study and is frozen for this recheck.
No real applicant data, third-party dependencies or network access required.
"""
import argparse
import csv
from datetime import datetime, timezone
import gc
import hashlib
import json
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
from time import perf_counter_ns

from benchmark_admissions import (
    check_equal, full_rebuild, quantile, student_from_json, wave_rebuild,
)
from synthetic_workload import components, make_case
from university_admissions import Pool, Student

ARTICLE_GRID = {
    1: tuple(range(1, 13)),
    10: (1, 10, 20, 30, 40, *range(50, 81), 90, 100),
}


def summarize(rows, clusters, batch_size):
    group = [r for r in rows if r['clusters'] == clusters and r['batch_size'] == batch_size]
    result = dict(clusters=clusters, batch_size=batch_size, measurements=len(group), metrics={})
    for method in ('local', 'full', 'wave'):
        values = [r[method + '_ms'] for r in group]
        result['metrics'][method] = dict(p50_ms=quantile(values, .5), p95_ms=quantile(values, .95))
    for method in ('full', 'wave'):
        ratios = [r[method + '_ms'] / r['local_ms'] for r in group]
        rng = random.Random(20261029 + clusters * 100 + batch_size)
        boots = sorted(statistics.median(rng.choices(ratios, k=len(ratios))) for _ in range(10000))
        low, high = quantile(boots, .025), quantile(boots, .975)
        result[method] = dict(
            paired_speedup_median=statistics.median(ratios),
            bootstrap95_low=low, bootstrap95_high=high,
            min=min(ratios), max=max(ratios),
            verdict='local_wins' if low > 1 else ('local_loses' if high < 1 else 'uncertain'),
        )
    return result


def measure(case, batch_size, repeats=9):
    pools = [Pool(**p) for p in case['pools']]
    initial = {s['id']: student_from_json(s) for s in case['initial_students']}
    clusters = case['metadata']['clusters']
    if not 1 <= batch_size <= len(initial) or repeats < 1:
        raise ValueError('Positive repeats and batch size within initial population required')
    chosen = list(initial.values())[:batch_size]
    changed = [Student(s.id, s.offers, s.original, not s.consent, s.locked_pool) for s in chosen]
    current = dict(initial)
    current.update({s.id: s for s in changed})
    rows = []
    for repeat in range(-1, repeats):
        local = full_rebuild(pools, case['totals'], 'consent', initial)
        methods = ['local', 'full', 'wave']
        random.Random(20261029 + clusters * 10000 + batch_size * 20 + repeat).shuffle(methods)
        times, engines = {}, {}
        for method in methods:
            start = perf_counter_ns()
            if method == 'local':
                for s in changed:
                    local.replace(s)
                result = local
            elif method == 'full':
                result = full_rebuild(pools, case['totals'], 'consent', current)
            else:
                result = wave_rebuild(pools, case['totals'], 'consent', current)
            times[method + '_ms'] = (perf_counter_ns() - start) / 1e6
            engines[method] = result
        check_equal(local, engines['full'])
        check_equal(local, engines['wave'])
        if repeat >= 0:
            rows.append(dict(clusters=clusters, batch_size=batch_size, repeat=repeat, equal=True, **times))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=9)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('Positive repeats required')
    if args.out.exists() and any(args.out.iterdir()):
        parser.error('Use a new or empty output directory to preserve previous measurements')
    args.out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    sources = ['synthetic_workload.py', 'benchmark_boundary.py', 'university_admissions.py',
               'ranking_index.py', 'benchmark_admissions.py']
    source_hashes = {n: hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in sources}
    try:
        commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent,
                                         text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    rows, cases, input_hashes, structure = [], [], {}, {}
    for clusters, grid in ARTICLE_GRID.items():
        case = make_case(4000, .3, clusters)
        raw = json.dumps(case).encode('utf-8')
        name = f'input_K{clusters}_SYNTHETIC.json'
        (args.out / name).write_bytes(raw)
        input_hashes[name] = hashlib.sha256(raw).hexdigest()
        structure[str(clusters)] = components(case['initial_students'], case['pools'])
        for batch_size in grid:
            rows.extend(measure(case, batch_size, args.repeats))
            item = summarize(rows, clusters, batch_size)
            cases.append(item)
            print(f'K={clusters} b={batch_size}: S={item["full"]["paired_speedup_median"]:.3f}; '
                  f'{item["full"]["verdict"]}; assignments and rankings equal', flush=True)
    csv_path = args.out / 'latencies.csv'
    with csv_path.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(
        N=4000, G=60, capacity_per_pool=20, routes_per_student=3,
        repeats=args.repeats, measurements_per_method=len(rows), conditions=len(cases),
        seed=20261028, python=sys.version, executable=sys.executable,
        platform=platform.platform(), processor=platform.processor(), gc_enabled=gc.isenabled(),
        timer='perf_counter_ns', all_equal=True, cases=cases, structure=structure,
        source_sha256=source_hashes, input_sha256=input_hashes,
        latencies_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        git_commit=commit, started_utc=started, finished_utc=datetime.now(timezone.utc).isoformat(),
        scope='Prepared consent toggles for first b participants; fresh initial state outside timer; '
              'sequential local replace versus one full rebuild; both views, equality outside timer.',
        uncertainty='Percentile bootstrap CI of paired median across timing repeats of one fixed workload; '
                    'not variation across datasets. Grid selected in the original study, frozen for this replay. '
                    'No universal or monotone threshold.',
    )
    (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
