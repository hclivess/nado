"""Every contract assembles unchanged for the old VM, and every contract assembles for the new one.

The assembler and the 27 builders take an instruction set (zkvmasm.ISAS: "v1" = zkvm.py, live; "v2" = the gen-29 256-bit
zkvm2.py, Goldilocks retirement G3). A contract's code is part of its cid and of every settled root, so the live
output must not move by a byte:
  1. build() (the default) equals build("v1") for all 27 contracts, and v1 code still uses the alghash round opcodes
     and the RANGE-guarded compare — the old machine, exactly;
  2. build("v2") passes zkvm2.validate_code for all 27, contains no alghash round opcode, and its compares carry no
     RANGE guard the source did not write;
  3. the same source drives both: the two builds of a contract differ only in what the ISA changes (hash rounds and
     macro RANGE guards), so a contract's logic cannot drift between them.

Run: python3 tests/test_every_contract_assembles_unchanged_for_the_old_vm.py
"""
import _harness
HOME = _harness.isolate("nado-test-asm-isa-")
import importlib
import os

from execnode import zkvm, zkvm2, zkvmasm

T = _harness.Report()
GAMES = sorted(f[:-3] for f in os.listdir(os.path.join(_harness.ROOT, "execnode", "games"))
               if f.endswith(".py") and not f.startswith("_") and f not in ("deploy.py", "redeploy.py"))
T.check("27 contracts are built here", len(GAMES) == 27, GAMES)
HR = {op for op in zkvm.OPS if op.startswith("HR")}

same, v2_ok, v2_clean, logic = [], [], [], []
for g in GAMES:
    mod = importlib.import_module("execnode.games." + g)
    d, v1, v2 = mod.build(), mod.build("v1"), mod.build("v2")
    if d == v1:
        same.append(g)
    try:
        zkvm2.validate_code(v2)
        v2_ok.append(g)
    except zkvm2.ZkVMError:
        pass
    ops2 = [i[0] for prog in v2.values() for i in prog]
    if not any(o in HR for o in ops2):
        v2_clean.append(g)
    # strip what the ISA changes from v1; what remains must equal v2 instruction for instruction (jump targets aside)
    for m in v1:
        if m in getattr(mod, "ISA_DIVERGENT_METHODS", ()):
            continue                                       # declared by the builder, with its reason, beside the method
        p1 = [i for i in v1[m] if i[0] not in HR]
        # macro RANGE guards: a RANGE pair directly before an LT
        keep = []
        for k, ins in enumerate(p1):
            if ins[0] == "RANGE" and ((k + 2 < len(p1) and p1[k + 2][0] == "LT") or (k + 1 < len(p1) and p1[k + 1][0] == "LT")):
                continue
            keep.append(ins)
        a = [(o, d_, s_) for o, d_, s_, _ in keep]
        b = [(o, d_, s_) for o, d_, s_, _ in v2[m]]
        if a != b:
            logic.append((g, m))
T.check("1. build() is build('v1') for every contract (the live code does not move)", len(same) == 27,
        sorted(set(GAMES) - set(same)))
hashing = [g for g in GAMES if any(i[0] == "HINIT" for prog in importlib.import_module("execnode.games." + g).build().values()
                                    for i in prog)]
T.check("1b. every contract that hashes still uses the alghash round opcodes in v1",
        all(any(i[0] in HR for prog in importlib.import_module("execnode.games." + g).build().values() for i in prog)
            for g in hashing) and len(hashing) >= 15, len(hashing))
T.check("2a. build('v2') passes zkvm2's deploy gate for every contract", len(v2_ok) == 27, sorted(set(GAMES) - set(v2_ok)))
T.check("2b. no v2 build contains an alghash round opcode", len(v2_clean) == 27, sorted(set(GAMES) - set(v2_clean)))
T.check("3. the two builds differ only in what the ISA changes (hash rounds, macro RANGE guards), outside the methods a "
        "builder declares in ISA_DIVERGENT_METHODS", not logic, logic[:5])
declared = {g: getattr(importlib.import_module("execnode.games." + g), "ISA_DIVERGENT_METHODS", ()) for g in GAMES}
T.check("3b. the declared per-ISA methods are exactly pets' hatch and gene-roll readers (the roll table), hexholm/stormhold/scrapline.reveal and otc.post/settle (each a reviewed port)",
        {g: m for g, m in declared.items() if m} == {"pets": ("hatch", "train_resolve", "resolve_battle", "combine", "upgrade", "staff", "collect"), "hexholm": ("reveal",), "stormhold": ("reveal",), "scrapline": ("reveal",),
                                                     "otc": ("post", "settle")},
        {g: m for g, m in declared.items() if m})
from execnode.games import scrapline as _scr, stormhold as _sto
T.check("3c. scrapline's v2 reveal is stormhold's reviewed port, instruction for instruction (it reuses the source)",
        _scr.build("v2")["reveal"] == _sto.build("v2")["reveal"] and _scr.build("v1")["reveal"] == _sto.build("v1")["reveal"])
T.check("the ISA list is v1 and v2", zkvmasm.ISAS == ("v1", "v2"))
T.done("ALL PASS — every contract assembles unchanged for the old VM and cleanly for the new one")
