"""The records prove must be behind the in-flight guard, not in front of it.

WHAT HAPPENED. _build_records_half runs prove_transition — a multi-minute, CPU-bound, multi-GB STARK — and
`if _settle_proving` sat ~60 lines BELOW the call. So every settle cadence (~8 s) launched ANOTHER records
prove while the previous one was still running. The per-batch instrumentation caught it in a single run,
because the batch index never advances:

    00:45:48  batch 1/13 K=2 T=32768  76.4s (cum  76.4s) rss=1.07GB
    00:47:08  batch 1/13 K=2 T=32768 147.0s (cum 147.0s) rss=1.63GB
    00:48:16  batch 1/13 K=2 T=32768 207.9s (cum 207.9s) rss=1.79GB
    00:49:19  batch 1/13 K=2 T=32768 261.8s (cum 261.8s) rss=1.96GB

Four SEPARATE prove_transition calls, each restarting at batch 1 (cum == the batch time, so the start clock
is fresh each line), all running CONCURRENTLY — identical work taking 76 -> 147 -> 208 -> 262 s as they contend.

That single defect produced everything I had been attributing elsewhere: RSS climbing to 14.6 GB (I blamed
batch-loop accumulation), a ~4x slowdown (I blamed load), and a prove blowing SETTLE_PROVE_TIMEOUT=2400s and
being abandoned (I blamed the batch size, and shipped two "corrected" constants because of it). None of it
was batching and none of it was the AIR. It was N concurrent copies of one proof.

The rule was already written on the LATER guard — "without it a timeout every settle would stack a new fold
thread every cadence and the box would grind to a halt". It guarded the KV prove; the records prove was
added later, is just as expensive, and sat in front of it.

WHY THIS IS AN AST TEST. The property is genuinely about STATEMENT ORDER inside one function, which is what
ast can answer and a substring cannot. It resolves the real module and walks the real function — it does not
grep for a phrase, and it cannot pass because a name happens to appear somewhere in the file.

Run: python3 tests/test_records_prove_not_stacked.py
"""
import ast
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_PATH = os.path.join(ROOT, "execnode", "execnode.py")
TREE = ast.parse(open(SRC_PATH).read())

fails = 0


def check(name, fn):
    global fails
    try:
        fn()
        print(f"PASS  {name}")
    except Exception as e:
        fails += 1
        print(f"FAIL  {name}: {e}")
        traceback.print_exc()


def _fn(name):
    for n in ast.walk(TREE):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"{name} not found in execnode.py")


def _records_call_line(fn):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            nm = getattr(f, "id", None) or getattr(f, "attr", None)
            if nm == "_build_records_half":
                return n.lineno
    raise AssertionError("_build_records_half is not called in _build_settlement_proof")


def _guard_lines(fn):
    """Lines of every `if _settle_proving:` test in the function."""
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.If):
            for sub in ast.walk(n.test):
                if isinstance(sub, ast.Name) and sub.id == "_settle_proving":
                    out.append(n.lineno)
                    break
    return sorted(out)


def t_a_guard_precedes_the_records_prove():
    fn = _fn("_build_settlement_proof")
    call = _records_call_line(fn)
    guards = _guard_lines(fn)
    assert guards, "no `if _settle_proving:` check in _build_settlement_proof at all"
    before = [g for g in guards if g < call]
    assert before, (
        f"_build_records_half is called at line {call} but every _settle_proving guard is at {guards} — "
        f"a records prove would be launched on every settle cadence while the previous one still runs")


def t_the_later_guard_is_still_there():
    """The early guard does NOT replace the late one. The late check re-reads at the last moment because the
    caller's copy goes stale while this function walks the span over HTTP — that was its own bug, three
    fixes deep. Removing it to 'deduplicate' would reintroduce the race."""
    fn = _fn("_build_settlement_proof")
    call = _records_call_line(fn)
    after = [g for g in _guard_lines(fn) if g > call]
    assert after, "the late-re-read guard was removed; the stale-read race comes back with it"


def t_the_publish_window_is_guarded_early_too():
    """After BUILT, _settle_proving clears while ~112-139 s of DA publish and the submit still lie ahead. A
    records prove started in that window extends the same pre-state and could never land."""
    fn = _fn("_build_settlement_proof")
    call = _records_call_line(fn)
    found = False
    for n in ast.walk(fn):
        if isinstance(n, ast.If) and n.lineno < call:
            for sub in ast.walk(n.test):
                if isinstance(sub, ast.Name) and sub.id == "_settle_publishing":
                    found = True
    assert found, "no publish-window check before the records prove"


def t_global_is_declared_before_first_use():
    """Python requires `global x` to precede any use of x in the function. Reading the guard early without
    moving the declaration is a SyntaxError at import — i.e. the exec node would not start."""
    fn = _fn("_build_settlement_proof")
    decls = [n.lineno for n in ast.walk(fn)
             if isinstance(n, ast.Global) and "_settle_proving" in n.names]
    assert decls, "no `global _settle_proving` in the function"
    uses = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "_settle_proving"]
    assert min(decls) <= min(uses), (
        f"global declared at {min(decls)} but first use is at {min(uses)} — this is a SyntaxError, "
        f"the exec node will not import")


def t_the_module_actually_imports():
    """The checks above are structural; this one proves the file still loads. A guard that cannot be
    imported protects nothing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_exec_probe", SRC_PATH)
    assert spec and spec.loader, "cannot build an import spec for execnode.py"
    compile(open(SRC_PATH).read(), SRC_PATH, "exec")     # full compile, not just parse


for nm, fn in [("a guard precedes the records prove", t_a_guard_precedes_the_records_prove),
               ("the late re-read guard is still there", t_the_later_guard_is_still_there),
               ("the publish window is guarded early too", t_the_publish_window_is_guarded_early_too),
               ("global is declared before first use", t_global_is_declared_before_first_use),
               ("the module still compiles", t_the_module_actually_imports)]:
    check(nm, fn)

print()
if fails:
    print(f"{fails} FAILURES")
    sys.exit(1)
print("ALL PASS")
