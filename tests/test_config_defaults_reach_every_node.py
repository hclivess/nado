import os, tempfile; os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-cfgdefaults-")   # BEFORE any nado import
"""The shipped defaults are merged under every node's own config (operator 2026-11-21: "the correct logic is to merge
the default json to every node which doesnt have its own configured ... make that design like that").

get_config() returned config.json verbatim, so a default added later reached only nodes installed afterwards (CLAUDE.md
rule 9): the node auto-vote allow-list stayed `faucet` on every node while the wallet shipped the operator's address
beside it, and no node ever voted on a proposal paying the operator. This pins the design:
  1. a key the node's file does not set takes CONFIG_DEFAULTS; a key it sets wins — even when it sets the default's
     opposite, and even when it sets something empty;
  2. nothing is rewritten: update_config persists the raw file plus the one knob, never the merged defaults; and
     create_config writes none of the merged keys, so a new install keeps following them;
  3. the safety list: per-install values, `archive` (operator 2026-08-17) and the protocol-constant knobs are never
     merged, and every merged key's default equals what the code did when the key was absent (a no-op for every node
     but the operator's intended change, the allow-list);
  4. the allow-list is the wallet's shipped list, and the node reads it from here.
Run: python3 tests/test_config_defaults_reach_every_node.py
"""
import json, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import config as C

fails = 0
def check(name, ok, detail=""):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok else f": {detail}"))
    fails += 0 if ok else 1

d = tempfile.mkdtemp(); p = os.path.join(d, "config.json")
json.dump({"port": 9173, "ip": "1.2.3.4", "server_key": "k", "auto_update": False, "auto_vote_allow": ""}, open(p, "w"))
g = C.get_config(p)
check("a key the node does not set takes the shipped default", g["relay_port"] == 80 and g["challenger"] is True
      and g["auto_vote_allow"] == "" and "auto_bond_percent" in g, g)
check("…a key it sets wins, even the default's opposite (auto_update False) and even empty (auto_vote_allow '')",
      g["auto_update"] is False and g["auto_vote_allow"] == "", g)
json.dump({"port": 9173, "ip": "1.2.3.4", "server_key": "k"}, open(p, "w"))
check("a node with no allow-list of its own gets the shipped one", C.get_config(p)["auto_vote_allow"] == C.CONFIG_DEFAULTS["auto_vote_allow"])
C.update_config({"min_peers": 3}, p)
raw = json.load(open(p))
check("update_config persists the file plus the one knob, never the merged defaults", raw == {"port": 9173, "ip": "1.2.3.4", "server_key": "k", "min_peers": 3}, raw)
p2 = os.path.join(d, "new.json"); C.create_config("5.6.7.8", p2); new = json.load(open(p2))
check("create_config writes none of the merged keys (a new install keeps following them)",
      not (set(new) & set(C.CONFIG_DEFAULTS)) and new["ip"] == "5.6.7.8" and "server_key" in new, sorted(set(new) & set(C.CONFIG_DEFAULTS)))
NEVER = {"port", "ip", "server_key", "config_version", "archive", "min_peers", "max_rollbacks", "finality_depth", "block_time"}
check("never merged: per-install values, archive (operator 2026-08-17), the protocol-constant knobs",
      not (set(C.CONFIG_DEFAULTS) & NEVER), sorted(set(C.CONFIG_DEFAULTS) & NEVER))
# every merged key's default equals the code's own fallback for it (grep every .get("key", X) in the node's code)
src = ""
for top, _, files in os.walk(ROOT):
    if any(x in top for x in ("/tests", "/node_modules", "/.git", "/nado_venv", "/static")): continue
    for f in files:
        if f.endswith(".py"): src += open(os.path.join(top, f), errors="ignore").read()
import protocol as P
env = {"True": True, "False": False, "None": None, "AUTO_BOND_DEFAULT_PERCENT": P.AUTO_BOND_DEFAULT_PERCENT,
       "_AB_DEFAULT": P.AUTO_BOND_DEFAULT_PERCENT, 'CONFIG_DEFAULTS["auto_vote_allow"]': C.CONFIG_DEFAULTS["auto_vote_allow"]}
bad = []
for k, v in C.CONFIG_DEFAULTS.items():
    for fb in re.findall(r'\.get\("' + k + r'",\s*([^)\n]+?)\)', src):
        fb = fb.strip(); val = env.get(fb, None) if fb in env else (int(fb) if fb.isdigit() else fb.strip('"'))
        if val != v: bad.append((k, fb, v))
check("every merged default equals the code's own fallback for that key (no node changes behaviour but by intent)", not bad, bad)
w = re.search(r'const AUTO_VOTE_DEFAULT_ALLOW = \[([^\]]*)\];', open(os.path.join(ROOT, "static", "interface.js")).read())
wl = sorted(a.strip().strip('"').lower() for a in w.group(1).split(","))
check("the node's default allow-list is the wallet's shipped list: the operator's address and faucet",
      sorted(a.strip().lower() for a in C.CONFIG_DEFAULTS["auto_vote_allow"].split(",")) == wl == sorted(["b7a08de8351e3af97f6f2bbcb19f2a8c722abad81c3460caf9", "faucet"]), wl)
mem = open(os.path.join(ROOT, "memserver.py")).read()
check("…and the node reads it from the merged config", 'self.config.get("auto_vote_allow", CONFIG_DEFAULTS["auto_vote_allow"])' in mem)
print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED")); sys.exit(1 if fails else 0)
