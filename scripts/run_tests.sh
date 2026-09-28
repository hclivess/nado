#!/usr/bin/env bash
# Run EVERY tests/test_*.py the way it must be run — isolated HOME (never the live node's data dir), testnet
# mode, Python STARK kernels allowed except for the two tests that certify the shipped native path — and fail
# on any non-zero exit or FAIL line. Runs the .mjs wallet tests with node too, and SKIPS the LIVE tests. The suite is print-PASS/FAIL scripts, not pytest: `pytest tests/` collects
# three functions and goes green (2026-09-02 audit). Usage: scripts/run_tests.sh [pattern] (default: all).
#   NADO_TEST_TIMEOUT   per-test seconds (default 900; the fold/prove tests need minutes)
#   NADO_TEST_SLOW_TIMEOUT  seconds for the SLOW list below (default 10800)
#   PY_ORACLE           interpreter for tests that use `cryptography` as a TEST ORACLE (default python3). The node's
#                       venv deliberately has no such dependency (ops/tpm_aik.py), so those tests run where it exists.
#   NADO_TEST_JOBS      parallel jobs (default 2; every job gets its own HOME)
set -u
cd "$(dirname "$0")/.."
PY=${PY:-nado_venv/bin/python}
PY_ORACLE=${PY_ORACLE:-python3}
PAT=${1:-'tests/test_*.py tests/test_*.mjs'}      # .mjs: the wallet/JS tests, run with node (they were never run here)
TMO=${NADO_TEST_TIMEOUT:-900}
JOBS=${NADO_TEST_JOBS:-2}
OUT=$(mktemp -d /tmp/nado-tests.XXXXXX)
NATIVE_ONLY="test_fold_cache_persist"      # FATAL under NADO_ALLOW_PYTHON_KERNELS (certifies the shipped native path)
# SLOW tests get their own ceiling: test_settle_fold_tree proves a K=4 tree fold in Python and needs well over an hour
# (measured 2026-09-26: 2 h 28 min to ALL PASS, so the 900 s default can only ever report it as a TIMEOUT).
# measured 2026-09-27 on this host: fold_hardening 25 min, games_e2e 27 min, shielded_wide 27 min, every_opcode_is_provable
# under 1 h — each a TIMEOUT under the 900 s default, each ALL PASS given the time.
# measured 2026-09-28: test_assets makes six real blake2b-backend proofs in Python (the native arena has no blake2b
# backend) — ~630 s CPU, 30 min wall at load 60.
SLOW="test_settle_fold_tree test_fold_hardening test_games_e2e test_shielded_wide test_every_opcode_is_provable test_assets"
STMO=${NADO_TEST_SLOW_TIMEOUT:-10800}
# LIVE tests talk to the node this checkout runs (tests/test_tests_are_isolated.py keeps this list and the tree in
# step): test_otc_swap_e2e POSTS real transactions with the operator's keys. Never batched — run one by hand, knowingly.
LIVE="test_otc_swap_e2e"
run_one() {
  t=$1; n=$(basename "$t"); n=${n%.py}; n=${n%.mjs}; h="$OUT/home-$n"; mkdir -p "$h"
  case " $LIVE " in *" $n "*) printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s\n" "LIVE" "-" "-" "-" "$n (skipped: talks to the live node)"; return;; esac
  run=("$PY" "$t"); case "$t" in *.mjs) run=(node "$t");; esac
  case "$t" in *.py)
    if grep -qE "^[[:space:]]*(from|import) cryptography" "$t" && ! "$PY" -c "import cryptography" 2>/dev/null \
       && "$PY_ORACLE" -c "import cryptography" 2>/dev/null; then run=("$PY_ORACLE" "$t"); fi;;
  esac
  flags="NADO_ALLOW_PYTHON_KERNELS=1"; case " $NATIVE_ONLY " in *" $n "*) flags="";; esac
  tmo=$TMO; case " $SLOW " in *" $n "*) tmo=$STMO;; esac
  # TMPDIR=$h: every tempfile.mkdtemp() a test makes (105 sites beyond the HOME line, 2026-09-22) lands
  # under its own home instead of /tmp, so one rm of $OUT below is the whole cleanup. 8,000 unprefixed
  # tmpXXXXXXXX directories were found in /tmp that day, almost all from these tests.
  env -i PATH="$PATH" HOME="$h" TMPDIR="$h" NADO_TESTNET=1 $flags timeout "$tmo" "${run[@]}" > "$OUT/$n.log" 2>&1
  rc=$?; fails=$(grep -c '^FAIL' "$OUT/$n.log"); skips=$(grep -c '^SKIP' "$OUT/$n.log")
  st=OK; [ "$rc" = 124 ] && st=TIMEOUT; { [ "$rc" != 0 ] || [ "$fails" != 0 ]; } && [ "$st" = OK ] && st=FAIL
  printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s\n" "$st" "$rc" "$fails" "$skips" "$n"
}
export -f run_one; export OUT PY PY_ORACLE TMO STMO SLOW NATIVE_ONLY LIVE
ls $PAT | xargs -P "$JOBS" -I{} bash -c 'run_one {}' | tee "$OUT/summary.txt"
bad=$(grep -c -E '^(FAIL|TIMEOUT)' "$OUT/summary.txt")
# A GREEN RUN LEAVES NOTHING BEHIND: the homes, the temp dirs and the logs go together. A run with a
# failure keeps $OUT, because then the logs are the point.
if [ "$bad" = 0 ]; then
  echo "---- $(grep -c '^OK' "$OUT/summary.txt") ok, 0 failed; all green, $OUT removed"
  rm -rf "$OUT"
  exit 0
fi
echo "---- $(grep -c '^OK' "$OUT/summary.txt") ok, $bad failed/timed out; logs in $OUT"
exit 1
