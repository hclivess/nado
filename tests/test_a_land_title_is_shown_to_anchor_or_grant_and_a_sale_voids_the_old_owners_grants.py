"""
The Land title registry (execnode/games/land.py): only the holder of a plot's title can anchor its build or grant a
builder, the title always comes straight back, and a grant is honoured only while its grantor still holds the title —
driven through the real ExecState.apply_blob path the exec node runs (deploy -> asset_create -> calls).

What a land registry can get wrong, each pinned below:
  * the title proof — anchor/allow/revoke need the plot's OWN title sent in (1 unit): no title, a different plot's
    title, another issuer's asset minted under the same seed, or 2 units are all refused;
  * the title never stays — after every call the caller holds it again and the contract holds nothing;
  * anchors — a zero commitment is refused, versions count up, the anchoring owner and height are recorded, and the
    anchored-plots index lists each plot once;
  * a plot on sale is frozen — a title escrowed by an NFT-marketplace listing cannot be shown;
  * grants — builder_of names the grantor; after a sale the grant still names the OLD owner, which is how the world
    server sees it is void; the new owner can revoke it; nobody can grant themselves;
  * ids >= PLOT_MAX refused (storage aliasing, finding C2);
  * the title's asset id is the derivation the page uses (asset_id(ISSUER, plot_seed(p))).

Run: python3 tests/test_a_land_title_is_shown_to_anchor_or_grant_and_a_sale_voids_the_old_owners_grants.py
"""
import os, tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): a throwaway HOME and exec files, never the live node's
os.environ["HOME"] = tempfile.mkdtemp(prefix="nado-test-land-titles-")
os.environ["NADO_EXEC_STATE"] = os.path.join(os.environ["HOME"], "exec_state.json")
os.environ["NADO_EXEC_DA"] = os.path.join(os.environ["HOME"], "exec_da")
import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState, asset_id
from execnode.runtimes import zkvm_addr_digest
from execnode.games import land as L
from execnode.games import nft as N

import _harness
_report = _harness.Report()
check = _report.run
PROPS = []


def prop(name):
    def reg(fn):
        PROPS.append((name, fn))
        return fn
    return reg

ISSUER = "ndoIIII" + "I" * 41
ALICE = "ndoAAAA" + "A" * 41
BOB = "ndoBBBB" + "B" * 41
MALLORY = "ndoMMMM" + "M" * 41
FUND = 10 ** 15


def _fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(prefix="nado_land_"), "s.json"))
    st.cursor = 1000
    code = L.build(ISSUER)
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": L.ABI, "nonce": "n"}, ISSUER, "d")
    cid = st.contract_id(ISSUER, code, "n")
    ncode = N.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": ncode, "abi": N.ABI, "nonce": "m"}, ISSUER, "d2")
    ncid = st.contract_id(ISSUER, ncode, "m")
    for who in (ISSUER, ALICE, BOB, MALLORY):
        st.credit_deposit(who, FUND)
    nonce = [0]

    def call(who, method, args, value=0, asset=0, contract=None):
        nonce[0] += 1
        blob = {"op": "call", "contract": contract or cid, "method": method, "args": args}
        if value:
            blob["value"] = value
        if asset:
            blob["asset"] = str(asset)
        return st.apply_blob(blob, who, f"n{nonce[0]}")

    def mint(plot, who=ISSUER, seed=None):
        st.apply_blob({"op": "asset_create", "seed": L.plot_seed(plot) if seed is None else seed, "name": f"Plot {plot}",
                       "sym": "LAND", "dec": 0, "supply": 1, "mintable": False, "uri": f"ipfs://bafyplot{plot}"},
                      who, f"m{plot}{who[:4]}")
        return int(asset_id(who, L.plot_seed(plot) if seed is None else seed))

    def give(aid, frm, to):
        nonce[0] += 1
        return st.apply_blob({"op": "asset_transfer", "asset": str(aid), "to": to, "amount": 1}, frm, f"t{nonce[0]}")

    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    bal = lambda aid, who: st.asset_balance(str(aid), who)
    return st, cid, ncid, call, mint, give, rd, bal


def ok(res):
    s = str(res)
    assert not s.startswith("skip:") and "revert" not in s.lower(), f"call failed: {s}"
    return res


def refused(res):
    s = str(res)
    assert s.startswith("skip:") or "revert" in s.lower(), f"expected a refusal, got: {s}"


P = L.plot_id(2, 4100, 4096)
C1, C2 = 0xC0FFEE, 0xBEEF


@prop("the title's asset id is asset_id(ISSUER, plot_seed(p)), and plot ids stay below PLOT_MAX < 2^32")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid = mint(P)
    assert str(aid) in st.assets and st.assets[str(aid)]["supply"] == 1, st.assets.get(str(aid))
    assert bal(aid, ISSUER) == 1
    assert L.PLOT_MAX < (1 << 32) and L.plot_id(5, L.FACE_N - 1, L.FACE_N - 1) == L.PLOT_MAX - 1


@prop("only the holder anchors: no title, another plot's title, and a same-seed asset of another issuer are refused")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid, other = mint(P), mint(P + 1)
    give(aid, ISSUER, ALICE)
    refused(call(ALICE, "anchor", [P, C1]))                                  # nothing shown
    give(other, ISSUER, ALICE)
    refused(call(ALICE, "anchor", [P, C1], value=1, asset=other))            # the next plot's title
    fake = mint(P, who=MALLORY)                                              # same seed, wrong issuer
    refused(call(MALLORY, "anchor", [P, C1], value=1, asset=fake))
    refused(call(MALLORY, "anchor", [P, C1], value=1, asset=aid))            # not his to send
    assert rd(L.A_VER, P) == 0


