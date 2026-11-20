# VIEW-EXERCISE — S0 report on the v2 ownership/view rules

**Task-ID:** V2-S0-B (NEXT.md §6) · **Date:** 2026-11-20 · **Corpus:**
[view-exercise/parser_iter.op](view-exercise/parser_iter.op) — 813 lines of
realistic lexer/parser/iterator code written against the v2 ownership rules
(second-class scoped views, single-argument elision, `from(param)` for
ambiguous ties, views never cross suspension).

**This is brief §23 test 2 — the cheapest architecture-killing test for the
ownership model.** The question it answers: *do the v2 view rules survive a
real parser/iterator workload, and is `from(param)` occasional or everywhere?*

## Verdict

**The reduced-lifetime premise HOLDS on this corpus.** `from(param)` was
needed **2 times in 813 lines** (once per ~400 lines) — comfortably within
"occasional" per the brief's kill criterion ("if it is more than occasional,
report that the reduced-lifetime premise has failed"). Every other view
return resolved by single-argument elision or self-elision. No rule needed to
be relaxed to write the code; no case was found where a view had to be
stored, returned untied, or smuggled across a suspension point.

The count, precisely:

| measure | count | where |
|---|---|---|
| `from(param)` annotations | **2** | `longer_hint(a,b) -> &Str from(b)`, `dominant_entry(local,outer) -> &SymEntry from(outer)` (§7) |
| view returns resolved by elision (incl. self-elision) | 12 | `SymTab::lookup`, `SymTab::span_of`, `Arena::get`, `Arena::expr_of`, `Lexer::text_at`, `Lexer::rest`, `Parser::peek`, `Parser::last_ident_text`, `Parser::tok_text`, `Parser::origin`, `Parser::peek_text`, `entry_for_token` |
| returned iterators (view structs returned under the same tie rule) | 2 | `lex_all(src, tab) -> TokenIter`, `only_kind(inner, kind) -> KindFilter` (§5) |
| marked suspension sites | 5 | `spellcheck_and_fetch`, `fetch_remote`, `parse_with_hints`, plus 2 stubs; **plus 1 non-compiling negative example** documenting the exact V4 error shape (§8) |
| explicit copies forced by the model | 2 classes | `make_owned(text)` at view→owned boundaries; `copy` at value boundaries (`Parser::bump`, `Parser::new` scratch slot) |

## Findings (what writing the code actually felt like)

**F1 — spans-not-slices is a legitimate pressure reducer, and it is not
rule-dodging.** Decision D1 in the corpus: tokens carry `(u32,u32)` byte
spans; borrowed text is recovered through `Lexer::text_at` / `Parser::tok_text`.
Spans are the representation the S1 strict core wants anyway (they survive
serialization, diagnostics, and replay), so this is the natural design, not a
view-avoidance trick. The borrowed path is still exercised everywhere — 12
elided view returns exist precisely because the code wants slices back.

**F2 — the one real ergonomic cost: iterator adapters are consumable views.**
A `TokenIter` holds a borrow, so rule V1 makes every adapter built on it
(`KindFilter`) a view too: adapters can be *created and consumed* in place,
returned under the same tie rules, but never stored in a struct or shipped
across a cell. This matches the ref-struct intent (C# precedent cited in the
brief) and is honest Rust-grade behavior for borrowing iterators, but it is
the friction point to watch. The S1 checker's error messages for "you tried
to store an iterator" must be excellent, and std should provide the common
collect-to-owned adapters so users rarely hand-roll view-holding structs.

**F3 — `from(param)` reads as naming the output region, not the physical
source.** Both uses are the classic "pick between two borrowed inputs"
shape (longer-of-two hints, dominant scope entry). Under the region
reading — the annotation names which argument's lifetime the return is
charged to; the checker still proves both inputs outlive the return scope —
both functions are natural to write and natural to call. This reading must
be pinned in the S1 spec (V2-S1-A); the alternative stricter reading
(return must physically trace to the named param) would have made both
cases compile errors and forced owned returns, which we would also accept —
record both readings for the spec author to choose from.

**F4 — the forced-copy surface is small and always at an explicit boundary.**
Views never silently become owned: `make_owned` / `copy` mark each site, and
both occur exactly where the design wants them (diagnostics keeping text,
values crossing suspension, values entering owned containers). No copy was
needed "just to satisfy the checker" in the parser hot path itself.

**F5 — method-heavy code elides cleanly.** The parser/lexer style (methods
returning views into `self`) resolved by self-elision in every case; no
lifetime parameter had to be written by hand anywhere in the corpus. The
only lifetime-like syntax that remains is the `'a` on view-struct
*declarations* (`Lexer<'a>`, `Parser<'a>`), which is a definition-site
annotation, not a call-site burden.

## Threats to validity (stated plainly, per the brief's honesty rules)

1. **Author bias:** the same person wrote the rules and the corpus. The
   corpus is realistic in size and shape (real lexer/parser structure, not
   toy snippets), but it is one workload. The remaining high-risk corpora
   are: zero-copy wire-protocol parsers (overlapping slices), GUI
   component trees (long-lived borrowed state), and graph algorithms on
   arena handles. They are queued as V2-S1-C follow-ups, not silently skipped.
2. **Not machine-checked yet.** This is a design exercise in sketch syntax;
   the v2.11 frontend cannot compile it. The count is a human measurement.
   V2-S1-A/B must encode the rules in the checker and run this corpus as
   the first acceptance fixture; a mechanical `from()`-per-kloc statistic
   then becomes a standing metric.
3. **Sketch syntax choices could bias the count.** The `?` early-return and
   the `copy`/`move` markers are informal here; if the real syntax makes
   copies noisier or view types harder to name, the ergonomic findings
   (especially F2) could get worse. That risk is captured in V2-S1-A.

## Bottom line for NEXT.md

No architecture kill. Proceed to S1 with the view rules as written in
NEXT.md §3 (rules 1–6), carrying F2 (adapter ergonomics) and F3 (pin the
`from()` semantics) into the V2-S1-A spec work. The premise "scoped views
reduce lifetime friction to occasional explicit annotations" survived its
first realistic test.
