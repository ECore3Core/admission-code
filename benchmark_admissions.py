"""Replay a normalized local event log: incremental, full queue and full wave DA.

Usage: python benchmark_admissions.py input.json --out results --repeats 5
Input parsing, policy compilation, output comparison and disk writes are
outside the measured interval. No database or network latency is measured.
"""
import argparse
from collections import deque
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import platform
import random
import sys
from time import perf_counter_ns
from university_admissions import Pool, Offer, Student, UniversityEngine


def student_from_json(row):
    return Student(
        row['id'],
        tuple(Offer(o['pool'], o['priority'], o['route_order'],
                    tuple(o['key']), o['basis']) for o in row['offers']),
        row.get('original', False), row.get('consent', False),
        row.get('locked_pool'),
    )


def full_rebuild(pools, totals, confirmation, students):
    """Fresh state, one proposal queue per scenario, same heaps and indexes.

    Uses private methods of the bundled engine; keep module versions together.
    Unlike calling add for every record, it does not produce per-record deltas.
    """
    engine = UniversityEngine(pools, totals, confirmation)
    for s in sorted(students.values(), key=lambda s: (s.locked_pool is None, s.id)):
        engine._register(engine._validate(s))
    for mode, state in engine.views.items():
        queue = deque()
        for a, s in engine.students.items():
            state.assignment[a] = s.locked_pool
            state.next[a] = 0
            if s.locked_pool is None and engine._eligible(s, mode):
                queue.append(a)
        engine._run(mode, queue, {})
    return engine


def check_equal(local, full):
    for mode in local.views:
        if local.views[mode].assignment != full.views[mode].assignment:
            raise AssertionError(f'Assignments differ in {mode}')
        for pool in local.pools:
            for begin in range(0, len(local.students), 200):
                if local.ranked_page(pool, mode, begin, 200) != full.ranked_page(
                        pool, mode, begin, 200):
                    raise AssertionError(f'Ranking differs in {mode}/{pool}')


def wave_rebuild(pools, totals, confirmation, students):
    """Synchronous DA: rejected applicants may propose only next wave.

    Same registration, heaps and ranking indexes as the full queue baseline.
    All assignments start empty, except enrollments fixed by an order.
    """
    engine = UniversityEngine(pools, totals, confirmation)
    engine.last_waves = 0
    for s in sorted(students.values(), key=lambda s: (s.locked_pool is None, s.id)):
        engine._register(engine._validate(s))
    for mode, state in engine.views.items():
        active = []
        for a, s in engine.students.items():
            state.assignment[a] = s.locked_pool
            state.next[a] = 0
            if s.locked_pool is None and engine._eligible(s, mode) and s.offers:
                active.append(a)
        while active:
            engine.last_waves += 1
            proposals = {}
            for a in active:
                offer = engine.students[a].offers[state.next[a]]
                state.next[a] += 1
                engine.last_checks += 1
                proposals.setdefault(offer.pool, []).append((a, offer))
            rejected = []
            for pool, incoming in proposals.items():
                cap = engine.pools[pool].capacity - len(engine.locked[pool])
                held = state.held[pool]
                for a, offer in incoming:
                    entry = (tuple(-x for x in offer.key), a)
                    if cap == 0:
                        rejected.append(a)
                    elif len(held) < cap:
                        heapq.heappush(held, entry)
                        state.assignment[a] = pool
                    elif entry[0] > held[0][0]:
                        _, displaced = heapq.heapreplace(held, entry)
                        state.assignment[a] = pool
                        state.assignment[displaced] = None
                        rejected.append(displaced)
                    else:
                        rejected.append(a)
            active = [a for a in rejected
                      if state.next[a] < len(engine.students[a].offers)]
    return engine


