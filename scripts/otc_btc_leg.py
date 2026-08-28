#!/usr/bin/env python3
"""Bitcoin leg of the OTC cross-chain swap (doc/dex-bridge.md §6.5) — the P2WSH HTLC, self-contained.

Builds the standard two-branch witness script, its bech32 P2WSH address, and fully-signed claim/refund
transactions (BIP143 sighash, libsecp via coincurve, no Core wallet involvement):

    OP_IF     OP_SHA256 <H> OP_EQUALVERIFY <claim_pub> OP_CHECKSIG
    OP_ELSE   <T2> OP_CHECKLOCKTIMEVERIFY OP_DROP <refund_pub> OP_CHECKSIG
    OP_ENDIF

`H` is the SAME 32-byte SHA-256 hashlock the otc contract bound at post — that is the whole cross-chain
interface. The claim witness carries the preimage `s`; `extract_secret` reads it back out of a claim tx the
way a counterparty/watchtower does, which is what lets the NADO side settle. Nothing here is NADO consensus
code: these are reference legs the wallet constructs and *reads* (used by tests/test_otc_swap_e2e.py against
regtest).
"""
import hashlib
try:
    from coincurve import PrivateKey          # signing only; the watchtower imports this module for extract_secret alone
except ImportError:                             # noqa: E722
    PrivateKey = None

# ---- hashes / encodings ---------------------------------------------------------------------------------
sha256 = lambda b: hashlib.sha256(b).digest()
sha256d = lambda b: sha256(sha256(b))
hash160 = lambda b: hashlib.new("ripemd160", sha256(b)).digest()


def ser_compact(n):
    if n < 0xfd: return bytes([n])
    if n <= 0xffff: return b"\xfd" + n.to_bytes(2, "little")
    if n <= 0xffffffff: return b"\xfe" + n.to_bytes(4, "little")
    return b"\xff" + n.to_bytes(8, "little")


def push(data):
    n = len(data)
    assert n <= 75, "only direct pushes needed here"
    return bytes([n]) + data


def scriptnum(n):
    """Minimal CScriptNum encoding (for the CLTV operand)."""
    assert n > 0
    out = bytearray()
    while n:
        out.append(n & 0xff); n >>= 8
    if out[-1] & 0x80:
        out.append(0x00)
    return bytes(out)

# ---- bech32 (BIP-173 reference, vendored — segwit v0 only) ----------------------------------------------
_B32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _b32_polymod(values):
    gen = (0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3)
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1ffffff) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _b32_hrp_expand(hrp):
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _convertbits(data, frombits, tobits, pad=True):
    acc = bits = 0; ret = []
    maxv = (1 << tobits) - 1
    for value in data:
        acc = (acc << frombits) | value; bits += frombits
        while bits >= tobits:
            bits -= tobits; ret.append((acc >> bits) & maxv)
    if pad and bits:
        ret.append((acc << (tobits - bits)) & maxv)
    return ret


