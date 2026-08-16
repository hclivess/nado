"""
SHIELDED CONTRACTS — private application state (ROADMAP Track F).

WHAT THIS IS. The shielded pool (execnode/shielded_field.py) hides *values*: a note is (value, owner, rho)
and the one invariant its circuit knows is value conservation. Every contract deployed today is the opposite
— public bytecode, public storage, public inputs. This module is the missing middle: **private state with
public code**. A contract's private state lives in typed NOTES the user holds; a state transition SPENDS
notes (revealing nullifiers) and CREATES notes (revealing commitments), and nothing else about it is visible.

It is deliberately NOT a second pool. It reuses the pool's exact machinery — alghash over Goldilocks, the
fixed-depth Merkle tree whose path folds the way the membership region folds, an append-only commitment tree
with a bounded anchor window, a spent-nullifier set — because the whole point is that the proving,
DA-transport and settlement path that already carries shielded transfers carries these unchanged.

THE THREE DIFFERENCES FROM A VALUE NOTE, and why each one is needed:

  1. A note is TYPED and SCOPED: (cid, kind, fields…, owner, rho). `cid` scopes it to one contract so notes
     can never be moved between apps; `kind` selects which transition predicate applies; `fields` is the
     private state itself, of whatever arity that kind declares.
  2. Conservation is a PER-KIND PREDICATE, not a global law. A value note conserves; a game's hidden-hand
     note doesn't conserve anything, it just has to be well-formed. `PREDICATES` is the whole extension
     point — a new private app is a new kind plus a predicate, not a new pool.
  3. The nullifier binds the COMMITMENT, not the randomness: nf = H(DOM_APPNF, nsk, cm). The value pool
     derives nf = H(nsk, rho) and its own docstring records the consequence — "the SENDER, who chose rho,
     can also compute this — a minor spend-detection leak". Binding cm instead closes that leak here: cm
     commits to the owner, and the sender does not hold nsk, so a sender cannot recognise the spend of a
     note they created. It also makes a nullifier collision across contracts impossible for free, since cid
     is inside cm.

PHASED, exactly like the pool it extends (doc/privacy.md §3), and the seam is the same shape:

  * PHASE 1 (this file): `verify_transition` re-checks openings, membership, nullifier and commitment
    derivation IN THE CLEAR. SOUND — no double-spend, no forged membership, no predicate violation — but
    NOT private, because the witness carries nsk. It is dev/test scaffolding: `CONSENSUS_ALLOW_TRANSPARENT`
    is False and the exec node refuses a transparent witness, so this path can never settle a chain.
  * PHASE 2 (next slice): `proof` is a STARK over the same statement and the verifier sees only `public`.
    The state machine below does not change — only what is behind the seam.

Nothing here is wired into the settled root or the blob dispatcher until its own slice; this module is the
state machine and its verifier, standing alone and fully tested first.
"""
from execnode.stark import field as F, alghash
from hashing import blake2b_hash

# Domain tags for the shielded-CONTRACT note algebra — disjoint from alghash's value-note tags
# (DOM_OWNER/CM/NF/NODE = 1..4) so an app note can never be confused with a pool note under any hash, and
# APPEND ONLY, because a tag number is part of every commitment ever computed under it.
#
# They are DEFINED IN THE CIRCUIT and imported here, not the other way round: the AIR has to absorb the
# same tags this module hashes, and a second copy of a consensus constant is a second thing that can drift.
# The circuit sits lower in the import graph (it must not import the state machine back), so that is the
# end that owns them.
from execnode.stark import appnote_circuit as AC
from execnode.stark.appnote_circuit import DOM_APPCM, DOM_APPNF

TREE_DEPTH = 20                     # 2^20 = 1,048,576 notes per contract. Proving cost is linear in depth,
                                    # so this is the one number to revisit when the membership region's cost
                                    # is measured — it is per-CONTRACT, not per-chain, which is why it can be
                                    # this generous without paying for it on every proof.
ANCHOR_WINDOW = 128                 # recent roots a proof may target, per contract (mirrors the pool)
EMPTY_LEAF = 0

