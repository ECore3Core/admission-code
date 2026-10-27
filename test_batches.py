import unittest
from benchmark_batches import replay
from university_admissions import Pool

class BatchTests(unittest.TestCase):
    def test_daily_replace_and_remove(self):
        def s(a,score,priority=1):
            return {'id':a,'consent':True,'offers':[{'pool':'A','priority':priority,'route_order':0,'key':[-score],'basis':'test'}]}
        batches=[{'date':'d1','events':[{'op':'add','student':s('a',10)},{'op':'add','student':s('b',20)}]},
                 {'date':'d2','events':[{'op':'replace','student':s('a',30)},{'op':'remove','student_id':'b'}]}]
        rows=replay([Pool('A','A',1,'main')],{'A':1},'consent',batches,0)
        self.assertEqual([r['N'] for r in rows],[2,1])
        self.assertTrue(all(r['equal'] for r in rows))
        self.assertEqual(rows[-1]['local_index_routes'],3)

if __name__=='__main__': unittest.main()
