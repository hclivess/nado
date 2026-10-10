"""
Browser clients IMPORT the protocol constants from the relay's /protocol.js — they never carry a copy.

WHY. Consensus constants exist once in protocol.py, and the browser has to compute the same PoSW anchor, epoch, finality
window and bond arithmetic the node does. They used to be COPIED into static/interface.js, static/nadodapp.js, the game
clients and website/emission.html under "MUST match protocol.py" comments, and the copies drifted anyway:
  * FINALITY_DEPTH sat at 12 in the wallet against 45 in protocol.py, putting the browser's RANDAO reveal window 33
    blocks too late, so browser-signed reveals were rejected;
  * TX_INCLUSION_DELAY sat at 2 against 8, so a send looked like an intermittent network fault;
  * the wallet's AUTO_BOND_DEFAULT_PCT sat at 80 against protocol.AUTO_BOND_DEFAULT_PERCENT 99 — found by this test's
    rewrite on 2026-10-10, after the 17-constant pin list had missed it for weeks because it only pinned the names
    someone remembered to add.
Now protocol.CLIENT_EXPORTS names what a client needs, nado.py serves it as GET /protocol.js and /protocol.json
(ops/client_protocol.py, rendered in memory from the imported module), and the clients import it. This test:
  (a) renders the module from protocol.py and evaluates it in Node: every CLIENT_EXPORTS name is exported with exactly
      protocol.py's value (BigInt above 2^53, as documented), and the JSON carries the same values;
  (b) refuses any CLIENT_EXPORTS name — or a known renamed alias of one — declared as a LITERAL anywhere under static/
      or website/, and requires the wallet and the dApp SDK to import /protocol.js — except the four address constants
      static/nadotx.js keeps (it runs in plain Node with no relay), which it pins by VALUE instead;
  (c) checks nado.py routes both URLs to the renderer and stamps `from "/protocol.js"` imports with the body hash.
It also keeps the config.py pin: create_config bakes defaults into every install, so a literal there freezes.
"""
import os, re, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_fails = []
def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (("  — " + detail) if detail and not cond else ""))
    if not cond: _fails.append(name)


# Client-side names that hold a CLIENT_EXPORTS value under another spelling. A literal under one of these is the same
# drift as a literal under the protocol name, so the guard refuses both.
ALIASES = {
    "ADDR_PREFIX": "ADDRESS_PREFIX", "ADDR_BODY": "ADDRESS_BODY", "ADDR_CK": "ADDRESS_CHECKSUM",
    "B_MIN_RAW": "B_MIN", "BASE_SUBSIDY_RAW": "BASE_SUBSIDY", "AUTO_BOND_DEFAULT_PCT": "AUTO_BOND_DEFAULT_PERCENT",
    "BLOCK_SECS": "BLOCK_TIME", "INVITE_BLOCKS_PER_DAY": "BLOCK_TIME", "RAW": "DENOMINATION",
}
# THE ONE PINNED EXEMPTION: static/nadotx.js is the environment-free crypto SDK the game engines load in plain Node (no
# relay to import from), so it keeps the address-format constants — and this test pins each one's VALUE instead.
PINNED = {"static/nadotx.js": {"ADDR_PREFIX": "ADDRESS_PREFIX", "DOMAIN_ADDRESS_V2": "DOMAIN_ADDRESS_V2",
                               "ADDR_CK": "ADDRESS_CHECKSUM", "ADDR_BODY": "ADDRESS_BODY"}}
# a declaration (const/let/var, or a later name in a comma list) whose WHOLE value is a number, BigInt, string or array
# literal — `86400 / P.BLOCK_TIME` is derived, not copied, so the literal must end the expression
LITERAL = r'(?:(?:-?[0-9][0-9_.]*n?|10n\s*\*\*\s*10n|"[^"\n]*"|\'[^\'\n]*\')(?=\s*(?:[;,)\n]|//|/\*))|\[)'