MAX_FIELDS = 16                     # arity ceiling per note — bounds the sponge and therefore the trace
MAX_INPUTS = 4                      # notes one transition may spend
MAX_OUTPUTS = 4                     # notes one transition may create


def _empty_roots(depth):
    """e[i] = root of an all-empty subtree of height i (e[depth] = the empty-tree root)."""
    e = [EMPTY_LEAF]
    for _ in range(depth):
        e.append(alghash.merkle_node(e[-1], e[-1]))
    return e


_EMPTY = _empty_roots(TREE_DEPTH)
EMPTY_ROOT = _EMPTY[TREE_DEPTH]


def cid_element(cid):
    """A contract id (hex string, or the fixed names "faucet"/"sovereign") folded to ONE field element.

    Folded rather than limbed because it is only ever an opaque scope tag here — nothing reconstructs a cid
    from it, and one element keeps it to a single sponge absorption in the circuit. Domain-tagged so the fold
    cannot collide with any other blake2b use in the tree."""
    return int(blake2b_hash(["appcid", str(cid)]), 16) % F.P


def note_commitment(cid, kind, fields, owner, rho):
    """cm = hashn([DOM_APPCM, cid, kind, arity, *fields, owner, rho]).

    ARITY IS BOUND, and it is not redundant. The sponge absorbs a flat sequence, so without an explicit
    length two notes of different shape could in principle be made to absorb the same sequence; binding the
    arity makes the note's shape part of what the commitment commits to, and gives the circuit a public
    handle on how many field absorptions a given kind performs."""
    fields = [int(f) % F.P for f in fields]
    if len(fields) > MAX_FIELDS:
        raise ValueError(f"note arity {len(fields)} exceeds MAX_FIELDS={MAX_FIELDS}")
    return alghash.hashn([DOM_APPCM, cid_element(cid), int(kind) % F.P, len(fields),
                          *fields, int(owner) % F.P, int(rho) % F.P])


def note_nullifier(nsk, cm):
    """nf = hashn([DOM_APPNF, nsk, cm]) — see the module note on why this binds cm and not rho."""
    return alghash.hashn([DOM_APPNF, int(nsk) % F.P, int(cm) % F.P])


def owner_of(nsk):
    """Owner id for a shielded key — the pool's own derivation, reused so ONE key serves both."""
    return alghash.owner_of(int(nsk) % F.P)


# ---- the fixed-depth tree (same shape the membership region folds) -----------------------------------
def tree_root(leaves):
    """Root of the fixed-depth alghash tree over `leaves`, padding short levels with the empty-subtree root."""
    if not leaves:
        return EMPTY_ROOT
    level = list(leaves)
    for d in range(TREE_DEPTH):
        level = [alghash.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _EMPTY[d])
                 for i in range(0, len(level), 2)]
    return level[0]


def tree_path(leaves, pos):
    """(siblings, dirs) for the leaf at `pos`; dirs[i] = bit i of pos (0 = this node is the left child)."""
    sibs, dirs, idx = [], [], pos
    level = list(leaves)
    for d in range(TREE_DEPTH):
        sib = idx ^ 1
        sibs.append(level[sib] if sib < len(level) else _EMPTY[d])
        dirs.append(idx & 1)
        level = [alghash.merkle_node(level[i], level[i + 1] if i + 1 < len(level) else _EMPTY[d])
                 for i in range(0, len(level), 2)]
        idx //= 2
    return sibs, dirs


def fold_path(leaf, sibs, dirs):
    """Fold a membership path to a root — the exact computation the circuit's MEMBERSHIP region performs,
    kept here so the transparent verifier and the eventual AIR can be diffed against one another."""
    acc = int(leaf) % F.P
    for sib, d in zip(sibs, dirs):
        acc = alghash.merkle_node(sib, acc) if d else alghash.merkle_node(acc, sib)
    return acc


# ---- per-kind transition predicates ------------------------------------------------------------------
# THE EXTENSION POINT. A predicate answers one question: given the fields of the notes this transition
# spends and creates, plus the transition's PUBLIC deltas, is this a legal move for this kind of note?
# It never sees owners, randomness or positions — those are the pool's business, not the app's.
KIND_VALUE = 1                      # fields = [amount]: the private per-contract balance note
VALUE_MAX = 1 << 62                 # matches the pool's C-3 in-circuit range bound