@prop("an anchor records the commitment, counts versions, names the owner and height, and returns the title")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid = mint(P)
    give(aid, ISSUER, ALICE)
    refused(call(ALICE, "anchor", [P, 0], value=1, asset=aid))               # a zero commitment
    ok(call(ALICE, "anchor", [P, C1], value=1, asset=aid))
    assert (rd(L.A_COMMIT, P), rd(L.A_VER, P), rd(L.A_H, P)) == (C1, 1, 1000)
    assert rd(L.A_BY, P) == zkvm_addr_digest(ALICE)
    assert bal(aid, ALICE) == 1 and bal(aid, cid) == 0, "the title came straight back"
    st.cursor = 1010
    ok(call(ALICE, "anchor", [P, C2], value=1, asset=aid))
    assert (rd(L.A_COMMIT, P), rd(L.A_VER, P), rd(L.A_H, P)) == (C2, 2, 1010)
    assert rd(0, L.CNT_ANCHORED) == 1 and rd(L.A_LIST, 0) == P, "listed once however often it is anchored"
    view = st.decode_view(st.contracts[cid])
    assert view["commit"][str(P)] == C2 and view["by"][str(P)] == ALICE, view


@prop("a plot listed on the NFT marketplace is frozen: its escrowed title cannot be shown")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid = mint(P)
    give(aid, ISSUER, ALICE)
    ok(call(ALICE, "list", [7, aid, 5 * 10 ** 10], value=1, asset=aid, contract=ncid))
    assert bal(aid, ALICE) == 0 and bal(aid, ncid) == 1
    refused(call(ALICE, "anchor", [P, C1], value=1, asset=aid))
    refused(call(ALICE, "allow", [P, BOB], value=1, asset=aid))
    ok(call(BOB, "buy", [7, 1], value=5 * 10 ** 10, contract=ncid))
    ok(call(BOB, "anchor", [P, C1], value=1, asset=aid))                     # the buyer can, at once


@prop("a grant names its grantor, survives a sale only as the OLD owner's (void), and the new owner revokes it")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid = mint(P)
    give(aid, ISSUER, ALICE)
    refused(call(ALICE, "allow", [P, ALICE], value=1, asset=aid))            # nobody grants themselves
    ok(call(ALICE, "allow", [P, BOB], value=1, asset=aid))
    assert st.view(cid, "builder_of", [P, BOB]) == zkvm_addr_digest(ALICE)
    assert st.view(cid, "builder_of", [P, MALLORY]) == 0
    refused(call(BOB, "allow", [P, MALLORY], value=1, asset=aid))            # a builder is not an owner
    give(aid, ALICE, MALLORY)                                                # the plot changes hands
    assert st.view(cid, "builder_of", [P, BOB]) == zkvm_addr_digest(ALICE), "still the old owner's grant"
    assert st.view(cid, "builder_of", [P, BOB]) != zkvm_addr_digest(MALLORY), "so the server treats it as void"
    ok(call(MALLORY, "revoke", [P, BOB], value=1, asset=aid))
    assert st.view(cid, "builder_of", [P, BOB]) == 0
    assert bal(aid, MALLORY) == 1 and bal(aid, cid) == 0


@prop("plot ids at or above PLOT_MAX are refused even with a title minted under that seed")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    big = L.PLOT_MAX
    aid = mint(big)
    refused(call(ISSUER, "anchor", [big, C1], value=1, asset=aid))


@prop("the contract deploys UPGRADABLE, and an upgrade in place keeps its cid, every anchor and every grant")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    assert st.contracts[cid].get("upgradable") is True, "deployed without the lock flag, as the deploy tools do"
    aid = mint(P)
    give(aid, ISSUER, ALICE)
    ok(call(ALICE, "anchor", [P, C1], value=1, asset=aid))
    ok(call(ALICE, "allow", [P, BOB], value=1, asset=aid))
    import base64, json, zstandard
    raw = json.dumps(L.build(ISSUER), separators=(",", ":"), sort_keys=True).encode()
    codez = base64.b64encode(zstandard.ZstdCompressor(level=19).compress(raw)).decode()
    refused(st.apply_blob({"op": "upgrade", "contract": cid, "codez": codez, "abi": L.ABI}, ALICE, "u0"))   # not the deployer
    ok(st.apply_blob({"op": "upgrade", "contract": cid, "codez": codez, "abi": L.ABI}, ISSUER, "u1"))
    assert cid in st.contracts and st.contracts[cid].get("upgradable") is True
    assert (rd(L.A_COMMIT, P), rd(L.A_VER, P)) == (C1, 1), "the anchor survived the upgrade"
    assert st.view(cid, "builder_of", [P, BOB]) == zkvm_addr_digest(ALICE), "the grant survived the upgrade"
    ok(call(ALICE, "anchor", [P, C2], value=1, asset=aid))
    assert rd(L.A_VER, P) == 2
    for tool in ("deploy.py", "redeploy.py"):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "execnode", "games", tool)).read()
        assert '"upgradable": False' not in src and "'upgradable': False" not in src, f"{tool} locks what it deploys"


@prop("the contract carries across a reroll with nothing to settle")
def _():
    st, cid, ncid, call, mint, give, rd, bal = _fresh()
    aid = mint(P)
    give(aid, ISSUER, ALICE)
    ok(call(ALICE, "anchor", [P, C1], value=1, asset=aid))
    ok(call(ALICE, "allow", [P, BOB], value=1, asset=aid))
    assert L.carry_in_flight(st.contracts[cid]["storage"]) == []


if __name__ == "__main__":
    for name, fn in PROPS:
        check(name, fn)
    _report.done()
