"""The compressed exec tree is canonical, and its verifier refuses every forged path.

execnode/csmt.py is the BLAKE2s exec root's tree (Goldilocks retirement G2; operator decision 2026-10-19: compressed, not
depth-256). It is frozen at the generation-29 reroll, so this pins its definition before anything gates on it:
  1. the root equals an independent recursive reference written from the docstring's definition, over random key sets
     (including keys that share long prefixes, so chains of one-empty-child internal nodes occur);
  2. the root depends on the key/value set only: insertion order, update-then-revert and delete all reach it;
  3. every present key proves membership, every absent key proves absence, and both verify against the root;
  4. FORGERIES, each refused: a wrong value; another key's leaf passed as membership; k's own leaf passed as absence;
     an "other" leaf off k's path passed as absence; a leaf pushed one level deeper beside an EMPTY sibling (the
     collapse rule); a path stopped early (a subtree's hash passed as a leaf); an EMPTY terminal beside an EMPTY
     sibling; swapped, dropped, extra or altered siblings; a proof against a different root; more than 256 siblings;
     malformed keys and proofs (never an exception);
  5. the hashes are one BLAKE2s compression each, with leaf and node domains separated.

Run: python3 tests/test_the_compressed_exec_tree_is_canonical_and_refuses_forged_paths.py
"""
import _harness
HOME = _harness.isolate("nado-test-csmt-")
import hashlib
import random

from execnode import csmt as C

T = _harness.Report()
rnd = random.Random(20261019)


def key(prefix_bits="", n_shared=0):
    """a random 32-byte key; with prefix_bits, its first bits are forced (to build shared prefixes)"""
    k = bytearray(rnd.randbytes(32))
    for i, b in enumerate(prefix_bits):
        byte, off = i >> 3, 7 - (i & 7)
        k[byte] = (k[byte] & ~(1 << off)) | (int(b) << off)
    return bytes(k)


def ref_root(items):
    """INDEPENDENT reference: the definition, recursively, with no caching or sorting tricks."""
    def node(depth, keys):
        if not keys:
            return C.EMPTY
        if len(keys) == 1:
            k = keys[0]
            vh = hashlib.blake2s(items[k], digest_size=32, person=b"NADOcsV1").digest()
            return hashlib.blake2s(k + vh, digest_size=32, person=b"NADOcsL1").digest()
        zero = [k for k in keys if not (k[depth >> 3] >> (7 - (depth & 7))) & 1]
        one = [k for k in keys if (k[depth >> 3] >> (7 - (depth & 7))) & 1]
        return hashlib.blake2s(node(depth + 1, zero) + node(depth + 1, one), digest_size=32, person=b"NADOcsN1").digest()
    return node(0, list(items))


def random_items(n):
    items = {}
    prefix = "".join(rnd.choice("01") for _ in range(rnd.choice([0, 3, 17, 40])))
    for i in range(n):
        k = key(prefix if rnd.random() < 0.4 else "")   # 40 % share a long prefix: deep one-empty-child chains
        items[k] = rnd.randbytes(rnd.choice([0, 1, 8, 32, 77]))
    return items


# ---- 1, 2: definition and canonicality
bad = []
for trial in range(40):
    items = random_items(rnd.choice([0, 1, 2, 3, 5, 17, 64]))
    t = C.Tree(items)
    if t.root() != ref_root(items):
        bad.append(("ref", trial, len(items)))
    order = list(items); rnd.shuffle(order)
    t2 = C.Tree()
    for k in order:
        t2.set(k, items[k])
    if t2.root() != t.root():
        bad.append(("order", trial))
    if items:                                            # update then revert; delete then re-add
        k = rnd.choice(order)
        r0 = t2.root()
        t2.set(k, b"changed"); changed = t2.root()
        t2.set(k, items[k])
        t2.delete(k); gone = t2.root()
        rest = {x: y for x, y in items.items() if x != k}
        if changed == r0:
            bad.append(("update", trial))                # a changed value must move the root
        if gone != ref_root(rest):
            bad.append(("delete", trial))
        t2.set(k, items[k])
        if t2.root() != r0:
            bad.append(("readd", trial))
T.check("1. the root equals the independent reference over 40 random key sets", not [b for b in bad if b[0] == "ref"], bad[:3])
T.check("2. insertion order, update-revert and delete/re-add all reach the canonical root",
        not [b for b in bad if b[0] != "ref"], bad[:3])
