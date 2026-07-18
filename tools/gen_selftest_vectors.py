"""
Regenerate the browser wallet's self-test VEC block (static/interface.js) from the PYTHON side —
the authoritative implementation — after any address-format / domain-tag / chain_id change.
Prints a ready-to-paste JS object body. Mines the registration-PoW vector nonce (~1-2 min once).

  PYTHONPATH=<repo> python3 tools/gen_selftest_vectors.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hashing import blake2b_hash, canonical_bytes
from ops.address_ops import make_address, make_checksum
from ops.mining_ops import registration_pow_target, registration_pow_hash
from ops.transaction_ops import create_txid
from protocol import ADDRESS_PREFIX, CHAIN_ID, DOMAIN_REGISTER

PUB = "96381e3725f85cfe0ab8de17623957b4565ca9b04d37b903075f2723600c21e3"
FIXPUB = "1e9f9f319a9ee0f98b3147a67dca40e7296d5e847b34ad683692f39264379f38"
CK_BODY = "18c3afa286439e7ebcb284710dbd4ae42bdaf21b80"     # 42-hex checksum-vector body
RCPT_BODY = "6a7a7a6d26040d8d53ce66343a47347c9b79e814c6"   # 42-hex transfer-recipient body

addr = make_address(PUB)
faddr = make_address(FIXPUB)
rcpt = ADDRESS_PREFIX + RCPT_BODY
rcpt = rcpt + make_checksum(rcpt)

target = registration_pow_target()
nonce = 0
while registration_pow_hash(addr, nonce) >= target:
    nonce += 1

def tx_vec(extra):
    body = dict(sender=faddr, amount=extra.pop("amount", 0), timestamp=1700000000, data=extra.pop("data", ""),
                nonce="fixednonc", public_key=FIXPUB, max_block=12345, chain_id=CHAIN_ID,
                fee=extra.pop("fee", 0), **extra)
    txid = create_txid(body)
    canon = canonical_bytes(body).decode()
    return dict(body, txid=txid), canon

reg, reg_c = tx_vec(dict(recipient="register", pow_nonce=2108331))
hb, hb_c = tx_vec(dict(recipient="heartbeat", epoch=205))
tr, tr_c = tx_vec(dict(recipient=rcpt, amount=123456, data="hello world", fee=1000))

def js(v):
    return json.dumps(v, ensure_ascii=True, separators=(", ", ": "))

print(f"""  hash_register_list: {js(blake2b_hash([DOMAIN_REGISTER, ADDRESS_PREFIX + "TEST", 5]))},
  checksum_string_size2: {js(make_checksum(ADDRESS_PREFIX + CK_BODY))},
  checksum_body: {js(CK_BODY)},
  make_address_pub: {js(PUB)},
  make_address_out: {js(addr)},
  hash_link_a_b: "d803f13f94cb4546f8f9d50368dfbb44ea46aa3db56fecfa2570a3ebf90f3a13",
  torture_canonical: "{{\\"a\\":\\"h\\\\u00e9llo \\\\\\"x\\\\\\"\\\\n\\\\t/end\\",\\"m\\":[3,2,{{\\"big\\":12345678901234567890,\\"k\\":true}}],\\"n\\":null,\\"unicode_key_\\\\u00fc\\":\\"\\\\u2603 snowman\\",\\"z\\":1}}",
  torture_hash: "69029840259d7c85d5c3e61f09abc352d0554c9b4320ef7d59bb6942647b840c",
  bigobj_canonical: "{{\\"amount\\":99999999999999999999,\\"x\\":9007199254740993}}",
  bigobj_hash: "8a09e2d0782c39dd1522f8a83c5338d2960d1b9710ec5c18e66d6cc20354de20",
  pow_address: {js(addr)},
  pow_nonce: {nonce},
  pow_target_str: {js(str(registration_pow_target()))},
  pow_hash_int_str: {js(str(registration_pow_hash(addr, nonce)))},
  fixed_priv: "4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a4d3c2b1a", // 32-byte ML-DSA-44 seed
  // Tx vectors carry NO signature (ML-DSA is hedged); only txid/canonical are comparable.
  // REGENERATE via tools/gen_selftest_vectors.py after ANY field/format/tag/chain_id change.
  register_tx: {js(reg)},
  register_canonical: {js(reg_c)},
  heartbeat_tx: {js(hb)},
  heartbeat_canonical: {js(hb_c)},
  transfer_tx: {js(tr)},
  transfer_canonical: {js(tr_c)},""")
