"""Pets Homestead: trades, base building, lazy production, provisioning, and Diablo-style gear.

The expansion turns the tamagotchi loop (which only ever ran DOWN — every pet costs NADO to feed) into a
working base: a pet has a TRADE derived from its species, a matching building can be staffed with it, and
production accrues lazily. Fodder feeds the barn for free; work turns up GEAR whose affixes are points on
real stats, so equipping one is visible in the arena.

These checks pin the parts where being wrong costs someone money or a pet: the trade gate on who may build
and work, that changing a building's terms banks the old terms first, that production is capped and paid to
the OWNER rather than the caller, that fodder is actually spent, and that equip/unequip is exactly
reversible (a drifting gear board would permanently inflate or wreck a pet).

Run: HOME=/root python tests/pets_homestead_test.py
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from execnode.state import ExecState
from execnode.games import pets as P

A, B = "ndoALICE", "ndoBOB"
passed = failed = 0


def ok(cond, msg):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("  FAIL:", msg)


def fresh():
    st = ExecState(os.path.join(tempfile.mkdtemp(), "s.json"))
    st.cursor = 100
    st.block_ts = int(time.time())
    # deterministic block hashes for hatch / item rolls
    st.block_hashes = {h: (h * 1_000_003 + 7) for h in range(0, 200000)}
    code = P.build()
    st.apply_blob({"op": "deploy", "runtime": "zkvm", "code": code, "abi": P.ABI, "nonce": "n"}, A, "d")
    cid = st.contract_id(A, code, "n")
    rd = lambda f, k: int((st.contracts[cid]["storage"].get("slots") or {}).get(str(f * (1 << 32) + k), 0))
    return st, cid, rd


def call(st, cid, who, method, args, value=None, tag=""):
    p = {"op": "call", "contract": cid, "method": method, "args": args}
    if value:
        p["value"] = value
    st.apply_blob(p, who, method + tag + who + str(args))


def hatched(st, cid, rd, owner, pid):
    """mint + hatch one pet and return its trade (si % NJOBS)."""
    st.credit_deposit(owner, P.MINT_FEE)
    call(st, cid, owner, "mint", [pid], P.MINT_FEE)
    st.cursor += 3
    call(st, cid, owner, "hatch", [pid])
    return rd(P.SI, pid) % P.NJOBS


def pet_of_trade(st, cid, rd, owner, want, start):
    """mint pets until one is born to `want` — trades come from the species, so we search rather than pick.
    Asserts the pet actually hatched: a mint that silently failed (no funds) leaves si == 0, which reads as
    "trade 0" and would hand the caller a pet that does not exist."""
    pid = start
    while pid < start + 400:
        if rd(P.OW, pid) == 0:
            t = hatched(st, cid, rd, owner, pid)
            assert rd(P.OW, pid) != 0 and rd(P.GN, pid) != 0, f"pet {pid} did not mint/hatch (funds?)"
            if t == want:
                return pid
        pid += 1
    raise AssertionError(f"no pet of trade {want} in 400 tries")



def grant(st, cid, owner, kind, amount):
    """Put resources straight into a player's store. Upgrades cost materials, and earning timber+stone the
    honest way means raising and working two more bases — worth testing once (it is), but not worth paying
    for in every other test. The slot is derived exactly as the contract derives it."""
    from execnode.runtimes import zkvm_addr_digest
    from execnode.stark import alghash
    slot = alghash.hashn([P.TG_RES, zkvm_addr_digest(owner), kind])
    st.contracts[cid]["storage"].setdefault("slots", {})[str(slot)] = int(amount)
    st.contracts[cid]["storage"]["slots"] = st.contracts[cid]["storage"]["slots"]


def test_trade_gates_who_can_build_and_work():
    """A base is raised BY a pet of its trade and worked BY a pet of its trade. Without the gate the whole
    'which animal do I need' layer collapses into 'any pet does anything'."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    farmer = pet_of_trade(st, cid, rd, A, 0, 1000)
    miner = pet_of_trade(st, cid, rd, A, 3, 2000)

    call(st, cid, A, "build", [1, 0, miner], P.BUILD_FEE)
    ok(rd(P.BO, 1) == 0, "a miner cannot raise a farm")
    call(st, cid, A, "build", [1, 0, farmer], P.BUILD_FEE - 1, tag="cheap")
    ok(rd(P.BO, 1) == 0, "the NADO cost is enforced exactly")
    call(st, cid, A, "build", [1, 0, farmer], P.BUILD_FEE)
    ok(rd(P.BO, 1) != 0 and rd(P.BL, 1) == 1, "the right pet + the right fee raises the farm")
    ok(rd(0, P.BURN_SLOT) >= P.BUILD_FEE, "the build fee is burned, not pocketed")

    call(st, cid, A, "staff", [1, miner])
    ok(rd(P.BP, 1) == 0, "a miner cannot work a farm")
    call(st, cid, A, "staff", [1, farmer])
    ok(rd(P.BP, 1) == farmer, "the farmer can")
    call(st, cid, B, "staff", [1, farmer], tag="notmine")
    ok(rd(P.BP, 1) == farmer, "a stranger cannot re-staff someone else's base")

    call(st, cid, A, "build", [2, P.NJOBS, farmer], P.BUILD_FEE)
    ok(rd(P.BO, 2) == 0, "a trade that does not exist is refused")


