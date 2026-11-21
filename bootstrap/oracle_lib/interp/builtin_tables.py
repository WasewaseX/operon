"""operon oracle: interp.builtin_tables (split of bootstrap/oracle.py)."""




BUILTINS = set("""promote expr_on expr_off decay_clock ligand_set ligand secrete quorum quench quorum_state splice_shift promoter_telemetry burst_set len push pop insert remove keys values has del range str num type
abs min max sum clock exit assert codon distance similar transcribe reverse_complement
gc_content translate find_orf memory methyl methylate demethylate m6a_write m6a_erase passage grn_set grn_get fingerprint toggle_on toggle_state repressi_next
repressi_state repressi_start grn_fire grn_state spawn join floor ceil sqrt pow random
randomize chr ord now sleep argv read_file write_file append_file exists file_size read_dir run
cancel task_state cancelled wait_all wait_any
fs_delete fs_rename fs_mkdir re_replace
bytes_from_str str_from_bytes bytes_from_list bytes_to_list read_file_bytes write_file_bytes
http_get serve recv_request send_response json_parse json_str env call items py
re_match re_find re_groups unix_time date_parts date_fmt
grapheme_len fold_case char_at char_slice
norm_nfc norm_nfd casefold char_category weak strengthen
some none ok err is_some is_none is_ok is_err unwrap unwrap_or try_num try_index try_get try_pop
try_first try_last try_char_at try_env try_json_parse try_re_groups
try_read_file try_read_file_bytes try_read_dir try_run try_http_get try_str_from_bytes
enumerate zip sorted reversed any all first last take drop unique flatten chunk round clamp divmod
channel send recv close select
is_object object_fields object_from_map""".split())

BUILTIN_SYNONYMS = {"print": "promote", "echo": "promote", "say": "promote", "show": "promote"}