def _predicate_value(in_fields, out_fields, public_delta):
    """Conservation for the value note: Σ in + public_delta = Σ out.

    public_delta > 0 means value ENTERS the private state (a public deposit paid into it); < 0 means it
    LEAVES. Sums are taken as INTEGERS, not field elements: mod-P conservation is not conservation, and the
    bound below is what makes the two coincide. It is the same wraparound the pool's C-3 range gadget exists
    to stop — a crafted output near P would balance mod P and mint value from nothing."""
    if any(len(f) != 1 for f in in_fields + out_fields):
        return "value note takes exactly one field (amount)"
    tot_in = sum(f[0] for f in in_fields)
    tot_out = sum(f[0] for f in out_fields)
    if not all(0 <= f[0] < VALUE_MAX for f in in_fields + out_fields):
        return f"note amount outside [0, {VALUE_MAX})"
    if not -VALUE_MAX < public_delta < VALUE_MAX:
        return "public_delta out of range"
    if tot_in + public_delta != tot_out:
        return f"value not conserved: {tot_in} + {public_delta} != {tot_out}"
    return None


PREDICATES = {KIND_VALUE: _predicate_value}

# Kinds whose predicate the CIRCUIT enforces, and therefore the only kinds a proof may be accepted for.
# The two tables are deliberately separate: PREDICATES is what the transparent verifier evaluates, this is
# what an AIR has built in. A kind can legitimately exist in the first and not the second — it simply has
# no proving path yet — but the reverse would mean shipping a circuit for a rule nothing else agrees on.
STARK_KINDS = {KIND_VALUE}


# ---- the pool ----------------------------------------------------------------------------------------
class ShieldedStatePool:
    """Per-contract append-only note trees + one global spent-nullifier set.

    WHY THE NULLIFIER SET IS GLOBAL while the trees are per-contract: the trees are separate so a proof's
    membership cost is bounded by ONE app's history rather than the whole chain's, and so a contract's note
    root is a single record in the settled state. The nullifier set is shared because a nullifier is only
    ever a "has this exact note been spent" question, cm already binds cid, and one set is one record and
    one lookup instead of N."""

    def __init__(self, trees=None, nullifiers=None, anchors=None):
        self.trees = {c: [int(x) % F.P for x in v] for c, v in (trees or {}).items()}
        self.nullifiers = set(int(n) % F.P for n in (nullifiers or []))
        self.anchors = {c: list(v) for c, v in (anchors or {}).items()}
        # Membership index per contract, so has_commitment is O(1) rather than a scan. Derived state only:
        # it is rebuilt from `trees` and never persisted, so it can never disagree with the committed tree.
        self._cmset = {c: set(v) for c, v in self.trees.items()}
        for cid in self.trees:
            self._remember(cid, self.root(cid))

    # -- tree ------------------------------------------------------------------------------------------
    def root(self, cid):
        """Current note-tree root for `cid` (the empty-tree root for a contract with no notes yet)."""
        return tree_root(self.trees.get(cid, []))

    def _remember(self, cid, root):
        a = self.anchors.setdefault(cid, [])
        if root not in a:
            a.append(root)
            if len(a) > ANCHOR_WINDOW:
                del a[:-ANCHOR_WINDOW]

    def knows_root(self, cid, root):
        """Anchor freshness: did this contract's tree recently hold `root`? A proof is built against a root
        that the next block may already have moved past, so a window rather than an equality test."""
        return int(root) % F.P in self.anchors.get(cid, [])

    def append(self, cid, cm):
        """Append a commitment to `cid`'s tree and register the resulting root as a valid anchor."""
        cm = int(cm) % F.P
        self.trees.setdefault(cid, []).append(cm)
        self._cmset.setdefault(cid, set()).add(cm)
        self._remember(cid, self.root(cid))

    def has_commitment(self, cid, cm):
        """Is this exact commitment already in `cid`'s tree?

        A COMMITMENT IS UNIQUE, exactly as a nullifier is, and for a reason that cost real money to find:
        nf = H(nsk, cm) depends only on the note, so two identical commitments share ONE nullifier. Spend
        either and the other becomes permanently unspendable while its value still sits in the contract's
        escrow — a fund lock, and the turnstile invariant breaks with it. Deposits made this reachable: a
        deposit has no nullifier, so its proof and public statement are infinitely replayable, and each
        replay appended the same commitment again. Rejecting the duplicate closes it at the source, costs an
        honest depositor nothing (fresh rho gives a fresh commitment), and applies to every path rather than
        only the one that exposed it."""
        return (int(cm) % F.P) in self._cmset.get(cid, ())

    def position(self, cid, cm):
        """Leaf index of `cm` in `cid`'s tree (the path witness needs it), or None if absent."""
        try:
            return self.trees.get(cid, []).index(int(cm) % F.P)
        except ValueError:
            return None

    # -- nullifiers ------------------------------------------------------------------------------------
    def has_nullifier(self, nf):
        return int(nf) % F.P in self.nullifiers

    def spend(self, nf):
        self.nullifiers.add(int(nf) % F.P)

    def nullifier_digest(self):
        """One digest over the spent set — what the settled root commits, so the record is O(1) in the set."""
        return blake2b_hash(["app_nfset", *sorted(str(n) for n in self.nullifiers)])

    # -- persistence -----------------------------------------------------------------------------------
    def to_dict(self):
        """JSON-safe snapshot — every field int as a STRING (JS loses precision above 2^53)."""
        return {"trees": {c: [str(x) for x in v] for c, v in self.trees.items()},
                "nullifiers": [str(n) for n in sorted(self.nullifiers)],
                "anchors": {c: [str(a) for a in v] for c, v in self.anchors.items()}}

    @classmethod
    def from_dict(cls, d):
        return cls({c: [int(x) for x in v] for c, v in (d.get("trees") or {}).items()},
                   [int(n) for n in d.get("nullifiers", [])],
                   {c: [int(a) for a in v] for c, v in (d.get("anchors") or {}).items()})


