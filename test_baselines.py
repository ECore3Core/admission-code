"""Baseline equivalence, wave propagation and event replay checks."""
import random
import unittest
from university_admissions import Pool, Offer, Student, UniversityEngine
from benchmark_admissions import full_rebuild, wave_rebuild, check_equal, replay, summarize


class BaselineTests(unittest.TestCase):
    def test_wave_chain(self):
        pools = [Pool('A', 'A', 1, 'main'), Pool('B', 'B', 1, 'main')]
        students = {
            'x': Student('x', (Offer('A', 1, 0, (2,), 'exam'), Offer('B', 2, 0, (2,), 'exam')), consent=True),
            'y': Student('y', (Offer('A', 1, 0, (1,), 'exam'),), consent=True),
        }
        wave = wave_rebuild(pools, {'A': 1, 'B': 1}, 'consent', students)
        check_equal(wave, full_rebuild(pools, {'A': 1, 'B': 1}, 'consent', students))
        self.assertEqual(wave.assignment('x'), 'B')
        self.assertEqual(wave.last_waves, 4)  # Two rounds in each scenario.

    def test_baselines_random_normalized_states(self):
        rng = random.Random(73)
        for trial in range(120):
            pools = [Pool(str(i), str(i), rng.randrange(4), 'main') for i in range(5)]
            totals = {p.program: p.capacity for p in pools}
            mode = rng.choice(['consent', 'original'])
            local = UniversityEngine(pools, totals, mode)
            for i in range(12):
                selected = rng.sample(pools, rng.randrange(6))
                offers = tuple(Offer(p.id, j+1, 0, (rng.randrange(4), i), 'exam') for j,p in enumerate(selected))
                free = [p for p in pools if len(local.locked[p.id]) < p.capacity]
                lock = rng.choice(free).id if free and rng.random() < .12 else None
                local.add(Student(str(i), offers, bool(rng.randrange(2)), bool(rng.randrange(2)), lock))
            check_equal(local, full_rebuild(pools, totals, mode, local.students))
            check_equal(local, wave_rebuild(pools, totals, mode, local.students))

    def test_replay_metrics(self):
        pools = [Pool('A', 'A', 1, 'main')]
        x = Student('x', (Offer('A', 1, 0, (2,), 'exam'),), consent=True)
        y = Student('y', (Offer('A', 1, 0, (1,), 'exam'),))
        changed = Student('y', y.offers, consent=True)
        events = [('add', x, 'e1', 't1'), ('add', y, 'e2', 't2'),
                  ('replace', changed, 'e3', 't3'), ('remove', 'y', 'e4', 't4')]
        rows = replay(pools, {'A': 1}, 'consent', {}, events, 0)
        summary = summarize(rows)
        self.assertEqual(summary['all']['unique_events'], 4)
        self.assertIn('wave', summary['all'])
        self.assertTrue(all(r['equal'] for r in rows))


if __name__ == '__main__':
    unittest.main()
