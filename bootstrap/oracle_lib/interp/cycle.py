"""operon oracle: interp.cycle (split of bootstrap/oracle.py)."""

from ..mapops import _map_items_side, _side
from ..values import ObjInst, Variant



class ICycle:

    def _cycle_prune(self):
        # strong-ref registrations persist by design (no GC, D-013): a
        # detected cycle stays in the gauge for the rest of the run, so
        # there is nothing to prune — this hook exists to keep the walk's
        # call shape symmetric with the gauge's registration step
        return

    def _cycle_walk_reaches(self, root, v):
        # does the walk from v reach the container at address root?
        # (the seed is v itself: if v IS the target, inserting it closes a
        # self-reference, push(a, a)). Returns True (reached), False
        # (completed, not reached) or None (budget exhausted, inconclusive).
        budget = [self.WALK_BUDGET]
        return self._cycle_walk_reaches_root(root, set(), [v], budget)

    def _cycle_register(self, target):
        # register the target container (list / dict / instance fields dict)
        # once per address and once per subgraph: if any container reachable
        # from the target is already registered, the cycle group was already
        # counted through that member.
        if isinstance(target, ObjInst):
            target = target.fields
        addr = id(target)
        self._cycle_prune()
        registered = {a for (_w, a) in self.cycle_regs}
        if addr in registered:
            return
        stack, seen = [], set()
        stack.extend(target.values() if isinstance(target, dict) else target)
        if isinstance(target, dict):
            # #214: side values are children too (the containment walk)
            stack.extend(p[1] for p in _map_items_side(target))
        # budgeted dedupe walk: an inconclusive dedupe registers anyway,
        # the detection at the insertion already proved a cycle at the
        # target (mirror of the Rust dedupe budget)
        budget = [self.WALK_BUDGET]
        while stack:
            cur = stack.pop()
            if budget[0] == 0:
                break  # inconclusive: register the proven cycle
            budget[0] -= 1
            if isinstance(cur, list):
                a = id(cur)
                if a in registered: return  # a member of this subgraph is registered
                if a in seen: continue
                seen.add(a)
                stack.extend(cur)
            elif isinstance(cur, dict):
                a = id(cur)
                if a in registered: return
                if a in seen: continue
                seen.add(a)
                # Z-MAPORDER: a nested promoted map carries tail values too
                stack.extend(cur.values())
                stack.extend(p[1] for p in _side(cur))
            elif isinstance(cur, ObjInst):
                a = id(cur.fields)
                if a in registered: return
                if a in seen: continue
                seen.add(a)
                stack.extend(cur.fields.values())
            elif isinstance(cur, Variant):
                if cur.payload is not None:
                    stack.append(cur.payload)
        # no GC: cycles persist once detected, mirror the Rust gauge;
        # strong refs keep the registration honest (a plain list/dict is
        # not weakref-able, and persistence is the modeled semantics)
        self.cycle_regs.append((target, addr))

    def _cycle_note_insert(self, target, v):
        # insertion-time detection, called BEFORE the edge lands; an
        # inconclusive detection walk (budget exhausted) does not register:
        # best-effort detection, the conservative direction for the GAUGE
        # is persistence of what is already registered
        if isinstance(target, ObjInst):
            target = target.fields
        if isinstance(v, (list, dict, ObjInst, Variant)) and \
                self._cycle_walk_reaches(id(target), v) is True:
            self._cycle_register(target)

    def _live_cycles(self):
        self._cycle_prune()
        n, keep = 0, []
        # ONE budget shared by every verification in this call: the whole
        # re-verify pass is bounded no matter how many cycles are registered
        budget = [self.WALK_BUDGET]
        for t, a in self.cycle_regs:
            if t is None:
                continue
            # re-verify: still reachable from itself (walk the CHILDREN,
            # the container itself is the pre-seen root, never the seed)
            seen, stack = {a}, []
            if isinstance(t, dict):
                # Z-MAPORDER: the re-verify walk sees BOTH stores (the
                # registration walk at _cycle_note_insert always did; the
                # prune side walked the dict only and could "prove dead" a
                # cycle living through a tail value)
                stack.extend(t.values())
                stack.extend(p[1] for p in _side(t))
            else:
                stack.extend(t)
            verdict = self._cycle_walk_reaches_root(a, seen, stack, budget)
            # True: proven alive. False: proven reclaimed or broken, drop
            # the entry. None: budget exhausted, the entry stays counted
            # (death must be PROVEN, persistence is D-013).
            still = verdict is not False
            if still:
                n += 1
                keep.append((t, a))
        self.cycle_regs = keep
        return n

    def _cycle_walk_reaches_root(self, root, seen, stack, budget):
        # budget is a one-element list shared by the callers; returns
        # True (reached), False (completed, not reached) or None
        # (budget exhausted mid-walk, inconclusive)
        while stack:
            cur = stack.pop()
            if budget[0] == 0:
                return None
            budget[0] -= 1
            if isinstance(cur, list):
                a = id(cur)
                if a == root: return True
                if a in seen: continue
                seen.add(a)
                stack.extend(cur)
            elif isinstance(cur, dict):
                a = id(cur)
                if a == root: return True
                if a in seen: continue
                seen.add(a)
                # Z-MAPORDER: a nested promoted map carries tail values too
                stack.extend(cur.values())
                stack.extend(p[1] for p in _side(cur))
            elif isinstance(cur, ObjInst):
                a = id(cur.fields)
                if a == root: return True
                if a in seen: continue
                seen.add(a)
                stack.extend(cur.fields.values())
            elif isinstance(cur, Variant):
                if cur.payload is not None:
                    stack.append(cur.payload)
        return False