# ---- the verifier seam -------------------------------------------------------------------------------
# CONSENSUS SWITCH. Phase 1's witness carries nsk in the clear, which is sound but not private — and a chain
# that accepted it would be publishing spend keys. It exists so the state machine, its tests and its
# integration can be built and frozen before the circuit lands, exactly as the pool's Phase 1 did. The exec
# node must refuse it; this flag is the single place that decision is written down.
CONSENSUS_ALLOW_TRANSPARENT = False


def transition_sighash(public):
    """The bytes a transition's public statement is identified by: contract, spent nullifiers, created
    commitments, the public delta AND the withdrawal destination. Sorted and '|'-joined rather than passed
    as lists, so the digest is byte-identical in the browser port (Python's str(list) is a
    non-reproducible repr).

    withdraw_addr is bound UNCONDITIONALLY — empty string when there is no destination — and that is the
    pool's H-4 fix, learned there and inherited here rather than rediscovered: with the destination outside
    the signed/proven message, a front-runner could copy a victim's blob, swap only the address for their
    own and land it first. The proof still verified, because the address was not in what it committed to,
    and the exit was silently redirected. Unconditional inclusion means signer and verifier can never
    disagree about whether the field was present."""
    return blake2b_hash(["app-sighash", str(public.get("cid")),
                         "|".join(sorted(str(n) for n in public.get("nullifiers", []))),
                         "|".join(sorted(str(c) for c in public.get("out_commitments", []))),
                         str(int(public.get("public_delta", 0))),
                         str(int(public.get("kind", 0))),
                         str(public.get("withdraw_addr") or "")])


