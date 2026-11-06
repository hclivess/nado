#!/usr/bin/env python3
"""Land agent client — the reference for an AI agent (or any program) that helps a plot owner shape the world
(doc/land.md "The API for agents"). It speaks the world server's API (scripts/land_server.py) as ITS OWN identity:

  1. python3 scripts/land_agent.py newkey --out agent.json      a fresh key for the agent (never a person's wallet key);
                                                                prints the agent's address
  2. the plot owner invites that address on land.nadochain.com  ("Invite a builder" on their plot — the land contract's
                                                                allow; selling the plot ends it)
  3. python3 scripts/land_agent.py --keys agent.json build --plot <id> --file house.json
                                                                places a structure: a JSON list of [x, z, y, block] cells,
                                                                x/z 0..15 within the plot, y the layer (0..255)
  Also: `plot --plot <id>` (the plot's edits), `set --cells '[[face,u,v,h,block],…]'`, `watch --plot <id>` (live edits).

THE AGENT PLAYS BY THE SAME RULES AS A PERSON (static/land-recipes.json): a cell set to 0 is BROKEN — gathered into the
agent's own inventory, if its tools can break it, at the speed a hand (or that tool) works — anywhere in the wilderness,
and on a titled plot only where it may build; any other block id is PLACED from its inventory, one item each, only where
it may build. So an agent gathers, makes tools and trades like anyone:
  inventory · craft --recipe <id> [--times n] · give --to <address> --items '{"cobble": 4}' · offers ·
  offer --give '{"planks": 8}' --want '{"sand": 4}' · accept --id <offer> · cancel --id <offer>
Blocks are static/land-world.js BLOCKS ids. At most MAX_CELLS cells per call and RATE cells a second; anything refused
comes back in `refused` with the reason.
"""
import os, sys, tempfile
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-land-agent-")   # BEFORE the crypto import (CLAUDE.md rule 4)
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import argparse, json, time, urllib.request

from signatures import generate_keydict, sign, unhex     # noqa: E402 — pure crypto
from hashing import blake2b_hash                         # noqa: E402

DOMAIN, AGENT_ORIGIN = "land-login-v1", "land-agent"     # scripts/land_server.py DOMAIN / AGENT_ORIGIN
FACE_N, PLOT = 8192, 16                                  # execnode/games/land.py


def call(server, path, body=None, token=None):
    req = urllib.request.Request(server.rstrip("/") + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + token} if token else {})})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 # the operator's chosen world server
        return json.loads(r.read().decode())


def login(server, kd):
    ch = call(server, "/land/api/challenge?kind=agent")
    msg = blake2b_hash([DOMAIN, AGENT_ORIGIN, kd["address"], ch["nonce"], ch["issued"]], 32)
    body = {"address": kd["address"], "public_key": kd["public_key"], "nonce": ch["nonce"],
            "signature": sign(kd["private_key"], unhex(msg), alg=kd.get("alg"))}
    if kd.get("alg"):
        body["alg"] = kd["alg"]
    return call(server, "/land/api/agent_login", body)["token"]


def plot_cells(plot, cells):
    """[x, z, y, block] within plot -> [face, u, v, h, block] on the planet."""
    face, row, col = plot // (FACE_N * FACE_N), (plot // FACE_N) % FACE_N, plot % FACE_N
    out = []
    for x, z, y, b in cells:
        if not (0 <= x < PLOT and 0 <= z < PLOT):
            raise SystemExit(f"cell {[x, z, y, b]} is outside the plot (x and z run 0..15)")
        out.append([face, col * PLOT + x, row * PLOT + z, y, b])
    return out


