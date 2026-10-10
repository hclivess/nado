#!/usr/bin/env bash
# Run EVERY tests/test_*.py the way it must be run — isolated HOME (never the live node's data dir), testnet
# mode, Python STARK kernels allowed except for the two tests that certify the shipped native path — and fail
# on any non-zero exit or FAIL line. Runs the .mjs/.js wallet tests with node too, and SKIPS the LIVE tests. The suite is print-PASS/FAIL scripts, not pytest: `pytest tests/` collects
# three functions and goes green (2026-09-02 audit).
#
# Usage: scripts/run_tests.sh [--fast | --slow] [pattern]          (default: every test, both tiers)
#   --fast   only the tests whose last measured time is under 60 s (the ~440 that take ~30 CPU-min together)
#   --slow   only the rest (the ~60 proving tests that took 6.9 CPU-hours of the 7.4 on 2026-10-10)
#
# TIERS AND SCHEDULING (2026-10-10). The whole suite took 1 h 56 min wall: 444 tests under 60 s used 1,776 CPU-s and
# 62 tests used 24,699, and they started in alphabetical order, so the longest ones began whenever their letter came
# up and the run ended on a lone hour-long test. Now:
#   - every test's wall time is RECORDED after it runs, in $NADO_TEST_TIMES (default ~/.cache/nado-tests/times.tsv —
#     outside the checkout on purpose: a file the runner rewrites at a tracked path is a dirty tree the fleet's
#     fast-forward has to fight; a tracked build product at its generated path once stalled every node's update);
#   - a test never measured on this machine falls back to the hand-kept SLOW list below (measured seconds), and
#     a test on neither is assumed fast;
#   - tests start LONGEST FIRST, so the long ones overlap each other and the short ones fill the gaps;
#   - each test's timeout is 3x its last measured time, never under NADO_TEST_TIMEOUT. A test that TIMES OUT is
#     recorded at the timeout it hit, so the next run gives it 3x that instead of failing the same way again.
#
#   NADO_TEST_TIMEOUT   the per-test timeout FLOOR in seconds (default 900)
#   NADO_TEST_SLOW_TIMEOUT  optional: a floor for the slow tier only (CI's native job sets it)
#   NADO_TEST_TIMES     the measured-times file (see above)
#   PY_ORACLE           interpreter for tests that use `cryptography` as a TEST ORACLE (default python3). The node's
#                       venv deliberately has no such dependency (ops/tpm_aik.py), so those tests run where it exists.
#   NADO_TEST_JOBS      parallel jobs (default: half the CPUs; every job gets its own HOME)
#   NADO_TEST_EXCLUDE   a file of "<test name>  <reason>" lines (e.g. tests/ci_exclude.txt): each is listed as
#                       EXCLUDED with its reason — never silently dropped — and not run. CI uses it for the tests
#                       that need the Rust kernels or hours of proving; everything else runs on every push.
#
# SKIPS ARE REPORTED, NOT HIDDEN: a test that prints SKIP lines still counts as OK (a declared skip is not a failure),
# but the summary lists every such test with its SKIP lines, and every LIVE / EXCLUDED / other-tier test with why.
set -u
cd "$(dirname "$0")/.."
TIER=all
while [ $# -gt 0 ]; do
  case "$1" in
    --fast) TIER=fast; shift;;
    --slow) TIER=slow; shift;;
    --all) TIER=all; shift;;
    --) shift; break;;
    -h|--help) sed -n '2,36p' "$0"; exit 0;;
    -*) echo "run_tests.sh: unknown option $1 (--fast, --slow, or a pattern)" >&2; exit 2;;
    *) break;;
  esac