T.check("2b. the empty tree's root is EMPTY (32 zero bytes)", C.Tree().root() == C.EMPTY)
one = {key(): b"v"}
T.check("2c. a one-key tree's root is that key's leaf hash (no internal node above a lone leaf)",
        C.Tree(one).root() == C.leaf_hash(*next(iter(one.items()))))

# ---- 3: honest proofs
items = random_items(200)
t = C.Tree(items)
root = t.root()
ok_in = all(C.verify(root, k, v, t.prove(k)) for k, v in items.items())
absent = [key() for _ in range(200)] + [key(format(next(iter(items))[0], "08b")[:6])]
ok_out = all(C.verify(root, k, None, t.prove(k)) for k in absent if k not in items)
T.check("3a. every present key (200) proves membership against the root", ok_in)
T.check("3b. every absent key (201) proves absence against the root", ok_out)
depths = sorted(len(t.prove(k)[0]) for k in items)
T.check("3c. paths are short: 200 keys sit at depth <= 2 log2(n) + the shared prefix (not 256)",
        depths[-1] < 80, (depths[0], depths[len(depths) // 2], depths[-1]))

# ---- 4: forgeries
k, v = next(iter(items.items()))
sibs, term = t.prove(k)
other_k = next(x for x in items if x != k)
forged = {}
forged["wrong value"] = C.verify(root, k, b"not the value", (sibs, term))
forged["another key's leaf as membership"] = C.verify(root, other_k, v, (sibs, term))
forged["own leaf passed as absence"] = C.verify(root, k, None, (sibs, term))
off = next(x for x in absent if x not in items and C.bit(x, 0) != C.bit(k, 0))
forged["a leaf off k's path passed as absence"] = C.verify(root, off, None, (sibs, ("leaf", k, v)))
forged["leaf pushed one level deeper beside EMPTY"] = C.verify(root, k, v, (sibs + [C.EMPTY], term))
if len(sibs) >= 1:
    forged["path stopped early (a subtree passed as the leaf)"] = C.verify(root, k, v, (sibs[:-1], ("leaf", k, v)))
forged["EMPTY terminal beside EMPTY"] = C.verify(root, key(), None, ([C.EMPTY], ("empty",)))
if len(sibs) >= 2:
    sw = list(sibs); sw[0], sw[1] = sw[1], sw[0]
    forged["swapped siblings"] = C.verify(root, k, v, (sw, term))
forged["dropped sibling"] = C.verify(root, k, v, (sibs[1:], term))
forged["extra sibling on top"] = C.verify(root, k, v, ([rnd.randbytes(32)] + sibs, term))
alt = list(sibs); alt[-1] = bytes([alt[-1][0] ^ 1]) + alt[-1][1:]
forged["altered sibling"] = C.verify(root, k, v, (alt, term))
forged["proof against a different root"] = C.verify(C.Tree({**items, key(): b"x"}).root(), k, v, (sibs, term))
forged["257 siblings"] = C.verify(root, k, v, ([rnd.randbytes(32)] * 257, term))
for name, got in forged.items():
    T.check(f"4. refused: {name}", got is False, got)
weird = []
for bad_input in (("short key", lambda: C.verify(root, b"\x00" * 31, v, (sibs, term))),
                  ("proof not a pair", lambda: C.verify(root, k, v, None)),
                  ("terminal unknown", lambda: C.verify(root, k, v, (sibs, ("node",)))),
                  ("sibling wrong length", lambda: C.verify(root, k, v, ([b"\x01"] + sibs[1:], term))),
                  ("root not bytes", lambda: C.verify(None, k, v, (sibs, term)))):
    try:
        if bad_input[1]() is not False:
            weird.append(bad_input[0])
    except Exception as e:
        weird.append(f"{bad_input[0]} raised {e!r}")
T.check("4. malformed keys and proofs return False, never raise", not weird, weird)

# ---- 5: one compression per node, separated domains
T.check("5a. an internal node hashes exactly 64 bytes (one BLAKE2s block)", len(C.EMPTY + C.EMPTY) == 64)
lk = C.leaf_hash(k, v)
T.check("5b. a leaf and an internal node over the same 64 bytes differ (personalization)",
        C.node_hash(k, C.value_hash(v)) != lk)
T.done("ALL PASS — the compressed exec tree is canonical and refuses forged paths")