def verify_transition(public, proof, pool):
    """Check a private state transition against ONLY its public statement plus `proof`.

    Returns None when the transition is valid, or a human-readable reason when it is not. It NEVER mutates
    the pool — apply_transition does that, and only after this has returned None, so a rejected transition
    can never leave a half-applied nullifier behind. (That ordering is not stylistic: the pool's own
    apply_transfer had to be fixed for exactly this, where a malformed unshield burned the note before the
    destination was validated.)

    Phase 1 verifies a transparent witness. Phase 2 will verify a STARK here and see no witness at all; the
    checks it must enforce are the ones written out below, one for one."""
    if not isinstance(public, dict) or not isinstance(proof, dict):
        return "malformed transition"
    cid = public.get("cid")
    if not cid:
        return "transition names no contract"
    kind = int(public.get("kind", 0))
    predicate = PREDICATES.get(kind)
    if predicate is None:
        return f"unknown note kind {kind}"

    nfs = [int(n) % F.P for n in public.get("nullifiers", [])]
    cms = [int(c) % F.P for c in public.get("out_commitments", [])]
    if len(nfs) > MAX_INPUTS or len(cms) > MAX_OUTPUTS:
        return f"transition exceeds {MAX_INPUTS} inputs / {MAX_OUTPUTS} outputs"
    if not nfs and not cms:
        return "transition spends and creates nothing"
    if len(set(nfs)) != len(nfs):
        return "duplicate nullifier within one transition"
    for nf in nfs:
        if pool.has_nullifier(nf):
            return "note already spent"

    # The anchor the transition is built against. Read HERE, above both verifier paths, because both need
    # it — the STARK hands it to the circuit's root_is_known, the transparent path folds a path to it.
    # NO DUPLICATE COMMITMENTS — see ShieldedStatePool.has_commitment for why this is a fund-lock guard
    # and not hygiene. Checked here, before either verifier runs, so it holds for deposits and transitions
    # alike and cannot be reached only through whichever path happens to be cheapest to replay.
    if len(set(cms)) != len(cms):
        return "duplicate output commitment within one transition"
    for cm in cms:
        if pool.has_commitment(cid, cm):
            return "output commitment already exists (a replayed or reused note)"

    root = int(public.get("root", EMPTY_ROOT)) % F.P

    # ---- Phase 2: a STARK over the same statement, verified against `public` alone -------------------
    if proof.get("stark") is not None:
        if kind not in STARK_KINDS:
            # A kind whose predicate the CIRCUIT does not enforce must never take this path. The
            # transparent verifier runs PREDICATES explicitly; the proof path relies on the AIR having the
            # rule built in, so accepting a proof for a kind the AIR knows nothing about would enforce no
            # rule at all — the transition would be "valid" by virtue of nobody checking it.
            return f"note kind {kind} has no proving circuit (its predicate is not enforced in-circuit)"
        delta = int(public.get("public_delta", 0))
        # The destination rides in the Fiat-Shamir transcript, so a front-runner cannot copy a proof, swap
        # the address and redirect the exit (the pool's H-4 lesson, inherited).
        aux = str(public.get("withdraw_addr") or "")
        if not nfs and len(cms) == 1 and delta > 0:
            # DEPOSIT (0-in/1-out): public coins become the first private note. There is nothing to spend,
            # so there is no nullifier and no membership — which is exactly why it needs its own statement
            # rather than being squeezed into the transition one. The deposited amount is public (it left
            # the ledger in plain sight); what the proof hides is WHOSE note it becomes.
            ok, why = AC.verify_deposit(proof["stark"], cid_element(cid), kind, cms[0], delta, aux=aux)
        elif len(nfs) == 1 and len(cms) == 1:
            ok, why = AC.verify(proof["stark"], cid_element(cid), kind, root, nfs[0], cms[0], delta,
                                lambda r: pool.knows_root(cid, r), aux=aux)
        else:
            return ("no circuit for this shape — a deposit is 0-in/1-out with a positive delta, "
                    "a transition is 1-in/1-out")
        return None if ok else f"proof rejected: {why}"

    if not CONSENSUS_ALLOW_TRANSPARENT:
        return "transparent witness refused — a proof is required"

    # ---- Phase 1: re-check the witness in the clear -------------------------------------------------
    w = proof.get("witness")
    if not isinstance(w, dict):
        return "no witness and no proof"
    ins, outs = w.get("inputs") or [], w.get("outputs") or []
    if len(ins) != len(nfs) or len(outs) != len(cms):
        return "witness does not match the public statement"

    if nfs and not pool.knows_root(cid, root):
        return "unknown anchor — the transition targets a root this contract never held"

    in_fields, out_fields = [], []
    for i, note in enumerate(ins):
        try:
            nsk, fields, rho = int(note["nsk"]), [int(f) for f in note["fields"]], int(note["rho"])
            sibs, dirs = [int(s) for s in note["siblings"]], [int(d) & 1 for d in note["dirs"]]
        except (KeyError, TypeError, ValueError):
            return f"input {i}: malformed witness"
        if len(sibs) != TREE_DEPTH or len(dirs) != TREE_DEPTH:
            return f"input {i}: path is not {TREE_DEPTH} deep"
        cm = note_commitment(cid, kind, fields, owner_of(nsk), rho)
        if fold_path(cm, sibs, dirs) != root:
            return f"input {i}: not a member of the tree at that root"
        if note_nullifier(nsk, cm) != nfs[i]:
            return f"input {i}: nullifier is not derived from this note"
        in_fields.append(fields)

    for i, note in enumerate(outs):
        try:
            fields, owner, rho = [int(f) for f in note["fields"]], int(note["owner"]), int(note["rho"])
        except (KeyError, TypeError, ValueError):
            return f"output {i}: malformed witness"
        if note_commitment(cid, kind, fields, owner, rho) != cms[i]:
            return f"output {i}: commitment is not derived from this note"
        out_fields.append(fields)

    return predicate(in_fields, out_fields, int(public.get("public_delta", 0)))