def test_production_is_lazy_capped_and_paid_to_the_owner():
    """collect() is permissionless so a helper (or a batch button) can settle a base — but the harvest must
    always land with the OWNER. And an unattended base banks a bounded window, never a year in one call."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    farmer = pet_of_trade(st, cid, rd, A, 0, 3000)
    call(st, cid, A, "build", [7, 0, farmer], P.BUILD_FEE)
    view = lambda m, a: st.view(cid, m, a)

    st.cursor += 500
    call(st, cid, A, "collect", [7])
    ok(view("res_of", [A, 0]) == 0, "an unstaffed base produces nothing")

    call(st, cid, A, "staff", [7, farmer])
    st.cursor += 1000
    call(st, cid, B, "collect", [7], tag="bob")
    got = view("res_of", [A, 0])
    ok(got > 0, "a staffed base produces")
    ok(view("res_of", [B, 0]) == 0, "the caller of collect never receives the owner's harvest")

    call(st, cid, A, "collect", [7], tag="again")
    ok(view("res_of", [A, 0]) == got, "collecting twice in the same block pays once")

    st.cursor += 10 * P.ACCRUE_CAP
    call(st, cid, A, "collect", [7], tag="long")
    capped = view("res_of", [A, 0]) - got
    st.cursor += P.ACCRUE_CAP
    call(st, cid, A, "collect", [7], tag="cap2")
    exact = view("res_of", [A, 0]) - got - capped
    ok(capped == exact, "an unattended base banks at most ACCRUE_CAP blocks of work")


def test_changing_the_terms_banks_the_old_terms_first():
    """staff() and upgrade() both change what a base pays. If either moved the rate without settling first,
    the pet that did the work would be paid at someone else's rate — silently, and in the wrong direction."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    f1 = pet_of_trade(st, cid, rd, A, 0, 4000)
    call(st, cid, A, "build", [9, 0, f1], P.BUILD_FEE)
    call(st, cid, A, "staff", [9, f1])
    view = lambda m, a: st.view(cid, m, a)

    st.cursor += 600
    call(st, cid, A, "staff", [9, 0])                       # clock off
    banked = view("res_of", [A, 0])
    ok(banked > 0, "clocking a pet off pays out the shift it worked")
    st.cursor += 600
    call(st, cid, A, "collect", [9], tag="idle")
    ok(view("res_of", [A, 0]) == banked, "an unstaffed base earns nothing while idle")

    call(st, cid, A, "staff", [9, f1], tag="back")
    st.cursor += 600
    grant(st, cid, A, 1, 10000)              # timber
    grant(st, cid, A, 2, 10000)              # stone
    before = view("res_of", [A, 0])
    call(st, cid, A, "upgrade", [9, f1], 2 * P.BUILD_FEE)
    ok(rd(P.BL, 9) == 2, "upgrade raises the level")
    ok(view("res_of", [A, 0]) > before, "upgrade banks the level-1 work before switching rate")
    call(st, cid, A, "upgrade", [9, f1], P.BUILD_FEE, tag="underpay")
    ok(rd(P.BL, 9) == 2, "each level up costs more than the last, exactly")


