"""Every contract builds byte-identical code for the 256-bit VM — the code generation 29 deployed.

A contract's code is part of its cid, of its code leaf in every settled exec root, and of what the carry matches a
contract against (tools/carry.module_of: the module whose build() IS the contract's code). G9 slice 3b deleted the field
VM (execnode/zkvm.py) and with it the assembler's v1 ISA, every builder's `isa=` switch, the v1 branches of the pets,
otc, faucet, hexholm, stormhold and scrapline builders and the field digest the faucet's source baked in. None of that
may move a single instruction of what build() emits, so:
  1. every game module's build() hashes to the value build() (= build("v2")) gave on deployed main 2cb36e73, before the
     deletion — all 27 of them; and the zkvm_examples library likewise;
  2. every build passes zkvm2's deploy gate and carries no alghash round opcode;
  3. the builders and the assembler take no instruction-set argument (a second ISA cannot come back unnoticed).
A pin that moves is a contract that would no longer match its deployed code: fix the builder, never the pin, unless the
change is a deliberate, gated contract upgrade.

Run: python3 tests/test_every_contract_builds_byte_identical_for_the_256_bit_vm.py
"""
import _harness
HOME = _harness.isolate("nado-test-build-pins-")
import hashlib
import importlib
import inspect
import json
import os

from execnode import zkvm2, zkvmasm, zkvm_examples

T = _harness.Report()

# sha256(canonical JSON)[:32] of build() on 2cb36e73 (deployed main), recorded before G9 slice 3b touched a builder
PINS = {
    "autogame": "a944aa98febeaa4506033e917d151194", "battleship": "ea71027c6c935d8e11ad157c58449680",
    "bet": "ef898a89e973b4c1fd2dfe088c727a38", "blackjack": "cb5455a3532f7919f5dfe8b96b65f4b9",
    "chess": "0596155c4dd08f436cca88ba815407ce", "coinflip": "137d008be69ab3a2357e4c5836cbbc5c",
    "connect4": "dbfd066125cdc68d799d6e5974ab719c", "dex": "4c0d493a50642aec6df80b08185c17ba",
    "dice": "4c0c7edabfba8e1611723a6fa91fe093", "farkle": "d4d09e98decb5b90b3e9d601d17aac46",
    "faucet": "a7727680bfb43efbb27029d72519b9da", "hamster": "c3fa475444686ec0e07e3d860603e6c8",
    "hexholm": "fb2beedd7d9512612bedf6b66d48aadb", "holdem": "33a9aa64ca61443425855809ec5b2d03",
    "lend": "578d7a1f2cd7a53396f073f69921dade", "mines": "3da1aee0859528f17e6bd36caed7ea2c",
    "otc": "e560afe7f1165ef6384049cccec09cd9", "pets": "18f3cf11760a07b9709292abbf678550",
    "pool": "c963f9f838439b87dc2db2d6996a98ac", "reserve": "eab74c5320347bc2e5134e90eac510f3",
    "reversi": "bd299b5cea3592aec21e71b70481b7b4", "roulette": "46ea1f569de58b423cead372ee448617",
    "scrapline": "b1691cb688a429020bfd2ccf9974999c", "slots": "6524fab380bdf95a2aaa06c0aec6cd17",
    "sovereign": "5679201159937d06742117e164d2c2c2", "stormhold": "cfb003d37775201200fe1e89ea0d348c",
    "tictactoe": "c7d3b61a51537a07c35e7dd8a9330cfb",
}
EXAMPLE_PINS = {"commit_box": "e614388f12a6b5c7105dd3c3f57ca1bf", "counter": "f6f94cddd27ea718cf4a9d0d11486c86",
                "tip_jar": "16e5516fa26cc7ef74d048f6c7196640"}


def h(code):
    return hashlib.sha256(json.dumps(code, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


GAMES = sorted(f[:-3] for f in os.listdir(os.path.join(_harness.ROOT, "execnode", "games"))
               if f.endswith(".py") and not f.startswith("_") and f not in ("deploy.py", "redeploy.py"))
T.check("1. the 27 contracts are the pinned ones", GAMES == sorted(PINS), sorted(set(GAMES) ^ set(PINS)))
builds = {g: json.loads(json.dumps(importlib.import_module("execnode.games." + g).build())) for g in GAMES}
moved = {g: h(c) for g, c in builds.items() if h(c) != PINS.get(g)}
T.check("1. every build() is byte-identical to the code gen 29 deployed (2cb36e73)", not moved, moved)
ex = {k: h(v["code"]) for k, v in zkvm_examples.LIBRARY.items()}
T.check("1. ...and so is every zkvm_examples contract", ex == EXAMPLE_PINS, ex)

bad, rounds = [], []
for g, code in builds.items():
    try:
        zkvm2.validate_code(code)
    except zkvm2.ZkVMError as e:
        bad.append((g, str(e)))
    if any(i[0].startswith("HR") for prog in code.values() for i in prog):
        rounds.append(g)
T.check("2. every build passes zkvm2's deploy gate and carries no alghash round opcode", not bad and not rounds,
        (bad, rounds))

with_isa = [g for g in GAMES if inspect.signature(importlib.import_module("execnode.games." + g).build).parameters]
T.check("3. no builder takes an instruction-set argument", not with_isa, with_isa)
T.check("3. ...nor does the assembler", list(inspect.signature(zkvmasm.assemble).parameters) == ["text"]
        and list(inspect.signature(zkvmasm.assemble_contract).parameters) == ["methods"])
T.done("ALL PASS — every contract builds byte-identical code for the 256-bit VM")
