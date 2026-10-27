"""One university, fixed stage, independent seat pools, two views. Python 3.10+."""
from collections import deque
from dataclasses import dataclass
import heapq
from ranking_index import RankingIndex


@dataclass(frozen=True)
class Pool:
    id: str
    program: str
    capacity: int
    category: str


@dataclass(frozen=True)
class Offer:
    pool: str
    priority: int
    route_order: int
    key: tuple[int, ...]  # Smaller is better; include full tie criteria.
    basis: str


@dataclass(frozen=True)
class Student:
    id: str
    offers: tuple[Offer, ...]
    original: bool = False
    consent: bool = False
    locked_pool: str | None = None  # Enrollment ORDER, not consent.


@dataclass(frozen=True)
class Delta:
    mode: str
    student: str
    before: str | None
    after: str | None


class State:
    def __init__(self, pools):
        self.assignment, self.next = {}, {}
        self.held = {p: [] for p in pools}


class UniversityEngine:
    """Policy adapter supplies eligible offers for one stage.

    'all' ignores confirmation; 'confirmed' uses consent or original.
    Capacities include locked seats. Empty quota seats stay reserved.
    Serialize calls. Do not mutate public state; use add/replace/remove.
    Rebuild the engine when stage, capacities or ranking policy changes.
    """
    def __init__(self, pools, totals, confirmation="consent"):
        rows = list(pools)
        self.pools = {p.id: p for p in rows}
        if len(rows) != len(self.pools):
            raise ValueError("Duplicate pool ID")
        if confirmation not in {"consent", "original"}:
            raise ValueError("Unknown confirmation mode")
        if any(type(n) is not int or n < 0 for n in totals.values()):
            raise ValueError("Invalid program totals")
        for p in rows:
            if p.program not in totals or type(p.capacity) is not int:
                raise ValueError("Invalid pool")
            if p.capacity < 0:
                raise ValueError("Negative capacity")
        for program, total in totals.items():
            used = sum(p.capacity for p in rows if p.program == program)
            if used > total:
                raise ValueError("Pools exceed program budget")
        self.confirmation = confirmation
        self.students = {}
        self.reverse = {p: set() for p in totals}
        self.program_pools = {p: [] for p in totals}
        for pool in rows:
            self.program_pools[pool.program].append(pool.id)
        self.keys = {p: {} for p in self.pools}
        self.width = {}
        self.locked = {p: set() for p in self.pools}
        self.views = {m: State(self.pools) for m in ("all", "confirmed")}
        self.last_checks = 0
        self.rankings = {mode: {p: RankingIndex() for p in self.pools}
                         for mode in self.views}

    def _programs(self, s):
        result = {self.pools[o.pool].program for o in s.offers}
        if s.locked_pool is not None:
            result.add(self.pools[s.locked_pool].program)
        return result

    def _eligible(self, s, mode):
        return mode == "all" or getattr(s, self.confirmation)

    def _validate(self, s):
        if not isinstance(s.id, str) or not s.id:
            raise ValueError("Student ID must be a nonempty string")
        offers = tuple(sorted((Offer(o.pool, o.priority, o.route_order,
                                    tuple(o.key), o.basis) for o in s.offers),
                              key=lambda o: (o.priority, o.route_order)))
        s = Student(s.id, offers, s.original, s.consent, s.locked_pool)
        if len({o.pool for o in offers}) != len(offers):
            raise ValueError("At most one normalized offer per pool")
        if len({(o.priority, o.route_order) for o in offers}) != len(offers):
            raise ValueError("Unresolved order of admission routes")
        for o in offers:
            if o.pool not in self.pools or o.priority < 1:
                raise ValueError("Unknown pool or invalid priority")
            if not o.key or any(type(x) is not int for x in o.key):
                raise ValueError("Ranking key must contain integers")
            if o.pool in self.width and len(o.key) != self.width[o.pool]:
                raise ValueError("Inconsistent ranking key width")
            owner = self.keys[o.pool].get(o.key)
            if owner is not None and owner != s.id:
                raise ValueError("Unresolved tie; supply full criteria")
        if s.locked_pool is not None:
            if s.locked_pool not in self.pools:
                raise ValueError("Unknown locked pool")
            occupied = self.locked[s.locked_pool] - {s.id}
            if len(occupied) >= self.pools[s.locked_pool].capacity:
                raise ValueError("Locked enrollments exceed capacity")
        return s

    def _register(self, s):
        self.students[s.id] = s
        for program in self._programs(s):
            self.reverse[program].add(s.id)
        for o in s.offers:
            self.keys[o.pool][o.key] = s.id
            self.width[o.pool] = len(o.key)
            for mode in self.views:
                if self._eligible(s, mode) or s.locked_pool is not None:
                    self.rankings[mode][o.pool].add(o.key, s.id)
        if s.locked_pool is not None:
            self.locked[s.locked_pool].add(s.id)

    def _unregister(self, s):
        for program in self._programs(s):
            self.reverse[program].remove(s.id)
        for o in s.offers:
            del self.keys[o.pool][o.key]
            for mode in self.views:
                if self._eligible(s, mode) or s.locked_pool is not None:
                    self.rankings[mode][o.pool].remove(o.key)
        if s.locked_pool is not None:
            self.locked[s.locked_pool].remove(s.id)
        del self.students[s.id]

    def _run(self, mode, queue, before):
        state = self.views[mode]
        def assign(a, pool):
            before.setdefault(a, state.assignment.get(a))
            state.assignment[a] = pool
        while queue:
            a = queue.popleft()
            s = self.students[a]
            while state.next[a] < len(s.offers):
                o = s.offers[state.next[a]]
                state.next[a] += 1
                self.last_checks += 1
                cap = self.pools[o.pool].capacity - len(self.locked[o.pool])
                if cap == 0:
                    continue
                heap = state.held[o.pool]
                entry = (tuple(-x for x in o.key), a)
                if len(heap) < cap:
                    heapq.heappush(heap, entry)
                    assign(a, o.pool)
                    break
                if entry[0] > heap[0][0]:
                    _, displaced = heapq.heapreplace(heap, entry)
                    assign(a, o.pool)
                    assign(displaced, None)
                    queue.append(displaced)
                    break

    def _delta(self, mode, before):
        now = self.views[mode].assignment
        return [Delta(mode, a, old, now.get(a))
                for a, old in before.items() if old != now.get(a)]

    def add(self, student):
        if student.id in self.students:
            raise ValueError("Student exists; use replace")
        s = self._validate(student)
        if s.locked_pool is not None:
            return self._change(s.id, s)
        self.last_checks = 0
        self._register(s)
        changes = []
        for mode, state in self.views.items():
            before = {s.id: None}
            state.assignment[s.id] = None
            state.next[s.id] = 0
            if self._eligible(s, mode):
                self._run(mode, deque([s.id]), before)
            changes.extend(self._delta(mode, before))
        return tuple(changes)

    def replace(self, student):
        if student.id not in self.students:
            raise KeyError(student.id)
        return self._change(student.id, self._validate(student))

    def remove(self, student_id):
        if student_id not in self.students:
            raise KeyError(student_id)
        return self._change(student_id, None)

    def _change(self, sid, new):
        self.last_checks = 0
        old = self.students.get(sid)
        programs = self._programs(old) if old else set()
        if new is not None:
            programs.update(self._programs(new))
        ids, queue = {sid}, deque(programs)
        while queue:
            program = queue.popleft()
            for a in self.reverse[program]:
                if a in ids:
                    continue
                ids.add(a)
                for other in self._programs(self.students[a]):
                    if other not in programs:
                        programs.add(other)
                        queue.append(other)
        before = {mode: {a: v.assignment.get(a) for a in ids}
                  for mode, v in self.views.items()}
        if old is not None:
            self._unregister(old)
        if new is not None:
            self._register(new)
        else:
            ids.remove(sid)
        changes = []
        for mode, state in self.views.items():
            for program in programs:
                for pool_id in self.program_pools[program]:
                    state.held[pool_id].clear()
            if new is None:
                state.assignment.pop(sid, None)
                state.next.pop(sid, None)
            queue = deque()
            for a in sorted(ids):
                s = self.students[a]
                state.assignment[a] = s.locked_pool
                state.next[a] = 0
                if s.locked_pool is None and self._eligible(s, mode):
                    queue.append(a)
            self._run(mode, queue, before[mode])
            changes.extend(self._delta(mode, before[mode]))
        return tuple(changes)

    def assignment(self, student_id, mode="all"):
        return self.views[mode].assignment[student_id]

    def ranked_page(self, pool_id, mode="all", offset=0, limit=50):
        """Positions refer to the selected scenario's application list."""
        rows = self.rankings[mode][pool_id].page(offset, limit)
        return tuple((rank, a, self.assignment(a, mode) == pool_id)
                     for rank, a in rows)


def demo():
    # Snapshot of a stage: BVI enrollment already fixed by an order.
    pools = [Pool("A:main", "A", 2, "main"),
             Pool("A:special", "A", 1, "special"),
             Pool("A:separate", "A", 1, "separate"),
             Pool("A:target:X", "A", 1, "target:X"),
             Pool("B:main", "B", 1, "main")]
    engine = UniversityEngine(pools, {"A": 5, "B": 1})
    engine.add(Student("olympiad", (), consent=True,
                       locked_pool="A:main"))
    engine.add(Student("anna", (
        Offer("A:main", 1, 0, (-290, -95), "exams"),
        Offer("B:main", 2, 0, (-290, -95), "exams")),
        original=True, consent=True))
    engine.add(Student("boris", (
        Offer("A:main", 1, 0, (-300, -96), "exams"),)))
    for mode in engine.views:
        print(mode, {a: engine.assignment(a, mode)
                     for a in engine.students})
    changed = engine.replace(Student(
        "boris", engine.students["boris"].offers,
        original=True, consent=True))
    print("Consent event:", changed)


if __name__ == "__main__":
    demo()
