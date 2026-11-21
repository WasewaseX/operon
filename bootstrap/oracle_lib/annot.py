"""operon oracle: annot (split of bootstrap/oracle.py)."""

from .values import Channel, Gene, ObjInst, SeqObj, Variant, WeakRef



# W01 (L2c), soft annotation matching (mirror of interp.rs ann_matches).
# A value matches by type_name(); `any` accepts everything; `float` accepts
# int (safe numeric widening, `int` refuses float: no silent narrowing);
# TYPED-MODE: capitalization is normalized (`Int`≡`int`, mirrored as
# ann_name_norm) and generic annotations match on their HEAD like the bare
# name (`list[int]` enforces "is a list") — element types stay static-checker
# business. Unions match any alternative; optionals additionally accept null.
def ann_name_norm(name):
    # TYPED-MODE mirror of interp.rs ann_name_norm.
    return name.lower()

def ann_matches(v, ann):
    k = ann[0]
    if k == "named":
        name = ann_name_norm(ann[1])
        if name == "any":
            return True
        if type_name(v) == name:
            return True
        return name == "float" and isinstance(v, int) and not isinstance(v, bool)
    if k == "union":
        return any(ann_matches(v, a) for a in ann[1])
    if k == "opt":
        # TYPED-MODE: optionals accept null, any value matching the inner
        # type (the W01 law), AND the Option family (W06): None outright,
        # Some(payload) when the payload matches.
        if v is None:
            return True
        if isinstance(v, Variant):
            if v.tag == "None":
                return True
            if v.tag == "Some":
                return ann_matches(v.payload, ann[1])
        return ann_matches(v, ann[1])
    if k == "alias":
        # W01-s2: an alias matches as its parse-time-resolved target
        # (mirror of interp.rs TypeAnn::Alias law).
        return ann_matches(v, ann[2])
    if k == "generic":
        head = ann_name_norm(ann[1])
        if head == "any":
            return True
        if head == "list":
            return isinstance(v, list)
        if head == "map":
            return isinstance(v, dict)
        if head == "option":
            return v is None or (isinstance(v, Variant) and v.tag in ("Some", "None"))
        if head == "result":
            return isinstance(v, Variant) and v.tag in ("Ok", "Err")
        # unknown generic head: bare-name fallback (typo never accepts all)
        return type_name(v) == head or (head == "float" and isinstance(v, int) and not isinstance(v, bool))
    return False

def ann_is_typaram(ann, type_params):
    # TYPED-MODE mirror of interp.rs ann_is_typaram: type parameters are
    # erased at runtime; the soft contract is a no-op for a bare param name.
    k = ann[0]
    if k == "named":
        return any(p == ann[1] for (p, _b) in type_params)
    if k == "union":
        return all(ann_is_typaram(a, type_params) for a in ann[1])
    if k == "opt":
        return ann_is_typaram(ann[1], type_params)
    # W01-s2: an alias resolves to its concrete target
    return False

def ann_render(ann):
    # Canonical rendering, must match TypeAnn::render op-for-op.
    k = ann[0]
    if k == "named":
        return ann[1]
    if k == "union":
        return " | ".join(ann_render(a) for a in ann[1])
    if k == "opt":
        return ann_render(ann[1]) + "?"
    if k == "generic":
        return ann[1] + "[" + ", ".join(ann_render(a) for a in ann[2]) + "]"
    if k == "alias":
        return ann[1]
    return "any"

def type_name(v):
    if v is None: return "null"
    if isinstance(v, bool): return "bool"
    if isinstance(v, int): return "int"
    if isinstance(v, float): return "float"
    if isinstance(v, str): return "str"
    if isinstance(v, bytes): return "bytes"
    if isinstance(v, list): return "list"
    if isinstance(v, dict): return "map"
    if isinstance(v, Gene): return "gene"
    if isinstance(v, SeqObj): return "sequence"
    if isinstance(v, ObjInst): return "phenotype"
    if isinstance(v, Variant): return "option" if v.tag in ("Some", "None") else "result"
    if isinstance(v, Channel): return "channel"
    # W013 mirror: the handle type is its own name, the TARGET's type is not
    # leaked (the handle may outlive the target).
    if isinstance(v, WeakRef): return "weak"
    return "native"
