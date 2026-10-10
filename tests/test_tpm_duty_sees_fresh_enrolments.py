"""EXPIRED ENROLMENTS MUST NOT HIDE FRESH ONES FROM THE CHALLENGER DUTY.

An incomplete TPM enrolment row is never collected from the chain (nothing deletes it), so
every abandoned attempt stays in the devbind DB for the life of the chain. The challenger duty's work list,
kv_ops.tpm_enrols_live, scans the "tpm:" prefix in KEY order and stops at 64 — and it used to count every
non-proven row, expired ones included. Enrolment ids are hashes, so once 64 dead rows sort before a fresh id,
that enrolment is invisible to every drawn challenger: nobody answers, it expires, the prover retries with a new
id that is equally likely to land behind the dead rows. The same "still open" test kept every expired
enrolment's challenge secret in private/tpm_challenges.json forever.

Pinned here: with the tip, the work list skips expired rows before the limit (the fresh enrolment is seen), the
expiry edge is the one /tpm_enrol_status uses (tip >= h + enrol_window(h) is expired), and the secret prune
drops an expired enrolment's secret while keeping a live one's.

Run: python3 tests/test_tpm_duty_sees_fresh_enrolments.py
"""
import os as _os, tempfile as _tempfile  # ISOLATION FIRST (CLAUDE.md rule 4): never the live node's HOME or exec files
_os.environ["HOME"] = _tempfile.mkdtemp(prefix="nado-test-")
_os.environ["NADO_EXEC_STATE"] = _os.path.join(_os.environ["HOME"], "exec_state.json")
_os.environ["NADO_EXEC_DA"] = _os.path.join(_os.environ["HOME"], "exec_da")
import json
import logging
import os
import sys
import types

import atexit, shutil; atexit.register(shutil.rmtree, os.environ["HOME"], ignore_errors=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for d in ("index", "blocks", "logs", "peers", "private"):
    os.makedirs(f"{os.environ['HOME']}/nado/{d}", exist_ok=True)

from genesis import create_indexers                                   # noqa: E402
create_indexers()
from ops import kv_ops, tpm_enrol as E                                # noqa: E402
from loops.core_loop import CoreClient as Core                        # noqa: E402

_fails = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else f": {detail}"))
    if not cond:
        _fails.append(name)


def record(h):
    return E.new_record("aa" * 32, b"\x30\x82spki", "bb" * 17, b"\x00\x01pub", "owner", h, ["c1", "c2", "c3"])


def main():
    tip = 50_000
    dead_h = 1_000                                        # long expired: 1000 + window << tip
    assert tip >= dead_h + E.enrol_window(dead_h)
    dead = [f"{i:032x}" for i in range(70)]              # 70 ids that all sort before the fresh one
    for eid in dead:
        kv_ops.tpm_enrol_set(eid, record(dead_h))
    fresh = "ff" * 16
    kv_ops.tpm_enrol_set(fresh, record(tip - 10))

    legacy = [e for e, _r in kv_ops.tpm_enrols_live()]
    check("without the tip the scan still fills its limit with dead rows (the old failure, kept reproducible)",
          fresh not in legacy and len(legacy) == 64, (len(legacy), fresh in legacy))
    live = [e for e, _r in kv_ops.tpm_enrols_live(tip=tip)]
    check("with the tip the fresh enrolment is on the work list", live == [fresh], live[:3])

    # the expiry edge is /tpm_enrol_status's: expired iff tip >= h + enrol_window(h)
    edge_h = tip - 5
    w = E.enrol_window(edge_h)
    kv_ops.tpm_enrol_set("fe" * 16, record(edge_h))
    at_edge = [e for e, _r in kv_ops.tpm_enrols_live(tip=edge_h + w)]
    before_edge = [e for e, _r in kv_ops.tpm_enrols_live(tip=edge_h + w - 1)]
    check("one block before its deadline an enrolment is live", "fe" * 16 in before_edge, before_edge)
    check("at its deadline it is expired and skipped", "fe" * 16 not in at_edge, at_edge)

    # a PROVEN record is never on the list, expired or not
    proven = dict(record(tip - 10)); proven["state"] = E.STATE_PROVEN; proven["hp"] = tip - 5
    kv_ops.tpm_enrol_set("fd" * 16, proven)
    check("a proven enrolment is not work", "fd" * 16 not in [e for e, _r in kv_ops.tpm_enrols_live(tip=tip)])

    # SECRETS: the prune keeps a live enrolment's secret and drops an expired one's
    core = types.SimpleNamespace(logger=logging.getLogger("tpm-fresh"))
    for m in ("maybe_tpm_prune_secrets", "_tpm_secrets_path", "_tpm_secrets_load", "_tpm_secrets_save"):
        setattr(core, m, getattr(Core, m).__get__(core))
    core._tpm_secrets_save({dead[0]: {"secret": "11" * 32, "seed": "22" * 32},
                            fresh: {"secret": "33" * 32, "seed": "44" * 32}})
    core.maybe_tpm_prune_secrets()
    check("without the tip nothing open is pruned (backward-compatible call)",
          set(core._tpm_secrets_load()) == {dead[0], fresh})
    core.maybe_tpm_prune_secrets(tip)
    kept = core._tpm_secrets_load()
    check("an expired enrolment's secret is pruned", dead[0] not in kept, sorted(kept))
    check("a live enrolment's secret is kept", fresh in kept, sorted(kept))
    with open(core._tpm_secrets_path()) as f:
        check("the store on disk is the pruned one", set(json.load(f)) == {fresh})


if __name__ == "__main__":
    main()
    if _fails:
        print(f"{len(_fails)} FAILED: {_fails}")
        sys.exit(1)
    print("ALL PASS")
