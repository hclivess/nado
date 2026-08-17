"""The design document must not drift from the code it describes.

WHY THIS FILE EXISTS. The most expensive mistake on this branch came from trusting prose over the thing it
described: VALUE_MAX was 2^62 because it was copied from joinsplit_circuit's module docstring, while the
constraint that docstring described pinned three bits and enforced 2^61. The transparent verifier ended up
LOOSER than the circuit it exists to specify, and a note above the circuit's bound would have been
creatable and then spendable by no proof.

Prose has no compiler. So every load-bearing NUMBER in doc/shielded-contracts.md is asserted here against
the constant or the measurement it claims to report. A doc that says 128 while ANCHOR_WINDOW says 256 is
not a documentation nit on this branch — it is the shape of a bug that has already happened once.

What is deliberately NOT pinned: timings (21.1 s, 30.7 s). They are measurements on one machine at one
moment, and asserting them would fail on any other box for no useful reason. They are labelled in the doc
as measured, with the conditions, which is the honest treatment for a number that cannot be re-derived.

Run: python3 tests/test_shielded_doc_matches_code.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from execnode import exec_root as ER
from execnode import shielded_state as S
from execnode.stark import appnote_circuit as AC

FAILS = []


def check(name, fn):
    try:
        fn()
        print("PASS  " + name)
    except AssertionError as e:
        print("FAIL  " + name + " — " + str(e))
        FAILS.append(name)
    except Exception as e:
        print(f"FAIL  {name} — {type(e).__name__}: {e}")
        FAILS.append(name)


DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "doc", "shielded-contracts.md")
TEXT = open(DOC, encoding="utf8").read()


def says(*fragments):
    """Every fragment must appear in the document."""
    missing = [f for f in fragments if f not in TEXT]
    assert not missing, f"the document no longer says: {missing}"


# ---- constants the document quotes -------------------------------------------------------------------
def t_the_document_exists_and_is_substantial():
    assert len(TEXT) > 8000, "the design document has shrunk unexpectedly"


def t_tree_depth_matches():
    says(f"TREE_DEPTH = {S.TREE_DEPTH}", f"{2 ** S.TREE_DEPTH:,} notes")


def t_the_record_tags_match():
    assert (ER.T_APP_ROOT, ER.T_APP_NULL) == (11, 12), "the app record tags moved"
    says("tags **11**", "12")


def t_the_value_bound_matches():
    exp = S.VALUE_MAX.bit_length() - 1
    says(f"2^{exp}")
    assert S.VALUE_MAX is AC.RANGE_BOUND, "the doc describes one bound; the code has two"


def t_the_anchor_window_matches():
    says(f"`ANCHOR_WINDOW` ({S.ANCHOR_WINDOW})")


def t_the_da_op_table_matches():
    src = open(os.path.join(os.path.dirname(DOC), "..", "execnode", "execnode.py"), encoding="utf8").read()
    m = re.search(r'_DA_BLOB_OPS = \{([^}]*)\}', src)
    assert m, "the DA op table is gone from the source"
    for op in re.findall(r'"([a-z_]+)":', m.group(1)):
        assert op in TEXT, f"the document does not mention the DA-carried op {op!r}"


def t_the_transparent_switch_is_documented_as_off():
    assert S.CONSENSUS_ALLOW_TRANSPARENT is False
    says("`CONSENSUS_ALLOW_TRANSPARENT`")


def t_the_two_statement_shapes_match_the_code():
    """The doc's table of statements must match what the seam actually admits."""
    says("0-in / 1-out", "1-in / 1-out")
    assert S.STARK_KINDS <= set(S.KIND_ARITY), "a provable kind has no declared arity"


def t_the_kinds_table_matches():
    for kind in sorted(S.PREDICATES):
        name = {S.KIND_VALUE: "KIND_VALUE"}.get(kind)
        assert name, f"kind {kind} exists in code with no name known to this test"
        assert name in TEXT, f"the document does not describe {name}"


# ---- claims that would be false if the code changed --------------------------------------------------
def t_measured_numbers_are_labelled_as_measured():
    """A number nobody can re-derive must say where it came from, or it becomes the next VALUE_MAX."""
    for n in ("24.7 MiB", "183"):
        assert n in TEXT, f"the measured figure {n} vanished from the document"
    assert "MEASURED" in TEXT or "Measured" in TEXT or "measured" in TEXT, \
        "the document no longer marks its measurements as measurements"


def t_the_honest_limits_are_still_stated():
    """The two things this feature does NOT do. If either silently left the doc, a reader would over-trust
    the system — which is a worse failure than any single wrong constant."""
    says("does not execute contract code")
    assert "private except from the operator" in TEXT or "not from whoever runs the exec node" in TEXT, \
        "the delegated-proving limitation is no longer stated"


for name, fn in list(globals().items()):
    if name.startswith("t_"):
        check(name[2:].replace("_", " "), fn)

print()
print(f"{len(FAILS)} FAILURE(S): {FAILS}" if FAILS else "DOC AND CODE AGREE")
sys.exit(1 if FAILS else 0)