done
PY=${PY:-nado_venv/bin/python}
PY_ORACLE=${PY_ORACLE:-python3}
# .mjs/.js: the wallet/JS tests, run with node (the .js ones — CommonJS — matched no glob until 2026-10-10). The two
# named files are tests kept under their names because CI, the pre-push hook and CLAUDE.md call them by it
# (tests/test_every_file_in_tests_is_run_or_declared.py declares every non-test_* file in tests/ and why).
PAT=${1:-'tests/test_*.py tests/test_*.mjs tests/test_*.js tests/i18n_coverage.mjs tests/selftest_vectors_crosscheck.mjs'}
TMO=${NADO_TEST_TIMEOUT:-900}
STMO=${NADO_TEST_SLOW_TIMEOUT:-0}
NCPU=$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || echo 2)
JOBS=${NADO_TEST_JOBS:-$(( NCPU / 2 > 0 ? NCPU / 2 : 1 ))}
FAST_MAX=60
TIMES=${NADO_TEST_TIMES:-${XDG_CACHE_HOME:-${HOME:-/tmp}/.cache}/nado-tests/times.tsv}
OUT=$(mktemp -d /tmp/nado-tests.XXXXXX)
NATIVE_ONLY="test_fold_cache_persist"      # FATAL under NADO_ALLOW_PYTHON_KERNELS (certifies the shipped native path)
# THE SLOW LIST — the fallback when this machine has no measurement of a test (a fresh clone, CI, a new host): every
# test measured at 60 s or more, with its seconds. Measured 2026-10-10 (/tmp/nado-tests.Y1P3TF, 12 cores, 2 jobs)
# unless noted. Keep a test here when it is slow anywhere; a measurement on this machine always wins.
#   test_settle_fold_tree   proves a K=4 tree fold in Python: 2 h 28 min to ALL PASS on 2026-09-26 at load 60 (the
#                           worst seen, kept as its seed); 1,990 s on 2026-10-10.
#   test_settlement_proof   TIMED OUT at the old 900 s default on 2026-10-10 (it was never on this list).
#   test_recursive_verify_hetero 876 s and test_wide_pool_depth 748 s ran within a minute or three of that 900 s cap.
#   test_every_opcode_is_provable  3,546 s as 31 separate proofs; ~100 s since its cases are proven as one epoch.
SLOW="
test_settle_fold_tree 8880
test_joinsplit3_js_proof_verifies_in_python 1200
test_games_e2e 2087
test_shielded_wide 1799
test_fold_hardening 1393
test_settlement_proof 1800
test_recursive_verify_hetero 876
test_wide_pool_depth 748
test_recursive_row 605
test_assets 588
test_fri_verify 540
test_zkvm_args 502
test_recursive_verify 496
test_io_fingerprint 479
test_exec_commit_periodic 469
test_records_transition 417
test_stark_joinsplit2 408
test_shielded_state_replay 400
test_recursion_authdepth 360
test_records_bind 350
test_settle_multiblock_da 340
test_recursion 307
test_air_ir 293
test_io_bind_exec 271
test_bound_epoch_o1 262
test_settle_pre_contracts_exported 259
test_stark_joinsplit_circuit 242
test_settlement_sparse 239
test_native_prover_verifies 230
test_zkvm_circuit 221
test_nop_is_a_provable_step 214
test_recursion_ext 211
test_exec_root_v2 195
test_offchain_bulk_reuptake 185
test_settle_cid_io_binding 167
test_shielded_vault_e2e 161
test_m10_h7 150
test_zk_review_2026_09_24 148
test_review_round2 142
test_comp_verify 140
test_zkvm_epoch 136
test_state_merge 132
test_zkvm_arg_tag_from_one 131
test_hexholm_engine_conserves_resources 137
test_msg_ratchet 122
test_state_transition_batched 121
test_every_opcode_is_provable 120
test_asset_ops_settle_by_proof 115
test_da_shielded_transfer 110
test_starkprove 109
test_shielded_field 107
test_merkle_update 105
test_fork_resolution_pruned 105
test_rowcomp_verify 103
test_shielded_state_da 100
test_asset_settle_l1 92
test_native_reduce 91
test_shielded_state_seam 81
test_offchain_batch_canon 80
test_appnote_circuit 77
test_hexholm_contract_lifecycle 75
test_joinsplit2_js_proof_verifies_in_python 114
test_stormhold_engine_referee 73
test_fri_blowup2_parity 71
test_settle_proof_live_state_shape 66
test_zkvm_runtime 65
test_proof_query_full 63
"
# LIVE tests talk to the node this checkout runs (tests/test_tests_are_isolated.py keeps this list and the tree in
# step): test_otc_swap_e2e POSTS real transactions with the operator's keys. Never batched — run one by hand, knowingly.
LIVE="test_otc_swap_e2e"
run_one() {
  t=$1; tmo=$2; n=$(basename "$t"); n=${n%.py}; n=${n%.mjs}; n=${n%.js}; h="$OUT/home-$n"; mkdir -p "$h"
  case " $LIVE " in *" $n "*) printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s\n" "LIVE" "-" "-" "-" "$n (skipped: talks to the live node)"; return;; esac
  if [ -n "${NADO_TEST_EXCLUDE:-}" ]; then
    why=$(awk -v n="$n" '$1 == n { $1 = ""; sub(/^ +/, ""); print; exit }' "$NADO_TEST_EXCLUDE")
    if [ -n "$why" ]; then printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s\n" "EXCLUDED" "-" "-" "-" "$n ($why)"; return; fi
  fi
  run=("$PY" "$t"); case "$t" in *.mjs|*.js) run=(node "$t");; esac
  case "$t" in *.py)
    if grep -qE "^[[:space:]]*(from|import) cryptography" "$t" && ! "$PY" -c "import cryptography" 2>/dev/null \
       && "$PY_ORACLE" -c "import cryptography" 2>/dev/null; then run=("$PY_ORACLE" "$t"); fi;;
  esac
  flags="NADO_ALLOW_PYTHON_KERNELS=1"; case " $NATIVE_ONLY " in *" $n "*) flags="";; esac
  # TMPDIR=$h: every tempfile.mkdtemp() a test makes (105 sites beyond the HOME line, 2026-09-22) lands
  # under its own home instead of /tmp, so one rm of $OUT below is the whole cleanup. 8,000 unprefixed
  # tmpXXXXXXXX directories were found in /tmp that day, almost all from these tests.
  s0=$(date +%s)
  env -i PATH="$PATH" HOME="$h" TMPDIR="$h" NADO_TESTNET=1 $flags timeout "$tmo" "${run[@]}" > "$OUT/$n.log" 2>&1
  rc=$?; secs=$(( $(date +%s) - s0 ))
  fails=$(grep -c '^FAIL' "$OUT/$n.log"); skips=$(grep -c '^SKIP' "$OUT/$n.log")
  st=OK; [ "$rc" = 124 ] && st=TIMEOUT; { [ "$rc" != 0 ] || [ "$fails" != 0 ]; } && [ "$st" = OK ] && st=FAIL
  # a TIMEOUT is recorded at the timeout it hit (a lower bound), so the next run's 3x gives it room
  printf "%s\t%s\t%s\t%s\n" "$n" "$secs" "$st" "$s0" >> "$OUT/times.new"
  printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s %ss\n" "$st" "$rc" "$fails" "$skips" "$n" "$secs"
}
export -f run_one; export OUT PY PY_ORACLE NATIVE_ONLY LIVE NADO_TEST_EXCLUDE