def main():
    os.environ["HOME"] = tempfile.mkdtemp()
    import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)   # leave no /tmp home behind (9,600 leaked by 2026-09-22)
    import json
    import protocol
    from ops import client_protocol as cp
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    names = list(protocol.CLIENT_EXPORTS)

    # ---- (a) the rendered module carries protocol.py's values ------------------------------------------------------
    check("CLIENT_EXPORTS names no constant twice", len(names) == len(set(names)))
    check("CLIENT_EXPORTS is not trivially small", len(names) >= 30, f"{len(names)} names")
    js, js_on, ver = cp.rendered()
    check("the module has one `export const` per CLIENT_EXPORTS name",
          re.findall(r"^export const ([A-Z_0-9]+) = ", js.decode(), re.M) == names)
    check("the version stamp is a hash of the module body", re.fullmatch(r"[0-9a-f]{16}", ver) is not None)
    probe = ("const m = await import('data:text/javascript;base64,' + process.argv[1]);"
             "const enc = (v) => typeof v === 'bigint' ? {big: v.toString()} : Array.isArray(v) ? v.map(enc)"
             "  : (v && typeof v === 'object') ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, enc(x)])) : v;"
             "const out = {}; for (const k of Object.keys(m)) out[k] = enc(m[k]);"
             "out.__frozen = Object.isFrozen(m.BOND_ELASTIC_MULT_BPS); console.log(JSON.stringify(out));")
    import base64
    r = subprocess.run(["node", "--input-type=module", "-e", probe, base64.b64encode(js).decode()],
                       capture_output=True, text=True, timeout=60)
    check("Node evaluates the rendered /protocol.js", r.returncode == 0, r.stderr[-400:])
    got = json.loads(r.stdout) if r.returncode == 0 else {}
    want = lambda v: ({"big": str(v)} if isinstance(v, int) and not isinstance(v, bool) and abs(v) > cp.MAX_SAFE_INTEGER
                      else [want(x) for x in v] if isinstance(v, (list, tuple))
                      else {k: want(x) for k, x in v.items()} if isinstance(v, dict) else v)
    for n in names:
        pv = getattr(protocol, n)
        check(f"/protocol.js {n} == protocol.{n}", got.get(n) == want(pv), f"js={got.get(n)!r:.80} protocol={pv!r:.80}")
    check("array constants are frozen in the module (a client cannot edit the table)", got.get("__frozen") is True)
    jd = json.loads(js_on)
    check("/protocol.json carries the same names, in order", list(jd) == names)
    check("/protocol.json carries the same values",
          all(jd[n] == (list(getattr(protocol, n)) if isinstance(getattr(protocol, n), tuple) else getattr(protocol, n))
              for n in names))
    # the documented BigInt rule and the float refusal, on synthetic values (no exported name is that large today)
    check("an integer above 2^53 - 1 renders as a BigInt literal in JS", cp._js(2 ** 60) == "1152921504606846976n")
    check("an integer above 2^53 - 1 renders as a decimal string in JSON", cp._jsonable(2 ** 60) == "1152921504606846976")
    check("2^53 - 1 itself stays a plain number", cp._js(2 ** 53 - 1) == str(2 ** 53 - 1))
    try:
        cp._check("X", 0.5); refused = False
    except TypeError:
        refused = True
    check("a float is refused (no floats near consensus)", refused)

    # the Node test hook serves the same body the relay does (it is how every JS test gets the constants)
    hook = ("import { PROTOCOL_JS } from " + json.dumps(os.path.join(root, "tests", "protocol_hook.mjs")) + ";"
            "process.stdout.write(PROTOCOL_JS);")
    r = subprocess.run(["node", "--input-type=module", "-e", hook], capture_output=True, text=True, timeout=60)
    check("tests/protocol_hook.mjs serves exactly the relay's rendering", r.returncode == 0 and r.stdout == js.decode(),
          r.stderr[-300:])

    # ---- (b) no client declares one of these as a literal --------------------------------------------------------
    guarded = names + list(ALIASES)
    decl = re.compile(r'(?:\b(?:const|let|var)\s+|,\s*)(%s)\s*=\s*%s' % ("|".join(map(re.escape, guarded)), LITERAL))
    offenders, scanned = [], 0
    for base in ("static", "website"):
        for dp, _dirs, files in os.walk(os.path.join(root, base)):
            for f in files:
                if not f.endswith((".js", ".mjs", ".html")) or f == "i18n.js":
                    continue
                p = os.path.join(dp, f)
                src = open(p, encoding="utf8", errors="replace").read()
                scanned += 1
                rel = os.path.relpath(p, root)
                for m in decl.finditer(src):
                    if m.group(1) in PINNED.get(rel, {}):
                        continue
                    line = src.count("\n", 0, m.start()) + 1
                    offenders.append(f"{rel}:{line} {m.group(1)}")
    check("the literal guard scanned the client tree", scanned >= 100, f"only {scanned} files")
    check("no CLIENT_EXPORTS name (or alias) is declared as a literal in static/ or website/", not offenders,
          "; ".join(offenders[:12]))
    for rel, pins in PINNED.items():
        src = open(os.path.join(root, rel), encoding="utf8").read()
        for jsname, pyname in pins.items():
            m = re.search(r'(?:const|let|var)\s+%s\s*=\s*("[^"]*"|[0-9]+)' % jsname, src)
            got = None if not m else (json.loads(m.group(1)) if m.group(1).startswith('"') else int(m.group(1)))
            check(f"{rel} pins {jsname} == protocol.{pyname} ({getattr(protocol, pyname)!r})",
                  got == getattr(protocol, pyname), f"found {got!r}")
    for f in ("static/interface.js", "static/nadodapp.js"):
        src = open(os.path.join(root, f), encoding="utf8").read()
        check(f"{f} imports its constants from /protocol.js", re.search(r'from\s*"/protocol\.js"', src) is not None)
    used = "\n".join(open(os.path.join(dp, f), encoding="utf8", errors="replace").read()
                     for base in ("static", "website") for dp, _d, fs in os.walk(os.path.join(root, base))
                     for f in fs if f.endswith((".js", ".html")) and f != "i18n.js")
    unused = [n for n in names if not re.search(r"\b%s\b" % n, used)]
    check("every CLIENT_EXPORTS name is used by some client (no dead exports)", not unused, str(unused))

    # ---- (c) nado.py serves it ---------------------------------------------------------------------------------
    nsrc = open(os.path.join(root, "nado.py"), encoding="utf8").read()
    check("nado.py routes GET /protocol.js", 'web.get("/protocol.js", protocol_js)' in nsrc)
    check("nado.py routes GET /protocol.json", 'web.get("/protocol.json", protocol_json)' in nsrc)
    check("both handlers render through ops.client_protocol (one renderer, in memory)",
          nsrc.count("from ops.client_protocol import rendered") >= 3)
    check("served .js has its /protocol.js import stamped",
          "_stamp_protocol_import(_stamp_js_imports(raw))" in nsrc)
    m = re.search(r"^_PROTOCOL_IMPORT_RE = (re\.compile\(.*\))$", nsrc, re.M)
    check("the stamp pattern is found in nado.py", m is not None)
    if m:
        rx = eval(m.group(1), {"re": re})
        stamp = lambda b: rx.sub(lambda mm: mm.group(1) + b"/protocol.js?v=" + ver.encode() + mm.group(2), b)
        for src_ in (b'import * as P from "/protocol.js";', b"import { A } from '/protocol.js?v=old';",
                     b'const P = await import("/protocol.js");'):
            check(f"stamps {src_.decode()!r}", b"/protocol.js?v=" + ver.encode() in stamp(src_))
        check("leaves a relative ./protocol.js alone", stamp(b'from "./protocol.js"') == b'from "./protocol.js"')

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