def test_fodder_feeds_the_barn_and_is_actually_spent():
    """The point of farming: fodder a farm produced feeds pets with no NADO. It must come OUT of the store,
    and the belly must still respect the same cap feeding does — free food is not infinite food."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    farmer = pet_of_trade(st, cid, rd, A, 0, 5000)
    call(st, cid, A, "build", [11, 0, farmer], P.BUILD_FEE)
    call(st, cid, A, "staff", [11, farmer])
    st.cursor += P.ACCRUE_CAP
    call(st, cid, A, "collect", [11])
    view = lambda m, a: st.view(cid, m, a)
    store = view("res_of", [A, 0])
    ok(store > 0, "the farm produced fodder")

    call(st, cid, A, "provision", [farmer, store + 1])
    ok(view("res_of", [A, 0]) == store, "cannot provision more fodder than the store holds")

    fu0 = rd(P.FU, farmer)
    call(st, cid, A, "provision", [farmer, 5])
    ok(view("res_of", [A, 0]) == store - 5, "provisioning spends the fodder")
    ok(rd(P.FU, farmer) > fu0, "and extends the belly")
    call(st, cid, B, "provision", [farmer, 1], tag="notmine")
    ok(view("res_of", [A, 0]) == store - 5, "a stranger cannot feed from my store")

    call(st, cid, A, "provision", [farmer, store - 5], tag="all")
    ok(rd(P.FU, farmer) <= st.cursor + P.BELLY_CAP, "the belly cap still holds on free food")


def test_gear_is_points_on_real_stats_and_exactly_reversible():
    """Equipping adds an item's rolled affixes to the pet's gear board, which _eff_stat feeds into every
    stat read including the arena. Unequip must return the pet EXACTLY to where it was — a drifting board
    would permanently inflate (or wreck) a pet, and nothing in the game could undo it."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    farmer = pet_of_trade(st, cid, rd, A, 0, 6000)
    call(st, cid, A, "build", [13, 0, farmer], P.BUILD_FEE)
    call(st, cid, A, "staff", [13, farmer])
    # collect repeatedly until the drop roll lands
    iid = 0
    for k in range(40):
        st.cursor += 300
        call(st, cid, A, "collect", [13], tag=f"c{k}")
        n = rd(0, P.ICNT_SLOT)
        if n:
            iid = rd(P.ILIST, n - 1)
            break
    ok(iid != 0, "working a base eventually turns up an item")
    if not iid:
        return
    ok(rd(P.IO, iid) != 0 and rd(P.IE, iid) == 0, "the find belongs to the base's owner and is unworn")
    ok(1 <= rd(P.IR, iid) <= 6, "it has a sane rarity")
    ok(rd(P.IT, iid) < P.GEAR_SLOTS, "and a real gear slot")

    before = [rd(P.GB_BASE + i, farmer) for i in range(10)]
    call(st, cid, A, "equip", [iid, farmer])
    ok(rd(P.IE, iid) == farmer, "equipping records the wearer")
    after = [rd(P.GB_BASE + i, farmer) for i in range(10)]
    ok(sum(after) > sum(before), "and adds its affix points to the pet")
    ok(st.view(cid, "gear_of", [farmer, rd(P.IT, iid)]) == iid, "the pet's slot now holds it")

    call(st, cid, B, "equip", [iid, farmer], tag="thief")
    ok(rd(P.IE, iid) == farmer, "a stranger cannot move my gear")
    call(st, cid, A, "scrap", [iid], tag="worn")
    ok(rd(P.IO, iid) != 0, "worn gear cannot be scrapped out from under a pet")

    call(st, cid, A, "unequip", [iid])
    ok([rd(P.GB_BASE + i, farmer) for i in range(10)] == before, "unequip returns the pet EXACTLY to before")
    ok(st.view(cid, "gear_of", [farmer, rd(P.IT, iid)]) == 0, "and frees the slot")

    ess = st.view(cid, "res_of", [A, 4])
    call(st, cid, A, "scrap", [iid], tag="ok")
    ok(st.view(cid, "res_of", [A, 4]) > ess, "scrapping an unworn item returns essence")
    ok(rd(P.IO, iid) == 0, "and the item is gone")


