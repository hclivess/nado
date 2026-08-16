#!/usr/bin/env bash
# Build EVERY required native crate — the same set a node rebuilds for itself on update.
#
# WHY THIS EXISTS. A node is fine without it: ops/self_update.py rebuilds missing or stale crates as part
# of advancing, so the fleet self-heals. A CHECKOUT is not. The only build script was
# scripts/build_pq_native.sh, which builds one crate (mldsa44) — yet every NativeMissing message, for any
# of the five, points the reader at it. So a fresh clone hits "native crate 'starkprove' is REQUIRED",
# follows the instruction it is given, and is still missing four libraries with no further hint.
#
# THE CRATE LIST IS READ FROM ops/self_update.py, not restated here. That module already owns it, a node
# already acts on it, and a second copy is a second thing to drift — which is a mistake this tree has
# made more than once (a bound that lived in two modules, a constant copied from a docstring). Add a crate
# there and this builds it with no edit.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
mapfile -t CRATES < <("$PY" - <<'EOF'
import re
src = open("ops/self_update.py", encoding="utf8").read()
m = re.search(r"_CRATES\s*=\s*\(([^)]*)\)", src)
if not m:
    raise SystemExit("could not read _CRATES from ops/self_update.py — has it been renamed?")
print("\n".join(re.findall(r'"([^"]+)"', m.group(1))))
EOF
)

[ "${#CRATES[@]}" -gt 0 ] || { echo "no crates found in ops/self_update.py" >&2; exit 1; }
echo "building ${#CRATES[@]} native crate(s), as listed in ops/self_update.py"

for crate in "${CRATES[@]}"; do
    if [ ! -d "$crate" ]; then
        echo "  SKIP $crate (not present in this checkout)"
        continue
    fi
    printf '  %-22s ' "$crate"
    if [ "$crate" = "native/mldsa44" ]; then
        # DELEGATE, do not reimplement. mldsa44's loader wants the library at the CRATE ROOT, not in
        # target/release, and build_pq_native.sh is what knows that. Copying the copy step here is how the
        # two would drift — and this script existing at all is the result of one such gap. Found by
        # building in a clean checkout and watching every ML-DSA test still fail after a "successful" build.
        sh scripts/build_pq_native.sh >/dev/null 2>&1 && echo "ok (via build_pq_native.sh)" \
            || { echo "FAILED"; exit 1; }
    else
        (cd "$crate" && cargo build --release >/dev/null 2>&1) && echo "ok" || { echo "FAILED"; exit 1; }
    fi
done

# VERIFY, DO NOT ASSUME — cargo can exit 0 and leave the artifact untouched, which is the same check
# self_update makes after rebuilding rather than trusting the exit code.
missing=0
for crate in "${CRATES[@]}"; do
    [ -d "$crate" ] || continue
    if ! ls "$crate"/target/release/*.so >/dev/null 2>&1; then
        echo "  no shared library produced for $crate" >&2
        missing=1
    fi
done
# mldsa44 is loaded from the CRATE ROOT, so target/release existing is not enough to say it is usable.
if [ -d native/mldsa44 ] && [ ! -f native/mldsa44/libnado_mldsa44.so ]; then
    echo "  native/mldsa44 built but libnado_mldsa44.so is not at the crate root — the loader looks there" >&2
    missing=1
fi
[ "$missing" -eq 0 ] || exit 1
echo "done — every listed crate has a shared library"
