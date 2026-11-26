#!/usr/bin/env python3
"""tools/actor.py — the NADO actor standard's tool: validate a manifest, build the standard command line, run it, pin it.

The standard is doc/actors.md; the manifest's shape is actors/schema.json, READ HERE — the schema keywords it uses are
interpreted below (no third-party validator), so the shape a manifest is checked against is the published one and the two
cannot drift. On top of the shape, the rules a schema cannot state: the entry's hash, that every flag, variable and command
the manifest promises is in the entry's source, the key rule (an actor anyone may run never uses a node wallet), defaults
that fit their types, and the safety arm.

  python3 tools/actor.py validate actors/<id>/actor.json [...]     # exit 1 and every problem, or "ok"
  python3 tools/actor.py cmd  actors/<id>/actor.json <command> [name=value ...]   # the standard command line, as JSON
  python3 tools/actor.py run  actors/<id>/actor.json <command> [name=value ...]   # …and execute it (in the repository)
  python3 tools/actor.py pin  actors/<id>/actor.json               # record the entry's current SHA-256 (a deliberate change)

Stdlib only.
"""
import hashlib
import json
import os
import re
import subprocess  # nosec B404 # runs the actor's own entry, as the user asked (cmd builds an argv, never a shell string)
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(ROOT, "actors", "schema.json")
INTERP = {"python3": "python3", "node": "node"}


# ---- the schema's keywords, as actors/schema.json uses them --------------------------------------------------------------
def _type_ok(v, t):
    return {"object": isinstance(v, dict), "array": isinstance(v, list), "string": isinstance(v, str),
            "boolean": isinstance(v, bool), "integer": isinstance(v, int) and not isinstance(v, bool),
            "number": isinstance(v, (int, float)) and not isinstance(v, bool)}[t]