def test_gear_shows_up_in_the_arena():
    """The integration that makes gear matter: a stat read anywhere must already include equipment."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    pid = pet_of_trade(st, cid, rd, A, 0, 7000)
    # hand-place a known gear bonus, then read the same stat the battle reads
    slots = st.contracts[cid]["storage"].setdefault("slots", {})
    idx = 0
    base_key = str((P.GB_BASE + idx) * (1 << 32) + pid)
    st.contracts[cid]["storage"]["slots"] = slots
    before = P.ref_stat(rd(P.GN, pid), rd(P.SP, pid), idx) if hasattr(P, "ref_stat") else None
    slots[base_key] = 25
    st._touch() if hasattr(st, "_touch") else None
    call(st, cid, A, "build", [17, 0, pid], P.BUILD_FEE)
    call(st, cid, A, "staff", [17, pid])
    st.cursor += 1000
    call(st, cid, A, "collect", [17])
    ok(st.view(cid, "res_of", [A, 0]) > 0, "a geared pet still produces (gear feeds the same stat path)")



def test_upgrades_cost_materials_and_cannot_be_half_paid():
    """Materials are what tie the bases together — a Farm needs a Sawmill and a Quarry to grow. If a short
    balance let the upgrade through, timber and stone would be decorative; if it took the materials and
    then failed, the player would be robbed. It has to be all or nothing."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    f1 = pet_of_trade(st, cid, rd, A, 0, 8000)
    call(st, cid, A, "build", [21, 0, f1], P.BUILD_FEE)
    view = lambda m, a: st.view(cid, m, a)
    cost = 2 * P.BUILD_FEE

    call(st, cid, A, "upgrade", [21, f1], cost, tag="broke")
    ok(rd(P.BL, 21) == 1, "no materials, no upgrade")

    grant(st, cid, A, 1, 2 * P.UPG_TIMBER)      # enough timber
    grant(st, cid, A, 2, 2 * P.UPG_STONE - 1)   # one stone short
    call(st, cid, A, "upgrade", [21, f1], cost, tag="short")
    ok(rd(P.BL, 21) == 1, "one unit short is still short")
    ok(view("res_of", [A, 1]) == 2 * P.UPG_TIMBER, "and the timber was NOT taken on the failed attempt")

    grant(st, cid, A, 2, 2 * P.UPG_STONE)
    call(st, cid, A, "upgrade", [21, f1], cost, tag="paid")
    ok(rd(P.BL, 21) == 2, "with both materials it goes up")
    ok(view("res_of", [A, 1]) == 0 and view("res_of", [A, 2]) == 0, "and both were spent")

    # ore only bites from level 4 up, so levels 2->3 need no ore at all
    grant(st, cid, A, 1, 99999); grant(st, cid, A, 2, 99999)
    call(st, cid, A, "upgrade", [21, f1], 3 * P.BUILD_FEE, tag="l3")
    ok(rd(P.BL, 21) == 3, "level 3 needs no ore")
    call(st, cid, A, "upgrade", [21, f1], 4 * P.BUILD_FEE, tag="l4")
    ok(rd(P.BL, 21) == 3, "level 4 does need ore")
    grant(st, cid, A, 3, 4 * P.UPG_ORE)
    call(st, cid, A, "upgrade", [21, f1], 4 * P.BUILD_FEE, tag="l4b")
    ok(rd(P.BL, 21) == 4, "with ore it goes to 4")