def bech32_encode(hrp, witver, witprog):
    data = [witver] + _convertbits(list(witprog), 8, 5)
    values = _b32_hrp_expand(hrp) + data
    poly = _b32_polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1        # bech32 (v0), not bech32m
    checksum = [(poly >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(_B32[d] for d in data + checksum)

# ---- the HTLC itself ------------------------------------------------------------------------------------
OP_IF, OP_ELSE, OP_ENDIF = 0x63, 0x67, 0x68
OP_DROP, OP_SHA256, OP_EQUALVERIFY, OP_CHECKSIG, OP_CLTV = 0x75, 0xa8, 0x88, 0xac, 0xb1


def htlc_script(H, claim_pub, refund_pub, locktime):
    """The witness script. H: 32B hashlock; pubs: 33B compressed; locktime: absolute (height or unixtime)."""
    assert len(H) == 32 and len(claim_pub) == 33 and len(refund_pub) == 33
    return (bytes([OP_IF, OP_SHA256]) + push(H) + bytes([OP_EQUALVERIFY]) + push(claim_pub)
            + bytes([OP_CHECKSIG, OP_ELSE]) + push(scriptnum(locktime)) + bytes([OP_CLTV, OP_DROP])
            + push(refund_pub) + bytes([OP_CHECKSIG, OP_ENDIF]))


def p2wsh_address(script, hrp="bcrt"):
    """bech32 v0 address of the HTLC ('bcrt' regtest / 'tb' testnet / 'bc' mainnet)."""
    return bech32_encode(hrp, 0, sha256(script))


def p2wpkh_script(pub):
    return b"\x00\x14" + hash160(pub)


def p2wsh_script(script):
    return b"\x00\x20" + sha256(script)

# ---- BIP143 spend construction --------------------------------------------------------------------------
def _bip143_sighash(txid_le, vout, script_code, amount_sat, out_script, out_sat, locktime, sequence):
    prevout = txid_le + vout.to_bytes(4, "little")
    outputs = out_sat.to_bytes(8, "little") + ser_compact(len(out_script)) + out_script
    pre = (b"\x02\x00\x00\x00"                                   # nVersion = 2
           + sha256d(prevout)                                    # hashPrevouts (single input)
           + sha256d(sequence.to_bytes(4, "little"))             # hashSequence
           + prevout
           + ser_compact(len(script_code)) + script_code
           + amount_sat.to_bytes(8, "little")
           + sequence.to_bytes(4, "little")
           + sha256d(outputs)                                    # hashOutputs (single output)
           + locktime.to_bytes(4, "little")
           + b"\x01\x00\x00\x00")                                # SIGHASH_ALL
    return sha256d(pre)


def _serialize(txid_le, vout, sequence, out_script, out_sat, witness, locktime):
    body = (b"\x02\x00\x00\x00" + b"\x00\x01"                    # version 2, segwit marker+flag
            + b"\x01" + txid_le + vout.to_bytes(4, "little") + b"\x00" + sequence.to_bytes(4, "little")
            + b"\x01" + out_sat.to_bytes(8, "little") + ser_compact(len(out_script)) + out_script
            + ser_compact(len(witness)) + b"".join(ser_compact(len(w)) + w for w in witness)
            + locktime.to_bytes(4, "little"))
    return body


def _spend(script, branch_witness, priv_hex, txid_hex, vout, amount_sat, out_script, fee_sat,
           locktime, sequence):
    """Shared claim/refund builder: sign the single-input single-output spend, splice the branch stack."""
    key = PrivateKey(bytes.fromhex(priv_hex))
    txid_le = bytes.fromhex(txid_hex)[::-1]
    out_sat = amount_sat - fee_sat
    assert out_sat > 0, "fee eats the whole output"
    digest = _bip143_sighash(txid_le, vout, script, amount_sat, out_script, out_sat, locktime, sequence)
    sig = key.sign(digest, hasher=None) + b"\x01"                # DER low-S + SIGHASH_ALL
    witness = [sig] + branch_witness + [script]
    return _serialize(txid_le, vout, sequence, out_script, out_sat, witness, locktime).hex()


def claim_tx(script, secret, priv_hex, txid_hex, vout, amount_sat, out_script, fee_sat=1000):
    """Spend the HTLC through the claim branch, REVEALING `secret` on-chain (witness = sig, s, 1, script)."""
    return _spend(script, [secret, b"\x01"], priv_hex, txid_hex, vout, amount_sat, out_script,
                  fee_sat, locktime=0, sequence=0xfffffffd)   # RBF-signalling, byte-identical to btcsign.js


def refund_tx(script, locktime, priv_hex, txid_hex, vout, amount_sat, out_script, fee_sat=1000):
    """Spend through the refund branch — only valid once the chain reaches `locktime` (CLTV needs
    nLockTime set and a sequence below final)."""
    return _spend(script, [b""], priv_hex, txid_hex, vout, amount_sat, out_script,
                  fee_sat, locktime=locktime, sequence=0xfffffffe)


def extract_secret(tx_hex, H):
    """Read the revealed preimage out of a claim transaction the way a watchtower does: the witness item
    whose SHA-256 equals the hashlock. Returns 64-hex or None."""
    raw = bytes.fromhex(tx_hex)
    for i in range(len(raw) - 32):
        cand = raw[i:i + 32]
        if sha256(cand) == H:
            return cand.hex()
    return None


# ---- CLI: everything a maker/taker needs to run the BTC side of an otc order by hand -------------------
def _cli():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("address", help="print the HTLC witness script + P2WSH address for an order's hashlock")
    for n, h in (("--hashlock", "the order's 64-hex SHA-256 hashlock"), ("--claim-pub", "claimant 33B pubkey hex"),
                 ("--refund-pub", "refundee 33B pubkey hex")):
        a.add_argument(n, required=True, help=h)
    a.add_argument("--locktime", required=True, type=int, help="absolute locktime T2 (height or unixtime)")
    a.add_argument("--hrp", default="bc", help="bc mainnet / tb testnet / bcrt regtest")
    c = sub.add_parser("claim", help="build the signed claim tx (REVEALS the secret on Bitcoin)")
    r = sub.add_parser("refund", help="build the signed refund tx (valid at/after the locktime)")
    for p in (c, r):
        for n in ("--hashlock", "--claim-pub", "--refund-pub"):
            p.add_argument(n, required=True)
        p.add_argument("--locktime", required=True, type=int)
        p.add_argument("--priv", required=True, help="YOUR key hex (claimant for claim, refundee for refund)")
        p.add_argument("--txid", required=True, help="funding txid")
        p.add_argument("--vout", required=True, type=int)
        p.add_argument("--amount", required=True, type=int, help="the HTLC output value in sat")
        p.add_argument("--dest-pub", required=True, help="33B pubkey hex the spend pays (as P2WPKH)")
        p.add_argument("--fee", type=int, default=1000)
    c.add_argument("--secret", required=True, help="the 64-hex swap secret")
    x = sub.add_parser("extract", help="read the revealed secret out of a claim tx")
    x.add_argument("--hashlock", required=True)
    x.add_argument("--tx", required=True, help="raw claim tx hex")
    o = ap.parse_args()
    if o.cmd == "extract":
        print(extract_secret(o.tx, bytes.fromhex(o.hashlock)) or "NOT FOUND")
        return
    sc = htlc_script(bytes.fromhex(o.hashlock), bytes.fromhex(o.claim_pub), bytes.fromhex(o.refund_pub), o.locktime)
    if o.cmd == "address":
        print("witness_script:", sc.hex())
        print("address:       ", p2wsh_address(sc, o.hrp))
        return
    dest = p2wpkh_script(bytes.fromhex(o.dest_pub))
    if o.cmd == "claim":
        print(claim_tx(sc, bytes.fromhex(o.secret), o.priv, o.txid, o.vout, o.amount, dest, o.fee))
    else:
        print(refund_tx(sc, o.locktime, o.priv, o.txid, o.vout, o.amount, dest, o.fee))


if __name__ == "__main__":
    _cli()
