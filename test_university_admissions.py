import sys, random, unittest
from pathlib import Path
from collections import deque
from university_admissions import *


def reference(e, mode):
    fixed={p:len(e.locked[p]) for p in e.pools}
    held={p:[] for p in e.pools}
    result={a:s.locked_pool for a,s in e.students.items()}
    cursor={a:0 for a in e.students}
    queue=deque(reversed(list(e.students)))
    while queue:
        a=queue.popleft(); s=e.students[a]
        if s.locked_pool or not e._eligible(s,mode): continue
        while cursor[a]<len(s.offers):
            o=s.offers[cursor[a]]; cursor[a]+=1
            cap=e.pools[o.pool].capacity-fixed[o.pool]
            candidate=held[o.pool]+[a]
            def key(b): return next(x.key for x in e.students[b].offers if x.pool==o.pool)
            candidate.sort(key=key); winners=candidate[:cap]
            if a not in winners: continue
            for b in held[o.pool]:
                if b not in winners: result[b]=None; queue.append(b)
            held[o.pool]=winners; result[a]=o.pool; break
    return result

class Tests(unittest.TestCase):
    def test_bvi_quota_confirmation(self):
        pools=[Pool('main','A',1,'main'),Pool('quota','A',1,'special')]
        e=UniversityEngine(pools,{'A':2})
        e.add(Student('exams',(Offer('main',1,0,(1,-300),'exams'),),consent=True))
        e.add(Student('bvi',(Offer('main',1,0,(0,1),'bvi'),)))
        e.add(Student('q',(Offer('quota',1,0,(1,-200),'exams'),),consent=True))
        self.assertEqual(e.assignment('bvi'),'main')
        self.assertEqual(e.assignment('exams'),None)
        self.assertEqual(e.assignment('exams','confirmed'),'main')
        self.assertEqual(e.assignment('q'),'quota')
        e.replace(Student('bvi',e.students['bvi'].offers,consent=True))
        self.assertEqual(e.assignment('exams','confirmed'),None)

    def test_locked_and_original(self):
        e=UniversityEngine([Pool('p','A',1,'main')],{'A':1},'original')
        e.add(Student('x',(Offer('p',1,0,(1,),'exams'),),consent=True))
        self.assertIsNone(e.assignment('x','confirmed'))
        e.add(Student('locked',(),locked_pool='p'))
        self.assertIsNone(e.assignment('x'))
        self.assertEqual(e.assignment('locked','confirmed'),'p')
        e.remove('locked')
        self.assertEqual(e.assignment('x'),'p')

    def test_invalid_input_is_rejected(self):
        with self.assertRaises(ValueError):
            UniversityEngine([Pool('p','A',2,'main')],{'A':1})
        e=UniversityEngine([Pool('p','A',1,'main')],{'A':1})
        e.add(Student('x',(Offer('p',1,0,(1,),'exams'),)))
        with self.assertRaises(ValueError):
            e.add(Student('y',(Offer('p',1,0,(1,),'exams'),)))
        self.assertEqual(set(e.students),{'x'})

    def test_random_mixed_events(self):
        r=random.Random(20261020); states=0
        for trial in range(100):
            pools=[Pool(f'{p}:{q}',str(p),r.randrange(4),q)
                   for p in range(r.randint(1,5)) for q in ('main','special')]
            totals={p.program:sum(x.capacity for x in pools if x.program==p.program) for p in pools}
            e=UniversityEngine(pools,totals,r.choice(['original','consent']))
            count=0
            for step in range(100):
                action=r.choice(['add','add','replace','remove']) if e.students else 'add'
                old={m:dict(v.assignment) for m,v in e.views.items()}
                if action=='remove': changes=e.remove(r.choice(list(e.students)))
                else:
                    if action=='add': count+=1; a=str(count)
                    else: a=r.choice(list(e.students))
                    selected=r.sample(pools,r.randrange(len(pools)+1))
                    offers=tuple(Offer(p.id,i+1,0,(r.randrange(20),int(a)),'exams') for i,p in enumerate(selected))
                    lock=None
                    free=[p.id for p in pools if len(e.locked[p.id]-{a})<p.capacity]
                    if free and r.random()<.08: lock=r.choice(free)
                    s=Student(a,offers,r.choice([False,True]),r.choice([False,True]),lock)
                    changes=e.add(s) if action=='add' else e.replace(s)
                expected_delta=set()
                for mode,state in e.views.items():
                    expected=reference(e,mode)
                    self.assertEqual(state.assignment,expected)
                    for pool in pools:
                        items = [(o.key, a) for a,s in e.students.items()
                                 if e._eligible(s,mode) or s.locked_pool is not None
                                 for o in s.offers if o.pool==pool.id]
                        ordered = [a for _,a in sorted(items)]
                        offset, limit = 1, 3
                        rows = e.ranked_page(pool.id,mode,offset,limit)
                        self.assertEqual(rows,tuple(
                            (i+1,a,expected[a]==pool.id)
                            for i,a in enumerate(ordered)
                            if offset <= i < offset+limit))
                    for a in old[mode].keys()|expected.keys():
                        if old[mode].get(a)!=expected.get(a):
                            expected_delta.add((mode,a,old[mode].get(a),expected.get(a)))
                    for p in pools:
                        self.assertLessEqual(sum(x==p.id for x in expected.values()),p.capacity)
                self.assertEqual({(d.mode,d.student,d.before,d.after) for d in changes},expected_delta)
                states+=1
        print('Mixed-event states verified:',states)

if __name__=='__main__': unittest.main()