def test_reroll_costs_essence_keeps_the_item_and_only_off_the_pet():
    """The affix chase. Rerolling must not change what the item IS (slot, rarity) — that would be a slot
    machine for better items rather than better rolls — must cost essence, and must be impossible while the
    item is worn, or the pet's gear board would keep points the item no longer has."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 2000 * P.MINT_FEE)
    pid = pet_of_trade(st, cid, rd, A, 0, 9000)
    call(st, cid, A, "build", [31, 0, pid], P.BUILD_FEE)
    call(st, cid, A, "staff", [31, pid])
    iid = 0
    for k in range(60):
        st.cursor += 300
        call(st, cid, A, "collect", [31], tag=f"r{k}")
        n = rd(0, P.ICNT_SLOT)
        if n: iid = rd(P.ILIST, n - 1); break
    ok(iid != 0, "found an item to reroll")
    if not iid: return
    kind, rar = rd(P.IT, iid), rd(P.IR, iid)
    before = [rd(P.IA_BASE + k, iid) for k in range(3)]
    view = lambda m, a: st.view(cid, m, a)

    call(st, cid, A, "reroll", [iid], P.REROLL_FEE, tag="broke")
    ok([rd(P.IA_BASE + k, iid) for k in range(3)] == before, "no essence, no reroll")

    grant(st, cid, A, 4, rar * P.REROLL_ESSENCE)
    grant(st, cid, A, 1, rar * P.REROLL_TIMBER)      # rerolling costs materials too (the repeatable sink)
    grant(st, cid, A, 2, rar * P.REROLL_STONE)
    grant(st, cid, A, 3, rar * P.REROLL_ORE)
    call(st, cid, A, "equip", [iid, pid])
    call(st, cid, A, "reroll", [iid], P.REROLL_FEE, tag="worn")
    ok([rd(P.IA_BASE + k, iid) for k in range(3)] == before, "cannot reroll gear that is being worn")
    call(st, cid, A, "unequip", [iid])

    st.cursor += 1                                   # fresh block -> fresh entropy
    call(st, cid, A, "reroll", [iid], P.REROLL_FEE, tag="ok")
    after = [rd(P.IA_BASE + k, iid) for k in range(3)]
    ok(after != before, "with essence and off the pet, the affixes change")
    ok(rd(P.IT, iid) == kind and rd(P.IR, iid) == rar, "the item keeps its slot and rarity")
    ok(view("res_of", [A, 4]) == 0, "and the essence is spent")
    for packed in after:
        idx, pts = packed // P.AFFIX_MUL, packed % P.AFFIX_MUL
        ok(0 <= idx < 10, "rerolled affix targets a real stat")
        ok(1 <= pts <= P.AFFIX_CAP * rar, "rerolled points stay within the rarity band")



def _mint_item(st, cid, rd, owner, iid, kind, rarity):
    """Place an item directly. Fusing needs several of the same slot, and farming them honestly would take
    hundreds of collect rolls — the drop path itself is covered by the gear test."""
    from execnode.runtimes import zkvm_addr_digest
    slots = st.contracts[cid]["storage"].setdefault("slots", {})
    B = 1 << 32
    slots[str(P.IO * B + iid)] = zkvm_addr_digest(owner)
    slots[str(P.IT * B + iid)] = kind
    slots[str(P.IR * B + iid)] = rarity
    slots[str(P.IE * B + iid)] = 0
    for k in range(3):
        slots[str((P.IA_BASE + k) * B + iid)] = 1 * P.AFFIX_MUL + 3      # +3 Agility, three times


def test_fusing_absorbs_junk_but_cannot_craft_the_rarest_gear():
    """The anti-Diablo-3 sink. Item supply is unbounded in time while demand is four slots per pet, so junk
    MUST have a permanent use or it ends up worthless and the chase is over. Fusing gives it one — and stops
    at FUSE_MAX_TIER, because the best gear staying FINDABLE-ONLY (by a rare pet, which costs burned NADO
    and luck) is the one scarcity anchor the economy has."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 200 * P.MINT_FEE)
    view = lambda m, a: st.view(cid, m, a)
    for i, (iid, kind, rar) in enumerate([(1, 0, 1), (2, 0, 1), (3, 1, 1), (4, 0, 1), (5, 0, P.FUSE_MAX_TIER)]):
        _mint_item(st, cid, rd, A, iid, kind, rar)
    for k in (1, 2, 3, 4):
        grant(st, cid, A, k, 10000)                              # fusing pulls on every material + essence
    st.credit_deposit(A, 100 * P.FUSE_FEE)

    call(st, cid, A, "fuse", [1, 3], P.FUSE_FEE)
    ok(rd(P.IR, 1) == 1, "cannot fuse across gear slots")
    call(st, cid, B, "fuse", [1, 2], tag="thief")
    ok(rd(P.IR, 1) == 1, "cannot fuse someone else's items")
    call(st, cid, A, "fuse", [1, 1], P.FUSE_FEE, tag="self")
    ok(rd(P.IR, 1) == 1, "cannot fuse an item into itself")

    ore0 = view("res_of", [A, 3])
    call(st, cid, A, "fuse", [1, 2], P.FUSE_FEE, tag="ok")
    ok(rd(P.IR, 1) == 2, "same slot, owned, unworn -> the target goes up a tier")
    ok(rd(P.IO, 2) == 0, "and the food item is destroyed")
    ok(view("res_of", [A, 3]) < ore0, "materials are spent — the permanent sink for them")

    call(st, cid, A, "fuse", [1, 4], P.FUSE_FEE, tag="weak")
    ok(rd(P.IR, 1) == 2, "food must be at least as good as the target")

    # the ceiling: an item already at the cap cannot be pushed further, whatever you feed it
    _mint_item(st, cid, rd, A, 6, 0, 6)
    call(st, cid, A, "fuse", [5, 6], P.FUSE_FEE, tag="cap")
    ok(rd(P.IR, 5) == P.FUSE_MAX_TIER, "fusing stops at the cap — the top tiers must be FOUND")

    _mint_item(st, cid, rd, A, 7, 2, 1)
    _mint_item(st, cid, rd, A, 8, 2, 1)
    call(st, cid, A, "equip", [7, pet_of_trade(st, cid, rd, A, 0, 11000)])
    call(st, cid, A, "fuse", [7, 8], P.FUSE_FEE, tag="worn")
    ok(rd(P.IR, 7) == 1, "cannot fuse gear that is being worn")


