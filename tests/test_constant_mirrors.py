"""
Every constant the wallet MIRRORS must equal protocol.py — checked, not trusted.

WHY. Consensus constants exist once in protocol.py and are COPIED into static/interface.js, because the
browser miner has to compute the same PoSW anchor, epoch, finality window and bond arithmetic the node
does. The copies carry "MUST match protocol.py" comments and drift anyway — comments do not fail builds.

Two live instances in one week:
  * FINALITY_DEPTH sat at 12 in the wallet against 45 in protocol.py, putting the browser's RANDAO reveal
    window 33 blocks too late, so browser-signed reveals were rejected;
  * config.py wrote the literal auto_bond_percent 80 while protocol.AUTO_BOND_DEFAULT_PERCENT had been
    raised to 99 — a FRESH install compounded at a different rate than a config that merely lacked the
    key, with nothing visible from outside to say which you had.

A mismatch here is never a crash. It is a browser that computes a valid-looking proof against the wrong
anchor, or two nodes quietly behaving differently — the failures that cost the most to diagnose because
everything keeps running.

This also pins config.py to WRITE THE CONSTANT rather than a literal, which is what let the second one
drift: create_config bakes every default into the file at install time, so a literal there is frozen into
every node installed before someone notices.
"""
import os, re, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond: _fails.append(name)


def main():
    os.environ.setdefault("HOME", tempfile.mkdtemp())
    import protocol
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js = open(os.path.join(root, "static", "interface.js"), encoding="utf8").read()

    # plain integers the wallet declares under the SAME name as protocol.py
    SAME_NAME = ["POSW_T", "POSW_S", "POSW_K", "POSW_ANCHOR_OFFSET", "POSW_LEASE_EPOCHS",
                 "POSW_TARGET_MARGIN", "EPOCH_LENGTH", "FINALITY_DEPTH", "TX_TARGET_MARGIN",
                 "BOND_UNLOCK_DELAY", "FIDELITY_CAP"]
    # and the ones the wallet renames (raw-unit suffix / BigInt literal)
    RENAMED = {"B_MIN_RAW": "B_MIN", "BOND_CAP": "BOND_CAP", "MIN_TX_FEE": "MIN_TX_FEE"}

    seen = 0
    for name in SAME_NAME:
        m = re.search(r'\b%s\s*=\s*([0-9_]+)' % name, js)
        pv = getattr(protocol, name, None)
        check(f"the wallet declares {name}", m is not None, "not mirrored — did it move?")
        if not m or pv is None:
            continue
        seen += 1
        check(f"{name} matches protocol.py ({pv})", int(m.group(1).replace("_", "")) == pv,
              f"wallet={m.group(1)} protocol={pv}")

    for jsname, pyname in RENAMED.items():
        m = re.search(r'\b%s\s*=\s*([0-9_]+)n?' % jsname, js)
        pv = getattr(protocol, pyname, None)
        check(f"the wallet declares {jsname}", m is not None)
        if not m or pv is None:
            continue
        seen += 1
        check(f"{jsname} matches protocol.{pyname} ({pv})",
              int(m.group(1).replace("_", "")) == pv, f"wallet={m.group(1)} protocol={pv}")

    check("a meaningful number of constants was actually compared", seen >= 12,
          f"only {seen} — the extractor has rotted; fix the regex, not this assert")

    # config.py must not freeze a default as a literal: create_config bakes it into every install
    cfg = open(os.path.join(root, "config.py"), encoding="utf8").read()
    m = re.search(r'"auto_bond_percent"\s*:\s*([A-Za-z_0-9]+)', cfg)
    check("config.py writes the auto-bond CONSTANT, not a literal",
          bool(m) and not m.group(1).isdigit(),
          f'writes {m.group(1) if m else "?"} — a literal here freezes into every node installed before it is noticed')

    print()
    print("ALL CONSTANT-MIRROR CHECKS PASSED" if not _fails else f"{len(_fails)} FAILURE(S): {_fails}")
    return 1 if _fails else 0


if __name__ == "__main__":
    sys.exit(main())
