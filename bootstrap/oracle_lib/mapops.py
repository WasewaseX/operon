"""operon oracle: mapops (split of bootstrap/oracle.py)."""




class _NanKey(float):
    """z-s0-parity (#107.1): a NaN map key that bypasses CPython's dict
    identity fast-path. deep_eq(NaN, NaN) is False (SPEC: NaN never equals
    NaN), so repeated NaN-key writes must ACCUMULATE (the Rust contract,
    len(m) == 2 after two m[n]=v writes with n NaN), but storing the same
    float object collapses to one dict slot via the identity shortcut.
    Identity-based hashing + the inherited float __eq__ (False for NaN
    pairs) gives each write its own entry while lookups stay honest:
    hash(nan) is identity-based on CPython 3.10+, so raw-NaN has/read/del
    probes never match a _NanKey slot (matching Rust: has(nan) false).
    Renders exactly like the plain float (float.__repr__ inherited)."""

    __hash__ = object.__hash__


def _nkey(k):
    """Wrap a NaN float key for map writes; everything else passes through."""
    if isinstance(k, float) and k != k:
        return _NanKey(k)
    return k


# ---- #214 + Z-MAPORDER: map keys key by VALUE in pure INSERTION order ----
# Rust's MapStore is a Vec of (key, value) pairs scanned with deep_eq — any
# Value is a legal key and Vec order IS the iteration contract: scalar keys
# upsert-IN-PLACE (MapStore::insert's position_h hit keeps the position),
# container keys mirror the KC_OTHER arm EXACTLY (ALWAYS APPEND, never
# replace — equal-content container keys coexist and the linear scan finds
# the first), del removes the FIRST match.
#
# Plain Python dicts cannot key by list/dict (unhashable), so the oracle
# keeps a side pair-list; the ORDER law is maintained structurally:
#
#   PROMOTION. A map stays a plain dict until its FIRST container key
#   (list/dict/Variant) arrives. At that moment the dict is the exact
#   insertion-order HEAD prefix, and it FREEZES: from then on
#     - container keys ALWAYS append to the side TAIL (KC_OTHER),
#     - a brand-NEW scalar key (dict probe misses) appends to the TAIL,
#     - an upsert of a dict-resident key stays in the dict IN PLACE,
#     - an upsert of a tail-resident key updates that pair IN PLACE.
#   dict entries therefore always precede tail entries and the
#   concatenation IS the pure insertion sequence — the documented
#   dict-before-side mixed-map deviation of the original #214 layout is
#   retired structurally, not per-consumer.
#
# The registry holds a STRONG ref alongside the id so a recycled id can
# never cross-attach (dicts are not weakref-able in CPython; the
# process-lifetime model mirrors the Rust CLI's documented Rc-graph
# teardown law). The pin-everything cost applies only to maps that
# actually receive container keys; scalar-only maps (the whole perf
# corpus) never promote and keep native dict speed. Equality on both
# stores is deep_eq with its seen-pair cycle law — the EXACT Rust
# semantics (canonical-frozen wrappers would mis-render nested-cycle-
# depth shapes the pair law calls equal). Known pre-existing residual
# (P1 finding (a), corpus-unexposed, unchanged here): pre-promotion
# bool/int keys collapse through the native dict probe (True == 1);
# post-promotion they are deep_eq-distinct in the tail exactly like the
# Rust two-slot law.
_MAP_SIDE = {}  # id(map) -> (map, side_list)


def _side(tv, create=False):
    """The map's side pair-list; readers get a read-only empty tuple when
    the map has none (only the insert path creates an entry)."""
    ent = _MAP_SIDE.get(id(tv))
    if ent is not None and ent[0] is tv:
        return ent[1]
    if create:
        side = []
        _MAP_SIDE[id(tv)] = (tv, side)
        return side
    return ()


def _map_insert_key(tv, key, val):
    from .values import Variant
    """Store key -> val on map tv. Scalars (str/int/float/bool/bytes/None)
    and ObjInst (id-hashable, the pinned pheno_equality path) upsert with
    the scalar law (replace in place, MapStore::insert's position_h hit);
    containers (list/dict/Variant) mirror the KC_OTHER arm EXACTLY: ALWAYS
    APPEND, never replace — equal-content container keys coexist and the
    linear scan finds the first (verified against the Rust core: two [3,4]
    inserts -> len 2, lookup returns "a").

    Z-MAPORDER: the FIRST container key PROMOTES the map — the dict freezes
    as the insertion-order HEAD and every brand-new scalar key lands in the
    side TAIL (dict probe hit -> in-place dict upsert; tail deep_eq hit ->
    in-place tail upsert; else append). dict-then-tail is therefore always
    the pure insertion sequence (see the block comment above)."""
    if isinstance(key, (list, dict, Variant)) and not isinstance(key, (str, bytes)):
        _side(tv, create=True).append([key, val])
        return
    ent = _MAP_SIDE.get(id(tv))
    if ent is not None and ent[0] is tv and key not in tv:
        # promoted and the dict probe missed: upsert into the TAIL when an
        # equal key already lives there, else append (NaN keys never probe-
        # match — each write accumulates, the z-s0-parity law)
        for pair in ent[1]:
            if deep_eq(pair[0], key):
                pair[1] = val
                return
        ent[1].append([_nkey(key), val])
        return
    tv[_nkey(key)] = val