# fold this run's measurements into the times file (the latest per test wins) — on ANY exit, so an interrupted run
# still teaches the next one
save_times() {
  [ -s "$OUT/times.new" ] || return 0
  mkdir -p "$(dirname "$TIMES")" 2>/dev/null || return 0
  { [ -f "$TIMES" ] && cat "$TIMES"; cat "$OUT/times.new"; } \
    | awk -F'\t' 'NF >= 2 { last[$1] = $0 } END { for (k in last) print last[k] }' | sort > "$TIMES.tmp.$$" \
    && mv "$TIMES.tmp.$$" "$TIMES"
}
trap save_times EXIT

# THE PLAN: "<estimate> <timeout> <tier> <source> <path>" per test, longest first
plan=$(
  { [ -f "$TIMES" ] && awk -F'\t' '{ print "M", $1, $2 }' "$TIMES"
    echo "$SLOW" | awk 'NF == 2 { print "S", $1, $2 }'
    ls $PAT 2>/dev/null | awk '{ print "T", $0 }'; } |
  awk -v tmo="$TMO" -v stmo="$STMO" -v fast="$FAST_MAX" '
    $1 == "M" { m[$2] = $3; next }
    $1 == "S" { s[$2] = $3; next }
    $1 == "T" { p = $2; n = p; sub(/.*\//, "", n); sub(/\.(py|mjs|js)$/, "", n)
                if (n in m) { e = m[n]; src = "measured" } else if (n in s) { e = s[n]; src = "slow-list" } else { e = 0; src = "unmeasured" }
                tier = (e >= fast) ? "slow" : "fast"
                t = 3 * e; if (t < tmo) t = tmo; if (tier == "slow" && t < stmo) t = stmo
                printf "%d %d %s %s %s\n", e, t, tier, src, p }' |
  sort -k1,1nr -k5,5)
[ -n "$plan" ] || { echo "run_tests.sh: no test matches: $PAT" >&2; exit 2; }
deferred=$(echo "$plan" | awk -v tier="$TIER" 'tier != "all" && $3 != tier')
torun=$(echo "$plan" | awk -v tier="$TIER" 'tier == "all" || $3 == tier')
echo "---- $(echo "$torun" | grep -c .) test(s), tier $TIER, $JOBS jobs, longest first; times: $TIMES"
[ -n "$torun" ] && echo "$torun" | awk '{ print $5, $2 }' | xargs -P "$JOBS" -n 2 bash -c 'run_one "$0" "$1"' | tee "$OUT/summary.txt"
touch "$OUT/summary.txt"

# ---- the report: skips with their reasons, then the verdict
if [ -n "$deferred" ]; then
  other=$([ "$TIER" = fast ] && echo slow || echo fast)
  echo "---- $(echo "$deferred" | grep -c .) test(s) in the $other tier not run (scripts/run_tests.sh --$other):"
  echo "$deferred" | awk '{ printf "  %-8s ~%ss (%s) %s\n", "DEFERRED", $1, $4, $5 }' | head -${NADO_TEST_LIST_MAX:-200}
fi
nskip=$(awk '$4 ~ /^skips=[1-9]/ || $1 == "LIVE" || $1 == "EXCLUDED"' "$OUT/summary.txt" | grep -c .)
if [ "$nskip" != 0 ]; then
  echo "---- $nskip test(s) skipped something (a declared skip is not a failure; each says why):"
  awk '$1 == "LIVE" || $1 == "EXCLUDED" { $2 = $3 = $4 = ""; print "  " $0 }' "$OUT/summary.txt" | tr -s ' '
  for n in $(awk '$4 ~ /^skips=[1-9]/ { print $5 ":" $1 }' "$OUT/summary.txt" | sort); do
    st=${n#*:}; n=${n%%:*}; echo "  $n ($st):"; grep '^SKIP' "$OUT/$n.log" | sort | uniq -c | sort -rn | head -10 | sed 's/^ */      /'
  done
fi
bad=$(grep -c -E '^(FAIL|TIMEOUT)' "$OUT/summary.txt")
# A GREEN RUN LEAVES NOTHING BEHIND: the homes, the temp dirs and the logs go together. A run with a
# failure keeps $OUT, because then the logs are the point.
if [ "$bad" = 0 ]; then
  save_times; trap - EXIT
  echo "---- $(grep -c '^OK' "$OUT/summary.txt") ok, 0 failed; all green, $OUT removed"
  rm -rf "$OUT"
  exit 0
fi
echo "---- failed or timed out:"; grep -E '^(FAIL|TIMEOUT)' "$OUT/summary.txt" | sed 's/^/  /'
echo "---- $(grep -c '^OK' "$OUT/summary.txt") ok, $bad failed/timed out; logs in $OUT"
exit 1
