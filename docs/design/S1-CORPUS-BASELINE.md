# S1-CORPUS-BASELINE — oracle-lane sweep (V2-S1-C evidence)

**Date:** 2026-11-21 · **Commit:** 875a443

Python oracle lane (`bootstrap/oracle.py run`) over every `tests/differential/*.op` file (114 files), 29.0s total wall time. Command:

```
python3 scripts/s1_corpus_baseline.py
```

This is the pre-MIR baseline required by [STRICT-CORE.md](STRICT-CORE.md) §5: engine-vs-oracle divergence is attributable only when the oracle lane is known-good. Legend: PASS = ran clean (rc 0); RC1-PIN = designed error-path pin rendered its frozen block (the corpus pins W05/Z-116/Z-132-class failures byte-for-byte across lanes, so rc 1 without a traceback is the expected outcome); FAIL = traceback or unexpected rc (an oracle finding, recorded verbatim); HANG/ERROR = infrastructure. These rows say nothing about S1 parity until the MIR lane joins.

**Result: 114 files — PASS=111, RC1-PIN=3**

| file | status | detail |
|---|---|---|
| arith_pinned.op | PASS | 12 out line(s) |
| arrays_pin.op | PASS | 49 out line(s) |
| bigint.op | PASS | 14 out line(s) |
| biocore_pin.op | PASS | 32 out line(s) |
| bk_slots_pin.op | PASS | 3 out line(s) |
| builtin_caps_gaps.op | PASS | 6 out line(s) |
| builtin_caps_probe.op | PASS | 1 out line(s) |
| builtin_core_gaps.op | PASS | 4 out line(s) |
| builtin_exit_gaps.op | PASS | 3 out line(s) |
| builtin_state_introspection.op | PASS | 1 out line(s) |
| builtin_time_shape.op | PASS | 1 out line(s) |
| burst_bins_pin.op | PASS | 4 out line(s) |
| bytes.op | PASS | 17 out line(s) |
| cancel.op | PASS | 11 out line(s) |
| capwindow_pin.op | PASS | 27 out line(s) |
| channels.op | PASS | 33 out line(s) |
| collections_typed.op | PASS | 16 out line(s) |
| const_freeze.op | RC1-PIN | designed error path: [fallback E2030] phantom call to 'display'; result null |
| deep_eq_adversarial_pin.op | PASS | 32 out line(s) |
| deep_eq_exact_pin.op | PASS | 22 out line(s) |
| deque.op | PASS | 7 out line(s) |
| distance_unicode_pin.op | PASS | 10 out line(s) |
| doc_comments.op | PASS | 3 out line(s) |
| env_process.op | PASS | 14 out line(s) |
| float_mod_floored_pin.op | PASS | 28 out line(s) |
| generics.op | PASS | 12 out line(s) |
| graph.op | PASS | 25 out line(s) |
| grn_methyl_combo.op | PASS | 4 out line(s) |
| guard_arms.op | PASS | 5 out line(s) |
| heap.op | PASS | 8 out line(s) |
| int_float_exact2_pin.op | PASS | 21 out line(s) |
| keyword_edit_replace.op | PASS | 1 out line(s) |
| keyword_ires.op | PASS | 1 out line(s) |
| keyword_tad.op | PASS | 0 out line(s) |
| keyword_tad_lib.op | PASS | 0 out line(s) |
| lex_zero_pin.op | PASS | 15 out line(s) |
| map_container_keys.op | PASS | 20 out line(s) |
| map_del_alias_pin.op | PASS | 10 out line(s) |
| map_order_mixed.op | PASS | 31 out line(s) |
| match_v2.op | PASS | 38 out line(s) |
| math_domain.op | PASS | 7 out line(s) |
| math_overflow_pin.op | PASS | 21 out line(s) |
| memory_model.op | PASS | 5 out line(s) |
| mod_res.op | PASS | 2 out line(s) |
| mod_res_lib1.op | PASS | 0 out line(s) |
| mod_res_lib2.op | PASS | 0 out line(s) |
| namespaces.op | PASS | 7 out line(s) |
| namespaces2.op | PASS | 13 out line(s) |
| namespaces2_lib.op | PASS | 0 out line(s) |
| noise_pin.op | PASS | 3 out line(s) |
| noteparity_pin.op | PASS | 15 out line(s) |
| numeric_abuse.op | PASS | 28 out line(s) |
| numeric_literals.op | PASS | 7 out line(s) |
| occupy_sum_combo_pin.op | PASS | 1 out line(s) |
| option_result.op | PASS | 25 out line(s) |
| option_result_null.op | PASS | 14 out line(s) |
| overflow_contract.op | PASS | 18 out line(s) |
| p1_map_keys_pin.op | PASS | 25 out line(s) |
| p2p3p5_opt_pins.op | PASS | 48 out line(s) |
| p4_member_read_pin.op | PASS | 25 out line(s) |
| p6_loop_scope_pins.op | PASS | 16 out line(s) |
| p6_scope_note_parity.op | PASS | 9 out line(s) |
| parser_depth_calls_pin.op | PASS | 3 out line(s) |
| parser_depth_leak_pin.op | PASS | 2 out line(s) |
| path.op | PASS | 8 out line(s) |
| pheno_equality.op | PASS | 12 out line(s) |
| phenotype_compound_pin.op | PASS | 3 out line(s) |
| quorum_state_pin.op | PASS | 12 out line(s) |
| range_step_wrap_pin.op | PASS | 28 out line(s) |
| regex_corpus.op | PASS | 9 out line(s) |
| result_std.op | PASS | 30 out line(s) |
| s3_136h_pool_pin.op | PASS | 39 out line(s) |
| s3_136t2_pin.op | PASS | 9 out line(s) |
| scope.op | PASS | 7 out line(s) |
| sort_stability_pin.op | PASS | 14 out line(s) |
| splice_m6a.op | PASS | 3 out line(s) |
| stdlib_csv_sepcollusion.op | PASS | 24 out line(s) |
| stdlib_url_utf8.op | PASS | 33 out line(s) |
| stdlib_wave1.op | PASS | 15 out line(s) |
| stdlib_wave2.op | PASS | 16 out line(s) |
| strength_clamp_pin.op | PASS | 2 out line(s) |
| string_literals.op | PASS | 7 out line(s) |
| strings_pinned.op | PASS | 11 out line(s) |
| sweep_std_json_compact_pin.op | PASS | 4 out line(s) |
| sweep_std_unique_pin.op | PASS | 5 out line(s) |
| task_groups.op | PASS | 5 out line(s) |
| time.op | PASS | 12 out line(s) |
| traceback_chain.op | PASS | 5 out line(s) |
| traits.op | PASS | 7 out line(s) |
| try_family.op | PASS | 30 out line(s) |
| try_io.op | PASS | 31 out line(s) |
| try_numeric_std.op | PASS | 26 out line(s) |
| try_wave2.op | PASS | 48 out line(s) |
| type_aliases.op | PASS | 0 out line(s) |
| type_anns.op | PASS | 17 out line(s) |
| type_generics.op | PASS | 0 out line(s) |
| typed_wrappers.op | PASS | 27 out line(s) |
| unicode.op | PASS | 13 out line(s) |
| unicode_depth.op | PASS | 20 out line(s) |
| vis_lib.op | PASS | 0 out line(s) |
| visibility_default.op | PASS | 6 out line(s) |
| weak_refs.op | PASS | 15 out line(s) |
| z116_const_order.op | RC1-PIN | designed error path:   at main |
| z116_converge.op | PASS | 7 out line(s) |
| z125_continuation.op | PASS | 13 out line(s) |
| z125_parser_pin.op | PASS | 22 out line(s) |
| z132_oracle_fatal.op | RC1-PIN | designed error path:   at main |
| z132_oracle_parity.op | PASS | 9 out line(s) |
| z136_residual_pin.op | PASS | 20 out line(s) |
| z213_interp_stress.op | PASS | 11 out line(s) |
| z512_cap_parity_pin.op | PASS | 38 out line(s) |
| z_s0_parity.op | PASS | 13 out line(s) |
| z_s2_harden.op | PASS | 5 out line(s) |
| z_typedgate_semantics.op | PASS | 11 out line(s) |