_MAP_MISS = object()


_NON_SCALAR_SCAN_CAP = 512  # sec-r5 F-12 (Z-512-CAP-PARITY): mirrors
# value.rs NON_SCALAR_SCAN_CAP — container-key probes scan the first 512
# UNIFIED items only; beyond the cap the key is TREATED AS ABSENT.


def _is_container_key(key):
    from .values import Variant
    """The KC_OTHER class: list/dict/Variant keys (bytes stay SCALAR, W029)."""
    return isinstance(key, (list, dict, Variant)) and not isinstance(key, (str, bytes))


def _map_lookup(tv, key):
    """deep_eq scan across BOTH stores; returns the value or _MAP_MISS.
    Z-MAPORDER: dict-HEAD-then-side-TAIL IS the insertion order (the dict
    froze at promotion, see the block comment), so the scan order is the
    MapStore first-match law exactly.
    Z-512-CAP-PARITY (sec-r5 F-12): a container-key probe scans only the
    first 512 UNIFIED items (head+tail counted in insertion order —
    position_h counts unified items); a match beyond the cap is treated as
    absent (SPEC §763). Scalar probes and the int/float cross-equality
    class stay UNBOUNDED, mirroring position_h's uncapped scalar arms."""
    if _is_container_key(key):
        n = 0
        for kk, vv in tv.items():
            if n >= _NON_SCALAR_SCAN_CAP:
                return _MAP_MISS
            n += 1
            if deep_eq(kk, key):
                return vv
        for pair in _side(tv):
            if n >= _NON_SCALAR_SCAN_CAP:
                return _MAP_MISS
            n += 1
            if deep_eq(pair[0], key):
                return pair[1]
        return _MAP_MISS
    for kk, vv in tv.items():
        if deep_eq(kk, key):
            return vv
    for pair in _side(tv):
        if deep_eq(pair[0], key):
            return pair[1]
    return _MAP_MISS


def _map_lookup_tail(tv, key):
    """First deep_eq match in the side TAIL only — for consumers that
    already probed the dict (member read, destructure, pattern match)."""
    ent = _MAP_SIDE.get(id(tv))
    if ent is not None and ent[0] is tv:
        for pair in ent[1]:
            if deep_eq(pair[0], key):
                return pair[1]
    return _MAP_MISS


def _map_member_get(tv, key):
    """Member-style read (string key): dict probe first (C-speed, and the
    hit is unique — a tail key never dict-equals a dict key by the append
    law), then the side TAIL. Returns _MAP_MISS when absent."""
    if key in tv:
        return tv[key]
    return _map_lookup_tail(tv, key)


def _map_has(tv, key):
    return _map_lookup(tv, key) is not _MAP_MISS


def _map_del(tv, key):
    """Remove deep_eq matches in insertion order: the dict HEAD loop first
    (scalar keys are deduped by the upsert, so at most one match), then the
    side TAIL mirrors MapStore::del EXACTLY: position_h -> remove the FIRST
    match only (container keys can coexist as dups, del pops one). Z-MAPORDER:
    head-before-tail is the insertion order, so this removes the FIRST
    matching entry of the unified store and the survivors keep their order.
    Z-512-CAP-PARITY: a container-key del scans only the first 512 UNIFIED
    items — a match beyond the cap is treated as absent and the del is a
    silent miss (len unchanged), mirroring the engine's two-phase delete
    whose phase-1 probe is position() (the KC_OTHER arm .take(512)).
    Scalar dels keep the full unbounded scan (position_h's scalar arms are
    uncapped)."""
    if _is_container_key(key):
        n = 0
        for kk in list(tv.keys()):
            if n >= _NON_SCALAR_SCAN_CAP:
                return
            n += 1
            if deep_eq(kk, key):
                del tv[kk]
                return
        ent = _MAP_SIDE.get(id(tv))
        if ent is not None and ent[0] is tv:
            side = ent[1]
            for i, p in enumerate(side):
                if n >= _NON_SCALAR_SCAN_CAP:
                    return
                n += 1
                if deep_eq(p[0], key):
                    del side[i]
                    return
        return
    for kk in list(tv.keys()):
        if deep_eq(kk, key):
            del tv[kk]
    ent = _MAP_SIDE.get(id(tv))
    if ent is not None and ent[0] is tv:
        side = ent[1]
        for i, p in enumerate(side):
            if deep_eq(p[0], key):
                del side[i]
                break


