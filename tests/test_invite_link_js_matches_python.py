"""The wallet's invite link (static/interface.js "FUNDED INVITE LINKS") is the node's (ops/transaction_ops), exactly.

WHY THIS IS THE TEST THAT MATTERS. A referrer's wallet derives the throwaway link key from the seed in the link, names
the invite by a hash of that key, and the newcomer's wallet signs (chain, id, claimant) with it. Every node recomputes
the id from the key (invite_id_of) and checks the signature against invite_claim_message. One differing byte — a key
order in the canonical encoding, a domain tag, signing the hex instead of its bytes, the wrong ML-DSA mode — and the
lock still lands (the node names it by ITS hash of the key), but the claim is refused at the last step: the gift sits
in escrow until the referrer reclaims it, and the newcomer, whose whole first experience this was, gets nothing.
Unit tests on either side cannot see that; only running the wallet's own code against the node's can.

The JS functions are LIFTED from interface.js (the canonical encoder, mldsaSignHex and the invite block) and run under
node with the wallet's own vendored crypto bundle — not restated here, so an edit to the wallet is what gets tested.
Pinned, for several seeds and claimants:
  - the link key the wallet derives from a seed is the key the node derives from it (signatures.from_private_key), and
    has the length validate_invite requires (INVITE_KEY_HEX);
  - inviteIdOf(key) == invite_id_of(key);
  - the wallet's claim signature verifies against invite_claim_message(id, claimant) — the consensus check;
  - the same signature does NOT verify for another claimant (a copied claim cannot be re-pointed), nor for an id
    computed on another chain (the claim is chain-bound).
Run: python3 tests/test_invite_link_js_matches_python.py   (needs node)
"""
import os
import sys
import tempfile

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-invitejs-")     # ASSIGN, never setdefault (CLAUDE.md rule 4)
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
for _d in ("index", "blocks", "logs", "peers"):
    os.makedirs(os.path.join(os.environ["HOME"], "nado", _d), exist_ok=True)
_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


# Lifts three slices of interface.js and evaluates them against the wallet's vendored crypto bundle. The markers are
# the ones the wallet's own comments name; if one moves, the "slices are found" check fails rather than a silent pass.
NODE_RUNNER = r"""
import { readFileSync } from "node:fs";
const crypto = await import(%(crypto)s);
// the protocol constants the wallet imports from the relay's /protocol.js, rendered from protocol.py
const { P } = await import(%(hook)s);
const js = readFileSync(%(iface)s, "utf8");
const cut = (a, b) => { const i = js.indexOf(a), j = js.indexOf(b, i + 1); if (i < 0 || j < 0) throw new Error("slice not found: " + a); return js.slice(i, j); };
const src = cut("function jsonEscapeAscii(", "function blake2bHashLink(")
  + cut("function mldsaSignHex(", "function authPop(")
  + cut("/* ==== FUNDED INVITE LINKS + REFERRALS", "/* ==== end FUNDED INVITE LINKS + REFERRALS ==== */");
const load = (chainId) => new Function("env", `with (env) { ${src}\n return { inviteKeyOf, inviteIdOf, inviteClaimSig }; }`)({
  blake2b: crypto.blake2b, bytesToHex: crypto.bytesToHex, hexToBytes: crypto.hexToBytes, ml_dsa44: crypto.ml_dsa44,
  CHAIN_ID: chainId, P, TextEncoder });
let raw = ""; process.stdin.on("data", (c) => raw += c); process.stdin.on("end", () => {
  const req = JSON.parse(raw);
  const w = load(req.chain_id), other = load(req.other_chain);
  const out = req.cases.map((c) => {
    const key = w.inviteKeyOf(c.seed), id = w.inviteIdOf(key);
    return { key, id, sig: w.inviteClaimSig(c.seed, id, c.claimant),
             other_chain_id: other.inviteIdOf(key),
             other_chain_sig: other.inviteClaimSig(c.seed, other.inviteIdOf(key), c.claimant) };
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def main():
    from protocol import CHAIN_ID, INVITE_KEY_HEX
    from ops.transaction_ops import invite_id_of, invite_claim_message
    from signatures import verify, from_private_key, generate_keydict

    claimants = [generate_keydict()["address"] for _ in range(3)]
    seeds = ["00" * 32, "ff" * 32, "0123456789abcdef" * 4] + [os.urandom(32).hex() for _ in range(3)]
    cases = [{"seed": s, "claimant": claimants[i % len(claimants)]} for i, s in enumerate(seeds)]

    runner = os.path.join(os.environ["HOME"], "runner.mjs")
    with open(runner, "w") as f:
        f.write(NODE_RUNNER % {
            "crypto": json.dumps("file://" + os.path.join(ROOT, "static", "vendor", "nado-crypto.js")),
            "hook": json.dumps("file://" + os.path.join(ROOT, "tests", "protocol_hook.mjs")),
            "iface": json.dumps(os.path.join(ROOT, "static", "interface.js"))})
    req = {"chain_id": CHAIN_ID, "other_chain": CHAIN_ID + "-other", "cases": cases}
    p = subprocess.run(["node", runner], input=json.dumps(req), capture_output=True, text=True, timeout=180)
    check("the wallet's invite code runs under node (its slices are found in interface.js)", p.returncode == 0, p.stderr[-600:])
    if p.returncode != 0:
        return
    js = json.loads(p.stdout)

    for c, r in zip(cases, js):
        tag = f"seed {c['seed'][:8]}…"
        key = r["key"]
        check(f"the link key from the seed is the node's key from that seed ({tag})",
              key == from_private_key(c["seed"])["public_key"])
        check(f"the link key is an ML-DSA-44 public key of the length validate_invite requires ({tag})",
              len(key) == INVITE_KEY_HEX and all(ch in "0123456789abcdef" for ch in key))
        check(f"inviteIdOf(key) == invite_id_of(key) ({tag})", r["id"] == invite_id_of(key), f"js {r['id']} py {invite_id_of(key)}")
        check(f"the wallet's claim signature verifies against invite_claim_message(id, claimant) ({tag})",
              verify(r["sig"], key, invite_claim_message(r["id"], c["claimant"])))
        rival = next(a for a in claimants if a != c["claimant"])
        check(f"the same signature does NOT verify for another claimant — it cannot be re-pointed ({tag})",
              not verify(r["sig"], key, invite_claim_message(r["id"], rival)))
        check(f"the id is chain-bound: another chain names the same key differently ({tag})", r["other_chain_id"] != r["id"])
        check(f"a claim signed for another chain does not verify here ({tag})",
              not verify(r["other_chain_sig"], key, invite_claim_message(r["id"], c["claimant"])))
    check("distinct seeds give distinct invites", len({r["id"] for r in js}) == len(js))


if __name__ == "__main__":
    main()
    if _fails:
        print(f"\n{len(_fails)} FAILED")
        sys.exit(1)
    print("\nall passed")
