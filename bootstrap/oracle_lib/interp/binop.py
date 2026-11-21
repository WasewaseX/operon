"""operon oracle: interp.binop (split of bootstrap/oracle.py)."""

import math
from ..annot import type_name
from ..mapops import _map_has, deep_eq
from ..values import Stress



class IBinop:

    def binop(self, op, l, r):
        if op == "+":
            if isinstance(l, bool) or isinstance(r, bool):
                raise Stress("unfolded", f"cannot add {type_name(l)} and {type_name(r)}")
            if isinstance(l, (int, float)) and isinstance(r, (int, float)):
                if isinstance(l, int) and isinstance(r, int) and not (-(2**63) <= l + r <= 2**63 - 1):
                    raise Stress("overflow", "int overflow in '+'")
                return l + r
            if isinstance(l, str) and isinstance(r, str):
                # reg-r4: concat ceiling parity with the Rust core, "exactly
                # at the 512 MiB line" + concat must raise, not allocate 1 GiB
                if len(l) + len(r) > 512 * 1024 * 1024:
                    raise Stress("overflow", "string concat exceeds the 512 MiB ceiling")
                return l + r
            if isinstance(l, bytes) and isinstance(r, bytes):
                # W029 mirror: bytes concat, same ceiling family as strings
                if len(l) + len(r) > 512 * 1024 * 1024:
                    raise Stress("overflow", "bytes concat exceeds the 512 MiB ceiling")
                return l + r
            if isinstance(l, list) and isinstance(r, list):
                if len(l) + len(r) > 64 * 1024 * 1024:
                    raise Stress("overflow", "list concat exceeds the 64M-element ceiling")
                return l + r
            raise Stress("unfolded", f"cannot add {type_name(l)} and {type_name(r)}")
        if op in ("-", "*", "/", "//", "%"):
            # string repetition (Python parity): "ab" * 3 / 3 * "ab";
            # the count must be a true int (Rust matches Value::Int only, so
            # null/float/bool counts fall through to the generic arith error;
            # found by the W050 property harness, strings lane case 19)
            if op == "*" and isinstance(l, str) and isinstance(r, int) and not isinstance(r, bool):
                n = int(r)
                if n < 0:
                    raise Stress("unfolded", "repeat count must be non-negative")
                if n * len(l) > 512 * 1024 * 1024:
                    raise Stress("overflow", "repeat exceeds the 512 MiB string ceiling")
                return l * n
            # W029 mirror: bytes repetition (Python parity), same ceiling
            if op == "*" and isinstance(l, bytes) and isinstance(r, int) and not isinstance(r, bool):
                n = int(r)
                if n < 0:
                    raise Stress("unfolded", "repeat count must be non-negative")
                if n * len(l) > 512 * 1024 * 1024:
                    raise Stress("overflow", "repeat exceeds the 512 MiB bytes ceiling")
                return l * n
            if op == "*" and isinstance(r, str) and isinstance(l, int) and not isinstance(l, bool):
                n = int(l)
                if n < 0:
                    raise Stress("unfolded", "repeat count must be non-negative")
                if n * len(r) > 512 * 1024 * 1024:
                    raise Stress("overflow", "repeat exceeds the 512 MiB string ceiling")
                return r * n
            if op == "*" and isinstance(r, bytes) and isinstance(l, int) and not isinstance(l, bool):
                n = int(l)
                if n < 0:
                    raise Stress("unfolded", "repeat count must be non-negative")
                if n * len(r) > 512 * 1024 * 1024:
                    raise Stress("overflow", "repeat exceeds the 512 MiB bytes ceiling")
                return r * n
            if isinstance(l, (int, float)) and isinstance(r, (int, float)) and not isinstance(l, bool) and not isinstance(r, bool):
                I64MIN, I64MAX = -(2**63), 2**63 - 1
                if op == "-":
                    if isinstance(l, int) and isinstance(r, int) and not (I64MIN <= l - r <= I64MAX):
                        raise Stress("overflow", "int overflow in '-'")
                    return l - r
                if op == "*":
                    if isinstance(l, int) and isinstance(r, int) and not (I64MIN <= l * r <= I64MAX):
                        raise Stress("overflow", "int overflow in '*'")
                    return l * r
                if op == "/":
                    if r == 0:
                        raise Stress("unfolded", "division by zero")
                    return l / r
                if op == "//":
                    if r == 0:
                        raise Stress("unfolded", "division by zero in '//'")
                    # SPEC/parity: floor division, ALWAYS int (i64)
                    q = l // r
                    if isinstance(q, float):
                        # Z-132 (#132 class B): Python's float // IS the
                        # CPython float_divmod law (the Rust core's
                        # divmod_f64); an infinite or i64-overflowing
                        # quotient is the engine's CONTAINED overflow
                        # stress, never a Python crash.
                        if not math.isfinite(q) or q >= 9.223372036854776e18 or q <= -9.223372036854776e18:
                            raise Stress("overflow", "int overflow in '//'")
                        q = int(q)
                    if not (-(2**63) <= q <= 2**63 - 1):
                        raise Stress("overflow", "int overflow in '//'")
                    return q
                if r == 0:
                    raise Stress("unfolded", "modulo by zero")
                if isinstance(l, float) or isinstance(r, float):
                    # Z-131-FLOORMOD: CPython's float_rem law — fmod
                    # (sign follows the dividend) adjusted into the
                    # divisor's sign class, and the zero remainder takes
                    # the DIVISOR's sign (copysign law; the SPEC's
                    # "sign follows divisor" carried into the zeros).
                    # Mirrors num_exact::mod_f64_floored bit-for-bit.
                    # The old float path ran the int mirror formula,
                    # whose l - q*r subtraction always yields +0.0 on
                    # exact multiples (4.0 % -2.0 printed 0.0, not -0.0).
                    m = math.fmod(l, r)
                    if m:
                        if (m < 0) != (r < 0):
                            m += r
                    else:
                        m = math.copysign(0.0, r)
                    return m
                if l == -(2**63) and r == -1:
                    # i64 corner: the quotient 2**63 does not fit, so the
                    # Rust core raises before ever materializing the
                    # remainder, the oracle must mirror that (W32 corpus).
                    raise Stress("overflow", "int overflow in '%'")
                # Mirror the Rust floor-remainder ALGORITHM, not just the
                # result: Rust computes q (trunc divide, floored), then
                # q*b and a-q*b through CHECKED i64 ops, so an intermediate
                # that leaves i64 raises overflow even when the final
                # remainder would fit. Python bignums never overflow, so
                # without this mirror the oracle silently returns where the
                # core raises (found by the W050 property harness, arith
                # lane cases 76/88: i64::MIN % (2**63 - 1)).
                q = abs(l) // abs(r)
                if (l < 0) != (r < 0):
                    q = -q
                if (l < 0) != (r < 0) and q * r != l:
                    q -= 1  # floor rounds down
                rb = q * r
                if not (-(2**63) <= rb <= 2**63 - 1):
                    raise Stress("overflow", "int overflow in '%'")
                m = l - rb
                if not (-(2**63) <= m <= 2**63 - 1):
                    raise Stress("overflow", "int overflow in '%'")
                return m
            if op in ("/", "//", "%"):
                # Z-NOTEPARITY-1 (receipt item 2): the engine routes /,//,%
                # through as_floats (interp.rs Div/FloorDiv/Mod arms) -- a
                # non-numeric pair renders "numeric op needs numbers, found
                # X and Y"; '-' and '*' keep the arith "cannot apply"
                # fallthrough (probe-verified control, byte-identical).
                raise Stress("unfolded", f"numeric op needs numbers, found {type_name(l)} and {type_name(r)}")
            raise Stress("unfolded", f"cannot apply '{op}' to {type_name(l)} and {type_name(r)}")
        if op == "**":
            if isinstance(l, int) and isinstance(r, int) and not isinstance(l, bool) and not isinstance(r, bool) and r >= 0:
                if r > 10_000_000:
                    raise Stress("overflow", "int overflow in '**'")
                val = l ** r
                if not (-(2**63) <= val <= 2**63 - 1):
                    raise Stress("overflow", "int overflow in '**'")
                return val
            if isinstance(l, (int, float)) and isinstance(r, (int, float)) and not isinstance(l, bool) and not isinstance(r, bool):
                # S4-5/F1b+F1c: mirror Rust f64::powf — python raises
                # ZeroDivisionError for 0 ** negative (rust: inf), returns a
                # COMPLEX for a negative finite base with a fractional
                # exponent (rendered <?> where rust returns nan), and raises
                # OverflowError where rust returns ±inf. The rust float path
                # ALSO stresses when the RESULT is infinite with finite
                # operands and a positive exponent — mirrored below.
                out = self._f64_powf(float(l), float(r))
                import math as _m
                if (out == float("inf") or out == float("-inf")) and _m.isfinite(float(l)) and _m.isfinite(float(r)) and float(r) > 0.0:
                    raise Stress("overflow", "float '**' overflowed to infinity")
                return out
            # Z-NOTEPARITY-1: rust Pow's fallback is as_floats too
            raise Stress("unfolded", f"numeric op needs numbers, found {type_name(l)} and {type_name(r)}")
        if op in ("&", "|", "^", "<<", ">>"):
            def as_i(x):
                if isinstance(x, bool):
                    return int(x)
                if isinstance(x, int):
                    return x
                raise Stress("unfolded", f"bitwise op needs ints, found {type_name(x)}")
            a, b = as_i(l), as_i(r)
            if op == "&": return a & b
            if op == "|": return a | b
            if op == "^": return a ^ b
            if b < 0 or b > 63:
                raise Stress("overflow", f"shift amount {b} out of range")
            if op == "<<":
                val = a << b
                # mirror the release-build i64 wrap (two's complement)
                val &= (1 << 64) - 1
                if val >= 2**63:
                    val -= 2**64
                return val
            return a >> b
        if op == "==":
            return deep_eq(l, r)
        if op == "!=":
            return not deep_eq(l, r)
        if op in ("<", "<=", ">", ">="):
            if isinstance(l, str) and isinstance(r, str):
                pass
            elif isinstance(l, (int, float)) and isinstance(r, (int, float)):
                pass
            else:
                raise Stress("unfolded", f"cannot order {type_name(l)} and {type_name(r)}")
            if op == "<": return l < r
            if op == "<=": return l <= r
            if op == ">": return l > r
            return l >= r
        if op == "in":
            if isinstance(r, list):
                return any(deep_eq(l, x) for x in r)
            if isinstance(r, str) and isinstance(l, str):
                return l in r
            if isinstance(r, dict):
                return _map_has(r, l)
            raise Stress("unfolded", f"'in' not defined for {type_name(r)}")
        raise Stress("unfolded", f"unknown op {op}")