def _map_len(tv):
    return len(tv) + len(_side(tv))


def _map_keys(tv):
    # Z-MAPORDER: head-then-tail IS the insertion sequence (structurally,
    # since the dict froze at promotion) — no per-consumer merge needed.
    return list(tv.keys()) + [p[0] for p in _side(tv)]


def _map_values(tv):
    return list(tv.values()) + [p[1] for p in _side(tv)]


def _map_items(tv):
    return list(tv.items()) + [(p[0], p[1]) for p in _side(tv)]


def _map_items_side(tv):
    """Only the SIDE entries (for wire/display merges that must not drop
    container-key entries; dict entries are rendered by the caller)."""
    return [(p[0], p[1]) for p in _side(tv)]


def deep_eq(a, b, _pairs=None):
    # reg-r4: cycle-safe, a pair of containers already being compared is
    # treated as equal (mirror of the Rust deep_eq's seen-pair set); the
    # old version recursed forever on `cyc == cyc`
    from .values import ObjInst, Variant, WeakRef
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    # W029 mirror: bytes equal iff same byte content
    if isinstance(a, bytes) or isinstance(b, bytes):
        return isinstance(a, bytes) and isinstance(b, bytes) and a == b
    # W06 (D-014) mirror: variants equal iff same tag + payload deep_eq;
    # families distinct (Some(x) != Ok(x)); None == None.
    if isinstance(a, Variant) or isinstance(b, Variant):
        if not (isinstance(a, Variant) and isinstance(b, Variant)):
            return False
        if a.tag != b.tag:
            return False
        if a.payload is None and b.payload is None:
            return True
        if a.payload is None or b.payload is None:
            return False
        return deep_eq(a.payload, b.payload, _pairs)
    # builder-B parity finding (W34 stage 2, PR #28 pin): instances are DATA,
    # not handles, equal iff same class name AND deep-equal field values.
    # Mirror of the Rust Value::Obj arm (the old fall-through made every pair
    # of distinct instances False regardless of state).
    if isinstance(a, ObjInst) or isinstance(b, ObjInst):
        if not (isinstance(a, ObjInst) and isinstance(b, ObjInst)):
            return False
        if a.defn.name != b.defn.name:
            return False
        fa, fb = a.fields, b.fields
        if fa is fb:
            return True  # a structure equals itself
        if _pairs is None:
            _pairs = set()
        key = (id(fa), id(fb))
        if key in _pairs:
            return True  # already comparing this pair (cycle)
        _pairs.add(key)
        try:
            if len(fa) != len(fb):
                return False
            return all(any(deep_eq(k, k2, _pairs) and deep_eq(v, v2, _pairs)
                           for k2, v2 in fb.items()) for k, v in fa.items())
        finally:
            _pairs.discard(key)
    # W013 mirror: weak handles are identity-based like channels (same
    # backing-store address), a handle never equals the target it references.
    if isinstance(a, WeakRef) or isinstance(b, WeakRef):
        return (isinstance(a, WeakRef) and isinstance(b, WeakRef)
                and a.kind == b.kind and a.addr == b.addr)
    if type(a) is not type(b) and not (a is None and b is None):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return a == b
        return False
    if isinstance(a, (list, dict)):
        if _pairs is None:
            _pairs = set()
        key = (id(a), id(b))
        if key in _pairs:
            return True  # already comparing this pair (cycle)
        _pairs.add(key)
        try:
            if isinstance(a, list):
                return len(a) == len(b) and all(
                    deep_eq(x, y, _pairs) for x, y in zip(a, b))
            # #214: compare BOTH stores — container keys live in the side
            # pair-list, so a dict-vs-dict walk that only iterated the
            # Python dict would call two all-container-key maps equal the
            # moment both dicts were empty (vacuous all-over-empty; caught
            # by deep_eq_exact_pin p3/p4/p5 the moment the side store
            # landed). _map_items merges both stores in the documented
            # order; equality itself is order-independent (any-pair scan).
            ia, ib = _map_items(a), _map_items(b)
            if len(ia) != len(ib):
                return False
            return all(any(deep_eq(k, k2, _pairs) and deep_eq(v, v2, _pairs)
                           for k2, v2 in ib) for k, v in ia)
        finally:
            _pairs.discard(key)
    return a == b
