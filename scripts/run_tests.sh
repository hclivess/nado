#!/usr/bin/env bash
# Run EVERY tests/test_*.py the way it must be run — isolated HOME (never the live node's data dir), testnet
# mode, Python STARK kernels allowed except for the two tests that certify the shipped native path — and fail
# on any non-zero exit or FAIL line. The suite is print-PASS/FAIL scripts, not pytest: `pytest tests/` collects
# three functions and goes green (2026-09-02 audit). Usage: scripts/run_tests.sh [pattern] (default: all).
#   NADO_TEST_TIMEOUT   per-test seconds (default 900; the fold/prove tests need minutes)
#   NADO_TEST_JOBS      parallel jobs (default 2; every job gets its own HOME)
set -u
cd "$(dirname "$0")/.."
PY=${PY:-nado_venv/bin/python}
PAT=${1:-'tests/test_*.py'}
TMO=${NADO_TEST_TIMEOUT:-900}
JOBS=${NADO_TEST_JOBS:-2}
OUT=$(mktemp -d /tmp/nado-tests.XXXXXX)
NATIVE_ONLY="test_fold_cache_persist"      # FATAL under NADO_ALLOW_PYTHON_KERNELS (certifies the shipped native path)
run_one() {
  t=$1; n=$(basename "$t" .py); h="$OUT/home-$n"; mkdir -p "$h"
  flags="NADO_ALLOW_PYTHON_KERNELS=1"; case " $NATIVE_ONLY " in *" $n "*) flags="";; esac
  env -i PATH="$PATH" HOME="$h" NADO_TESTNET=1 $flags timeout "$TMO" "$PY" "$t" > "$OUT/$n.log" 2>&1
  rc=$?; fails=$(grep -c '^FAIL' "$OUT/$n.log"); skips=$(grep -c '^SKIP' "$OUT/$n.log")
  st=OK; [ "$rc" = 124 ] && st=TIMEOUT; { [ "$rc" != 0 ] || [ "$fails" != 0 ]; } && [ "$st" = OK ] && st=FAIL
  printf "%-8s rc=%-3s fails=%-2s skips=%-2s %s\n" "$st" "$rc" "$fails" "$skips" "$n"
}
export -f run_one; export OUT PY TMO NATIVE_ONLY
ls $PAT | xargs -P "$JOBS" -I{} bash -c 'run_one {}' | tee "$OUT/summary.txt"
bad=$(grep -c -E '^(FAIL|TIMEOUT)' "$OUT/summary.txt")
echo "---- $(grep -c '^OK' "$OUT/summary.txt") ok, $bad failed/timed out; logs in $OUT"
[ "$bad" = 0 ]