def check_schema(v, s, root, path="$"):
    """Every way `v` fails schema `s` (the subset of JSON Schema 2020-12 actors/schema.json uses), as messages."""
    if "$ref" in s:
        node = root
        for part in s["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return check_schema(v, node, root, path)
    errs = []
    if "const" in s and v != s["const"]:
        errs.append(f"{path}: must be {s['const']!r}")
    if "enum" in s and v not in s["enum"]:
        errs.append(f"{path}: {v!r} is not one of {s['enum']}")
    if "type" in s and not _type_ok(v, s["type"]):
        return errs + [f"{path}: must be {s['type']}"]
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            errs.append(f"{path}: {v!r} does not match {s['pattern']}")
        if "minLength" in s and len(v) < s["minLength"]:
            errs.append(f"{path}: shorter than {s['minLength']}")
        if "maxLength" in s and len(v) > s["maxLength"]:
            errs.append(f"{path}: longer than {s['maxLength']}")
    if isinstance(v, list):
        if "minItems" in s and len(v) < s["minItems"]:
            errs.append(f"{path}: fewer than {s['minItems']} items")
        if "items" in s:
            for i, x in enumerate(v):
                errs += check_schema(x, s["items"], root, f"{path}[{i}]")
    if isinstance(v, dict):
        for k in s.get("required", []):
            if k not in v:
                errs.append(f"{path}: missing {k!r}")
        if "minProperties" in s and len(v) < s["minProperties"]:
            errs.append(f"{path}: needs at least {s['minProperties']} entries")
        props = s.get("properties", {})
        for k, x in v.items():
            if "propertyNames" in s:
                errs += check_schema(k, s["propertyNames"], root, f"{path} key {k!r}")
            if k in props:
                errs += check_schema(x, props[k], root, f"{path}.{k}")
            elif s.get("additionalProperties") is False:
                errs.append(f"{path}: unknown field {k!r}")
            elif isinstance(s.get("additionalProperties"), dict):
                errs += check_schema(x, s["additionalProperties"], root, f"{path}.{k}")
    if "oneOf" in s:
        n = sum(1 for alt in s["oneOf"] if not check_schema(v, alt, root, path))
        if n != 1:
            errs.append(f"{path}: must match exactly one of {len(s['oneOf'])} alternatives ({n} matched)")
    return errs


# ---- the standard's own rules ----------------------------------------------------------------------------------------------
def sha256_of(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def validate(manifest_path, root=ROOT):
    """Every problem with the manifest at `manifest_path` (an empty list: it is valid)."""
    try:
        m = json.load(open(manifest_path))
    except (OSError, ValueError) as e:
        return [f"cannot read the manifest: {e}"]
    schema = json.load(open(SCHEMA_PATH))
    errs = check_schema(m, schema, schema)
    if errs:
        return errs                                   # the rules below read fields the shape guarantees
    d = os.path.basename(os.path.dirname(os.path.abspath(manifest_path)))
    if d != m["id"]:
        errs.append(f"the manifest's directory is {d!r}, its id {m['id']!r} — they must be the same")
    entry = os.path.join(root, m["runtime"]["entry"])
    if m["source"]["path"] != m["runtime"]["entry"]:
        errs.append("source.path must be runtime.entry")
    if not os.path.isfile(entry):
        return errs + [f"the entry {m['runtime']['entry']} does not exist"]
    if sha256_of(entry) != m["source"]["sha256"]:
        errs.append(f"the entry's SHA-256 is {sha256_of(entry)}, the manifest pins {m['source']['sha256']} — a changed "
                    "actor is a new version: move `version` and run `tools/actor.py pin`")
    code = open(entry, encoding="utf-8").read()
    # THE KEY RULE (doc/actors.md rule 1; CLAUDE.md §8): an actor anyone may run acts as its own identity
    if m["audience"] == "anyone" and m["identity"]["kind"] == "node-wallet":
        errs.append("an actor anyone may run never uses a node wallet: identity.kind must be own-key or none")
    transacts = False
    groups = [("(global)", {"inputs": m.get("inputs") or {}, "effects": {"transactions": False}})] + list(m["commands"].items())
    for cname, c in groups:
        if cname not in ("run", "(global)") and f'"{cname}"' not in code and f"'{cname}'" not in code:
            errs.append(f"command {cname!r} is not in {m['runtime']['entry']}")
        eff = c["effects"]
        if eff["transactions"]:
            transacts = True
            if not (eff.get("contracts") or eff.get("l1")):
                errs.append(f"command {cname!r} transacts but names no contract or L1 recipient")
            if not eff.get("spends"):
                errs.append(f"command {cname!r} transacts but does not say what it may spend")
            if m["identity"]["kind"] == "none":
                errs.append(f"command {cname!r} transacts, so the actor needs an identity (own-key)")
        for iname, i in (c.get("inputs") or {}).items():
            where = f"{cname}.{iname}"
            name = i.get("cli") or i.get("env")
            if f'"{name}"' not in code and f"'{name}'" not in code:
                errs.append(f"input {where}: {name} is not in {m['runtime']['entry']} — the code must take what the manifest promises")
            if i.get("required") and "default" in i:
                errs.append(f"input {where}: a required input has no default")
            if "default" in i and not _type_ok(i["default"], i["type"]):
                errs.append(f"input {where}: default {i['default']!r} is not a {i['type']}")
            if "enum" in i and "default" in i and i["default"] not in i["enum"]:
                errs.append(f"input {where}: default {i['default']!r} is not in its enum")
    if transacts:
        sf = m.get("safety")
        if sf is None:
            errs.append("an actor that transacts declares `safety`")
        elif sf["dry_run_by_default"]:
            arm = sf.get("arm")
            if not arm or not any(arm in (c.get("inputs") or {}) for c in m["commands"].values()):
                errs.append(f"safety.arm {arm!r} names no input — a dry-run actor must say what arms it")
    lp = m["lifecycle"].get("loop_input")
    if lp and not any(lp in (c.get("inputs") or {}) for c in m["commands"].values()):
        errs.append(f"lifecycle.loop_input {lp!r} names no input")
    return errs


def _coerce(v, t, name):
    if t == "boolean":
        if isinstance(v, bool):
            return v
        if str(v).lower() in ("1", "true", "yes", "on"):
            return True
        if str(v).lower() in ("0", "false", "no", "off"):
            return False
        raise ValueError(f"{name}: {v!r} is not a boolean")
    if t == "integer":
        return int(v)
    if t == "number":
        return float(v)
    return str(v)


def command_line(m, command, values):
    """(argv, env) — the STANDARD invocation of `command` with `values` (name -> value): the interpreter, the entry, the
    command (unless it is `run`), each input as its flag (a true boolean as the bare flag, a false one left out), and the
    `env` inputs as environment. Raises ValueError on an unknown command or input, a missing required one, or a bad value."""
    if command not in m["commands"]:
        raise ValueError(f"no command {command!r} (has: {', '.join(m['commands'])})")
    glob, spec = m.get("inputs") or {}, m["commands"][command].get("inputs") or {}
    clash = set(glob) & set(spec)
    if clash:
        raise ValueError(f"input(s) {sorted(clash)} are both global and {command!r}'s")
    unknown = set(values) - set(spec) - set(glob)
    if unknown:
        raise ValueError(f"unknown input(s) {sorted(unknown)} for {command!r} (has: {', '.join(spec) or 'none'})")
    argv, env = [INTERP[m["runtime"]["lang"]], m["runtime"]["entry"]], {}
    # global inputs BEFORE the command (argparse takes its top-level options there), the command's own after it
    for group in (glob, None, spec):
        if group is None:
            if command != "run":
                argv.append(command)
            continue
        for name, i in group.items():
            if name not in values:
                if i.get("required"):
                    raise ValueError(f"{command}: {name} is required")
                continue
            v = _coerce(values[name], i["type"], name)
            if "enum" in i and v not in i["enum"]:
                raise ValueError(f"{name}: {v!r} is not one of {i['enum']}")
            if "env" in i:
                env[i["env"]] = json.dumps(v) if isinstance(v, bool) else str(v)
            elif i["type"] == "boolean":
                if v:
                    argv.append(i["cli"])
            else:
                argv += [i["cli"], str(v)]
    return argv, env


def main(argv):
    if len(argv) < 2 or argv[0] not in ("validate", "cmd", "run", "pin"):
        sys.exit(__doc__)
    op, path = argv[0], argv[1]
    if op == "validate":
        bad = 0
        for p in argv[1:]:
            errs = validate(p)
            print(f"{p}: " + ("ok" if not errs else "\n  " + "\n  ".join(errs)))
            bad += bool(errs)
        sys.exit(1 if bad else 0)
    m = json.load(open(path))
    if op == "pin":
        m["source"]["sha256"] = sha256_of(os.path.join(ROOT, m["runtime"]["entry"]))
        with open(path, "w") as f:
            json.dump(m, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"{path}: pinned {m['source']['sha256']}")
        return
    errs = validate(path)
    if errs:
        sys.exit(f"{path} is not a valid actor:\n  " + "\n  ".join(errs))
    if len(argv) < 3:
        sys.exit(f"which command? ({', '.join(m['commands'])})")
    values = dict(a.split("=", 1) for a in argv[3:])
    try:
        cl, env = command_line(m, argv[2], values)
    except ValueError as e:
        sys.exit(str(e))
    if op == "cmd":
        print(json.dumps({"argv": cl, "env": env, "cwd": ROOT}))
        return
    sys.exit(subprocess.call(cl, cwd=ROOT, env=dict(os.environ, **env)))  # nosec B603 # argv list from a validated manifest


if __name__ == "__main__":
    main(sys.argv[1:])
