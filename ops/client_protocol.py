"""Render protocol.CLIENT_EXPORTS for browser clients: GET /protocol.js and GET /protocol.json (nado.py).

WHY THIS EXISTS. Consensus constants lived once in protocol.py and were COPIED by hand into static/interface.js,
static/nadodapp.js, a dozen game clients and website/emission.html. The copies drifted (FINALITY_DEPTH 12 vs 45,
TX_INCLUSION_DELAY 2 vs 8, the auto-bond default 80 vs 99) and nothing failed when they did. Now the relay serves the
values from the module it runs, and the clients import them.

RENDERED IN MEMORY, never written to the tree: a tracked build product at its generated path once bricked the fleet's
fast-forward update (an untracked file where the tip tracked one). The render is a pure function of the imported module,
so it is computed once per process; protocol.py only changes with a commit, which restarts the node.

TYPES. int / str / bool, and lists / tuples / dicts of them. Floats are refused (no floats near consensus; a client that
needs a ratio gets the integer basis points). JavaScript numbers are exact only to 2^53 - 1, so a larger integer is
emitted as a BigInt literal (`123n`) in the module and as a decimal STRING in the JSON — documented here because the
two forms differ; no exported name is that large today and tests/test_constant_mirrors.py pins the rendering.

Imports nothing but protocol (stdlib + hashing): safe to import from a test or a tool without touching any database.
"""
import hashlib
import json

import protocol

MAX_SAFE_INTEGER = 2 ** 53 - 1


def _check(name, v):
    if isinstance(v, bool) or isinstance(v, str):
        return
    if isinstance(v, int):
        return
    if isinstance(v, (list, tuple)):
        for x in v:
            _check(name, x)
        return
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                raise TypeError(f"protocol.{name}: dict key {k!r} is not a string")
            _check(name, x)
        return
    raise TypeError(f"protocol.{name}: {type(v).__name__} cannot be exported to a client (int/str/bool/list/dict only)")


def _js(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return f"{v}n" if abs(v) > MAX_SAFE_INTEGER else str(v)
    if isinstance(v, str):
        return json.dumps(v)                       # ensure_ascii: a valid JS string literal
    if isinstance(v, (list, tuple)):
        return "Object.freeze([" + ", ".join(_js(x) for x in v) + "])"
    return "Object.freeze({" + ", ".join(json.dumps(k) + ": " + _js(v[k]) for k in sorted(v)) + "})"


def _jsonable(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return str(v) if abs(v) > MAX_SAFE_INTEGER else v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {k: _jsonable(v[k]) for k in sorted(v)}
    return v


def exported_values():
    """[(name, value)] in CLIENT_EXPORTS order. Raises on a missing name or an unexportable type, so a bad entry
    fails the first render (and the test) rather than serving a module with a hole in it."""
    out = []
    for name in protocol.CLIENT_EXPORTS:
        if not hasattr(protocol, name):
            raise AttributeError(f"protocol.CLIENT_EXPORTS names {name}, which protocol.py does not define")
        v = getattr(protocol, name)
        _check(name, v)
        out.append((name, v))
    return out


def render_js():
    lines = ["// NADO protocol constants, rendered by the relay from its own protocol.py (ops/client_protocol.py).",
             "// Do not copy these into a client: import them. Integers above 2^53 - 1 are BigInt literals."]
    lines += [f"export const {n} = {_js(v)};" for n, v in exported_values()]
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_json():
    return json.dumps({n: _jsonable(v) for n, v in exported_values()}, separators=(",", ":")).encode("utf-8")


_cache = {}


def rendered():
    """(js_bytes, json_bytes, version) — memoised for the process. `version` is a hash of the JS body: the ?v= stamp
    the relay writes into every `import ... from "/protocol.js"` it serves, and the ETag of both responses."""
    if "v" not in _cache:
        js, js_on = render_js(), render_json()
        _cache["v"] = (js, js_on, hashlib.blake2b(js, digest_size=8).hexdigest())
    return _cache["v"]

