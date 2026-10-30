import hashlib
import json
import unittest
from benchmark_boundary import ARTICLE_GRID, measure, summarize
from synthetic_workload import components, make_case


class BoundaryTests(unittest.TestCase):
    def test_generator_matches_saved_article_inputs(self):
        # Hashes of the exact synthetic JSON inputs retained on 29 October 2026.
        expected = {
            1: '3b914b38216e2723ed0aa321f6ef556a064128ad3aeea3a9e1b5e28b156eb778',
            10: 'decedb7a95e296f40f5e52afaf42b8fb704822e23180dfcd3913433245ee9b1c',
        }
        for k, digest in expected.items():
            case = make_case(4000, .3, k)
            self.assertEqual(hashlib.sha256(json.dumps(case).encode()).hexdigest(), digest)
            self.assertEqual(components(case['initial_students'], case['pools'])['pool_components'], k)
        self.assertEqual(sum(map(len, ARTICLE_GRID.values())), 50)

    def test_replay_checks_three_methods_and_excludes_warmup(self):
        rows = measure(make_case(40, .3, 1), batch_size=3, repeats=2)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r['repeat'] for r in rows], [0, 1])
        self.assertTrue(all(r['equal'] for r in rows))
        for r in rows:
            self.assertTrue(all(r[m + '_ms'] > 0 for m in ('local', 'full', 'wave')))

    def test_paired_ratios_not_ratio_of_marginal_medians(self):
        rows = [dict(clusters=1, batch_size=1, repeat=i, local_ms=local,
                     full_ms=full, wave_ms=full)
                for i, (local, full) in enumerate([(1, 2), (2, 8), (100, 200)])]
        result = summarize(rows, 1, 1)
        self.assertEqual(result['full']['paired_speedup_median'], 2)
        self.assertEqual(result['full']['verdict'], 'local_wins')


if __name__ == '__main__':
    unittest.main()
