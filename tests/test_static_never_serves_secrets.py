"""The node never serves key material out of static/, whatever put it there (nado.py _static_secret).

FOUND LIVE 2026-09-27: the TPM enrolment helper writes its signing identity (a private key) as nado-identity.json beside
itself, and a run from static/ on 2026-09-11 left one there. /static/ served it with HTTP 200 on every public host for 16
days. Pins: a key-material name, a dotfile, or a file its owner made unreadable to others is refused (404, never 403);
the helpers and every ordinary asset are still served; and static_handler checks before serving anything.

The function is lifted from nado.py's source: importing nado.py opens the node's database.
Run: python3 tests/test_static_never_serves_secrets.py
"""
import ast, os, re, stat, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(os.path.join(ROOT, "nado.py")).read()
fails = 0


def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f"  {detail}"))
    fails += 0 if ok else 1


tree = ast.parse(SRC)
wanted = {"_STATIC_SECRET_NAMES", "_static_secret"}
parts = [ast.get_source_segment(SRC, n) for n in tree.body
         if (isinstance(n, ast.Assign) and any(getattr(t, "id", None) in wanted for t in n.targets))
         or (isinstance(n, ast.FunctionDef) and n.name in wanted)]
check("the refusal and its name list are found in nado.py", len(parts) == 2, len(parts))
ns = {"re": re, "os": os}
exec("\n\n".join(parts), ns)
secret = ns["_static_secret"]

d = tempfile.mkdtemp(prefix="nado-static-")
def mk(name, mode):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write("x")
    os.chmod(p, mode)
    return p

check("the helper's identity file, as it was found (0600), is refused", secret(mk("nado-identity.json", 0o600)))
check("...and refused by NAME even if someone makes it world-readable", secret(mk("nado-identity.json", 0o644)))
check("a node key file is refused", secret(mk("keys.dat", 0o644)))
check("PEM/key material is refused", secret(mk("server.pem", 0o644)) and secret(mk("tls.key", 0o644)))
check("a dotfile is refused", secret(mk(".env", 0o644)))
check("any file its owner made unreadable to others is refused", secret(mk("notes.txt", 0o600)))
check("an ordinary asset is served", not secret(mk("interface.js", 0o644)))
check("a downloadable helper (0755) is served", not secret(mk("nado-tpm-enrol.exe", 0o755)))
check("a file that vanished is refused, not raised", secret(os.path.join(d, "gone.bin")))

# the handler must ask BEFORE serving anything (html, js or a plain file), and answer 404 like a missing file
body = next(ast.get_source_segment(SRC, n) for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "static_handler")
i_chk = body.find("_static_secret(full)")
first_serve = min(i for i in (body.find("_html_response("), body.find("_static_cached("), body.find("FileResponse(")) if i >= 0)
check("static_handler refuses before its first serving call", 0 < i_chk < first_serve, (i_chk, first_serve))
check("...with a 404, never a 403 that would confirm the secret exists",
      re.search(r"_static_secret\(full\):[^\n]*\n\s*return web\.Response\(status=404", body) is not None)

print("ALL PASS — no key material is served from static/" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
