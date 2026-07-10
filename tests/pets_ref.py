# tests/pets_ref.py — the SINGLE Python reference for every chance formula in the NADO Pets contract.
# tests/test_pets_contract.py proves the bytecode equals these functions; tests/pets_js_crosscheck_gen.py
# proves static/pets-genes.js (what the browser shows) equals them too. Change a formula in one place only.
import json, hashlib

DIE_PCT = 20   # battle loser's death chance, %

def vm_hash(v):
    return int.from_bytes(hashlib.blake2b(json.dumps(v, sort_keys=True).encode(), digest_size=32).digest(), "big")

def ref_gene(bh, b, pid):       return vm_hash(bh[b] + bh[b + 1] + pid)
def ref_species(gene):          r = gene % 100; return 1 + (r >= 70) + (r >= 95)
def ref_stat(gene, sp, i):      return vm_hash(gene + 1000 + i) % 60 + 1 + (sp - 1) * 15
def ref_power(gene, sp):        return sum(ref_stat(gene, sp, i) for i in range(10))
def ref_train_roll(bh, th, pid, i): return vm_hash(bh[th] + bh[th + 1] + pid * 16 + i) % 100

def ref_train_ok(roll, cur, sp):
    K = 10 + 30 * sp               # the rarity-scaled limit function: rarer species train easier
    return roll * (K + cur) < 100 * K

def ref_battle(bh, wh, bid, pwa, pwb):
    q = bh[wh] + bh[wh + 1] + bid * 8
    sa, sb = pwa * (75 + vm_hash(q + 1) % 100), pwb * (75 + vm_hash(q + 2) % 100)
    return (sa > sb), (vm_hash(q + 3) % 100 < DIE_PCT)     # (A wins?, loser dies?)