def replay(pools, totals, confirmation, initial, events, repeat):
    current = dict(initial)
    local = full_rebuild(pools, totals, confirmation, current)
    rng = random.Random(repeat)
    rows = []
    for sequence, event in enumerate(events):
        op, payload, event_id, timestamp = event
        if op == 'add':
            if payload.id in current:
                raise ValueError(f'Duplicate addition: {event_id}')
            current[payload.id] = payload
        elif op == 'replace':
            if payload.id not in current:
                raise ValueError(f'Missing student: {event_id}')
            current[payload.id] = payload
        else:
            del current[payload]

        def local_call():
            return getattr(local, op)(payload)

        calls = ['local', 'full', 'wave']
        rng.shuffle(calls)  # Reduce systematic first-run/cache bias.
        times, full, wave, changes = {}, None, None, None
        for name in calls:
            start = perf_counter_ns()
            if name == 'local':
                changes = local_call()
            elif name == 'full':
                full = full_rebuild(pools, totals, confirmation, current)
            else:
                wave = wave_rebuild(pools, totals, confirmation, current)
            times[name] = (perf_counter_ns() - start) / 1_000_000
        check_equal(local, full)
        check_equal(local, wave)
        rows.append({
            'repeat': repeat, 'sequence': sequence, 'event_id': event_id,
            'timestamp': timestamp, 'operation': op,
            'students': len(current),
            'local_ms': times['local'], 'full_ms': times['full'],
            'wave_ms': times['wave'], 'wave_checks': wave.last_checks,
            'waves_both_scenarios': wave.last_waves,
            'local_checks': local.last_checks,
            'full_checks': full.last_checks,
            'changed_assignments': len(changes), 'equal': True,
        })
    return rows


def quantile(values, q):
    """Nearest-rank empirical quantile."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def summarize(rows):
    result = {}
    for op in ['all', 'add', 'replace', 'remove']:
        group = rows if op == 'all' else [r for r in rows if r['operation'] == op]
        if not group:
            continue
        item = {'measurements': len(group),
                'unique_events': len({r['sequence'] for r in group})}
        for method in ['local', 'full', 'wave']:
            values = [r[f'{method}_ms'] for r in group]
            item[method] = {
                'p50_ms': quantile(values, .50),
                'p95_ms': quantile(values, .95),
                'p99_ms': quantile(values, .99), 'max_ms': max(values),
                'total_ms': sum(values),
            }
        item['total_time_ratio_full_to_local'] = (
            item['full']['total_ms'] / item['local']['total_ms'])
        item['total_time_ratio_wave_to_local'] = (
            item['wave']['total_ms'] / item['local']['total_ms'])
        item['p99_sample_warning'] = item['unique_events'] < 100
        result[op] = item
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--repeats', type=int, default=5)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    raw = args.input.read_bytes()
    data = json.loads(raw.decode('utf-8-sig'))
    origin = data['metadata']
    if origin.get('kind') not in {'real', 'synthetic'}:
        raise ValueError('metadata.kind must be real or synthetic')
    if not origin.get('description'):
        raise ValueError('Document data provenance in metadata.description')
    pools = [Pool(**p) for p in data['pools']]
    totals = data['totals']
    confirmation = data.get('confirmation', 'consent')
    initial = {}
    for row in data['initial_students']:
        student = student_from_json(row)
        if student.id in initial:
            raise ValueError('Duplicate initial student')
        initial[student.id] = student
    events, seen = [], set()
    for e in data['events']:
        if e['id'] in seen:
            raise ValueError('Duplicate event ID')
        seen.add(e['id'])
        if e['op'] not in {'add', 'replace', 'remove'}:
            raise ValueError('Stage/capacity changes require a separate dataset')
        payload = e['student_id'] if e['op'] == 'remove' else student_from_json(e['student'])
        events.append((e['op'], payload, e['id'], e['timestamp']))
    if not events:
        raise ValueError('An event log is required to measure update latency')
    replay(pools, totals, confirmation, initial, events, -1)  # Warm-up excluded.
    rows = []
    for repeat in range(args.repeats):
        rows.extend(replay(pools, totals, confirmation, initial, events, repeat))
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / 'latencies.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        'data_origin': origin, 'input_sha256': hashlib.sha256(raw).hexdigest(),
        'python': sys.version, 'platform': platform.platform(),
        'processor': platform.processor(), 'repeats': args.repeats,
        'timer': 'perf_counter_ns',
        'scope': 'algorithm and ranking indexes; no DB, no network, no equality check',
        'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                          for name in ['university_admissions.py','ranking_index.py','benchmark_admissions.py']},
        'metrics': summarize(rows),
    }
    (args.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Completed: {len(events)} events, origin={origin["kind"]}')
    print(f'Results: {args.out.resolve()}')


if __name__ == '__main__':
    main()