def test_reroll_also_spends_materials():
    """Upgrades are a FINITE material sink (a building consumes 560 timber over its whole life and then
    never again). Without a repeatable one, timber and stone pile up worthless the moment every base is
    maxed — so rerolling costs them too, forever."""
    st, cid, rd = fresh()
    st.credit_deposit(A, 200 * P.MINT_FEE)
    _mint_item(st, cid, rd, A, 12, 0, 2)
    view = lambda m, a: st.view(cid, m, a)
    grant(st, cid, A, 4, 1000)                                   # essence only
    before = [rd(P.IA_BASE + k, 12) for k in range(3)]
    call(st, cid, A, "reroll", [12], P.REROLL_FEE, tag="nomat")
    ok([rd(P.IA_BASE + k, 12) for k in range(3)] == before, "essence alone is not enough any more")
    ok(view("res_of", [A, 4]) == 1000, "and the essence was NOT taken on the failed attempt")
    grant(st, cid, A, 1, 1000); grant(st, cid, A, 2, 1000); grant(st, cid, A, 3, 1000)
    st.cursor += 1
    call(st, cid, A, "reroll", [12], P.REROLL_FEE, tag="mat")
    ok([rd(P.IA_BASE + k, 12) for k in range(3)] != before, "with materials it rerolls")
    ok(view("res_of", [A, 1]) < 1000 and view("res_of", [A, 2]) < 1000, "timber and stone are spent")



def test_client_constants_match_the_contract():
    """static/pets.js MIRRORS a dozen contract constants so it can show what a base will produce before you
    collect. They drifted the moment the contract was retuned: RATE_DIV and FODDER_BLOCKS were left at their
    pre-tuning values (so every yield on screen was 10x wrong) and RARITY_RATE was never declared at all,
    which threw a ReferenceError on EVERY refresh — the whole page froze at "Loading pet from the chain",
    and hatching, feeding and battling all stopped working. A mirrored constant needs a test or it is a
    silent time bomb."""
    import re
    js = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "static", "pets.js"), encoding="utf-8").read()
    for name in ("NJOBS", "GEAR_SLOTS", "RATE_DIV", "ACCRUE_CAP", "MAX_LEVEL", "RARITY_RATE",
                 "FODDER_BLOCKS", "FUSE_MAX_TIER", "REROLL_ESSENCE", "REROLL_TIMBER", "REROLL_STONE",
                 "REROLL_ORE", "FUSE_TIMBER", "FUSE_STONE", "FUSE_ORE", "FUSE_ESSENCE"):
        m = re.search(r"\b" + name + r"\s*=\s*(\d+)", js)
        ok(m is not None, f"pets.js never declares {name} (a ReferenceError at runtime)")
        if m:
            ok(int(m.group(1)) == getattr(P, name),
               f"pets.js {name}={m.group(1)} but the contract says {getattr(P, name)}")
    for name, raw in (("BUILD_FEE", P.BUILD_FEE), ("REROLL_FEE", P.REROLL_FEE), ("FUSE_FEE", P.FUSE_FEE)):
        m = re.search(r"\b" + name + r"\s*=\s*(\d+)n", js)
        ok(m is not None, f"pets.js never declares {name}")
        if m:
            ok(int(m.group(1)) == raw, f"pets.js {name}={m.group(1)} but the contract says {raw}")


for t in (test_trade_gates_who_can_build_and_work,
          test_production_is_lazy_capped_and_paid_to_the_owner,
          test_changing_the_terms_banks_the_old_terms_first,
          test_fodder_feeds_the_barn_and_is_actually_spent,
          test_gear_is_points_on_real_stats_and_exactly_reversible,
          test_gear_shows_up_in_the_arena,
          test_upgrades_cost_materials_and_cannot_be_half_paid,
          test_reroll_costs_essence_keeps_the_item_and_only_off_the_pet,
          test_fusing_absorbs_junk_but_cannot_craft_the_rarest_gear,
          test_reroll_also_spends_materials,
          test_client_constants_match_the_contract):
    t()
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
