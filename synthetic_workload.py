"""Seeded model workload used in the article; no real applicant records.

The generator is unchanged from the local experiment of 28 October 2026.
For N=4000 and seat ratio 0.3, 60 pools each contain 20 places.
"""
import math
import random


def make_case(n, ratio, clusters, seed=20261028):
    rng = random.Random(seed + n + clusters)
    g = 60
    cap = math.ceil(ratio * n / g)
    pools = [dict(id=f'P{i:02}', program=f'P{i:02}', capacity=cap,
                  category='main') for i in range(g)]
    totals = {p['id']: cap for p in pools}

    def student(i):
        cluster = i % clusters
        choices = list(range(cluster * (g // clusters), (cluster + 1) * (g // clusters)))
        routes = rng.sample(choices, 3)
        score = rng.randrange(100, 301)
        return dict(id=f'S{i:06}', consent=rng.random() < .5,
                    offers=[dict(pool=f'P{p:02}', priority=j + 1, route_order=0,
                                 key=[-score, i], basis='synthetic')
                            for j, p in enumerate(routes)])

    initial = [student(i) for i in range(n)]
    events = []
    for j in range(10):
        new = student(n + j)
        changed = dict(initial[j])
        changed['consent'] = not changed['consent']
        events.extend([
            dict(id=f'add-{j}', timestamp=f't{3*j:03}', op='add', student=new),
            dict(id=f'replace-{j}', timestamp=f't{3*j+1:03}', op='replace', student=changed),
            dict(id=f'remove-{j}', timestamp=f't{3*j+2:03}', op='remove',
                 student_id=initial[10 + j]['id']),
        ])
    return dict(metadata=dict(kind='synthetic', seed=seed, N=n, G=g,
                              routes_per_student=3, capacity_per_pool=cap,
                              total_capacity=g*cap, target_seat_ratio=ratio,
                              actual_seat_ratio=g*cap/n, clusters=clusters,
                              description='Seeded random preferences within disjoint equal-size pool groups; '
                              'ten additions, ten consent toggles and ten withdrawals; no quotas or orders.'),
                pools=pools, totals=totals, confirmation='consent',
                initial_students=initial, events=events)


def components(initial, pools):
    adjacency = {p['id']: set() for p in pools}
    for s in initial:
        ids = [o['pool'] for o in s['offers']]
        for p in ids:
            adjacency[p].update(ids)
    seen = set()
    groups = []
    for p in adjacency:
        if p in seen:
            continue
        todo = [p]
        component = set()
        while todo:
            q = todo.pop()
            if q in component:
                continue
            component.add(q)
            todo.extend(adjacency[q] - component)
        seen.update(component)
        groups.append(component)
    sizes = [sum(any(o['pool'] in group for o in s['offers']) for s in initial)
             for group in groups]
    return dict(pool_components=len(groups), largest_applicant_component=max(sizes))