def prove_transition(pool, cid, kind, nsk, fields_in, rho_in, cm_in_pos, fields_out, owner_out, rho_out,
                     public_delta=0, withdraw_addr=None):
    """DELEGATED PROVER: given the secret witness and the input note's position, build the Merkle path from
    the pool and produce the transition proof. Returns (public, proof) ready for apply_transition.

    The caller sees the witness — that is the delegated model this inherits from the pool, and it is the
    honest limit of the feature today: private from the chain and from other users, NOT from whoever runs
    this. A WASM/blind prover is what makes it unilateral (doc/shielded-contracts.md §7)."""
    sibs, dirs = tree_path(pool.trees.get(cid, []), cm_in_pos)
    stark_proof, root, nf, cm_out = AC.prove(nsk, cid_element(cid), kind, fields_in, rho_in, sibs, dirs,
                                             fields_out, owner_out, rho_out, public_delta=public_delta,
                                             aux=str(withdraw_addr or ""))
    public = {"cid": cid, "kind": kind, "root": root, "nullifiers": [nf], "out_commitments": [cm_out],
              "public_delta": public_delta}
    if withdraw_addr:
        public["withdraw_addr"] = withdraw_addr
    return public, {"stark": stark_proof}


def prove_deposit(cid, kind, fields_out, owner_out, rho_out, public_delta):
    """DELEGATED PROVER for a deposit: public coins -> the first private note. Returns (public, proof).

    A deposit needs no pool state at all — there is nothing to spend, so no Merkle path and no anchor. That
    is also why it is much cheaper than a transition: the trace is the OUTPUT region alone."""
    if int(public_delta) <= 0:
        raise ValueError("a deposit must bring value in (public_delta > 0)")
    stark_proof, cm_out = AC.prove_deposit(cid_element(cid), kind, fields_out, owner_out, rho_out,
                                           public_delta, aux="")
    public = {"cid": cid, "kind": kind, "root": EMPTY_ROOT, "nullifiers": [],
              "out_commitments": [cm_out], "public_delta": int(public_delta)}
    return public, {"stark": stark_proof}


def apply_transition(public, proof, pool):
    """Verify, then apply: record every nullifier and append every output commitment.

    Verification runs FIRST and in full — see verify_transition on why the ordering is load-bearing. Returns
    None on success or the rejection reason, having mutated nothing in the failure case."""
    reason = verify_transition(public, proof, pool)
    if reason is not None:
        return reason
    cid = public["cid"]
    for nf in public.get("nullifiers", []):
        pool.spend(nf)
    for cm in public.get("out_commitments", []):
        pool.append(cid, cm)
    return None