def main():
    ap = argparse.ArgumentParser(description="NADO Land agent client")
    ap.add_argument("--server", default="https://land.nadochain.com")
    ap.add_argument("--keys", help="the agent's own key file (from `newkey`)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    nk = sub.add_parser("newkey"); nk.add_argument("--out", required=True); nk.add_argument("--alg", default=None)
    pl = sub.add_parser("plot"); pl.add_argument("--plot", type=int, required=True)
    st = sub.add_parser("set"); st.add_argument("--cells", required=True)
    bd = sub.add_parser("build"); bd.add_argument("--plot", type=int, required=True); bd.add_argument("--file", required=True)
    wt = sub.add_parser("watch"); wt.add_argument("--plot", type=int, required=True)
    sub.add_parser("inventory")
    cr = sub.add_parser("craft"); cr.add_argument("--recipe", required=True); cr.add_argument("--times", type=int, default=1)
    gv = sub.add_parser("give"); gv.add_argument("--to", required=True); gv.add_argument("--items", required=True)
    sub.add_parser("offers")
    of = sub.add_parser("offer"); of.add_argument("--give", required=True); of.add_argument("--want", required=True)
    ac = sub.add_parser("accept"); ac.add_argument("--id", required=True)
    cn = sub.add_parser("cancel"); cn.add_argument("--id", required=True)
    a = ap.parse_args()

    if a.cmd == "newkey":
        if os.path.exists(a.out):
            raise SystemExit(f"{a.out} exists — refusing to overwrite a key")
        kd = generate_keydict(a.alg)
        fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({k: kd[k] for k in ("address", "public_key", "private_key")} | ({"alg": a.alg} if a.alg else {}), f)
        print(kd["address"])
        print(f"The agent's own key is in {a.out} (keep it private). Give the address above to the plot owner to invite.",
              file=sys.stderr)
        return
    if not a.keys:
        raise SystemExit("--keys <the agent's key file> is required (create one with `newkey`)")
    kd = json.load(open(a.keys))
    if a.cmd == "plot":
        print(json.dumps(call(a.server, f"/land/api/plot?plot={a.plot}", token=login(a.server, kd)), indent=1))
    elif a.cmd == "set":
        print(json.dumps(call(a.server, "/land/api/set", {"cells": json.loads(a.cells)}, token=login(a.server, kd))))
    elif a.cmd == "build":
        cells = plot_cells(a.plot, json.load(open(a.file)))
        tok, applied, refused = login(a.server, kd), 0, []
        for i in range(0, len(cells), 2048):                 # half a full call each, 2048 / RATE (400/s) apart
            r = call(a.server, "/land/api/set", {"cells": cells[i:i + 2048]}, token=tok)
            applied += r["applied"]; refused += r["refused"]
            if i + 2048 < len(cells):
                time.sleep(5.5)
        print(json.dumps({"applied": applied, "refused": refused[:20], "refused_total": len(refused)}))
    elif a.cmd == "inventory":
        print(json.dumps(call(a.server, "/land/api/inventory", token=login(a.server, kd))))
    elif a.cmd == "craft":
        print(json.dumps(call(a.server, "/land/api/craft", {"recipe": a.recipe, "times": a.times}, token=login(a.server, kd))))
    elif a.cmd == "give":
        print(json.dumps(call(a.server, "/land/api/give", {"to": a.to, "items": json.loads(a.items)}, token=login(a.server, kd))))
    elif a.cmd == "offers":
        print(json.dumps(call(a.server, "/land/api/offers")))
    elif a.cmd == "offer":
        print(json.dumps(call(a.server, "/land/api/offer", {"give": json.loads(a.give), "want": json.loads(a.want)}, token=login(a.server, kd))))
    elif a.cmd in ("accept", "cancel"):
        path = "/land/api/accept" if a.cmd == "accept" else "/land/api/cancel_offer"
        print(json.dumps(call(a.server, path, {"id": a.id}, token=login(a.server, kd))))
    elif a.cmd == "watch":
        import asyncio, aiohttp
        async def run():
            tok = login(a.server, kd)
            url = a.server.replace("https://", "wss://").replace("http://", "ws://").rstrip("/") + "/land/ws?token=" + tok
            async with aiohttp.ClientSession() as s, s.ws_connect(url) as ws:
                await ws.send_json({"t": "watch", "plots": [a.plot]})
                async for m in ws:
                    d = json.loads(m.data)
                    if d.get("t") in ("plot", "edit"):
                        print(json.dumps(d), flush=True)
        asyncio.run(run())


if __name__ == "__main__":
    main()
