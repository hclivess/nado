"""A Windows Hello VBS key (AAGUID 9ddd1817) is never told "not using a TPM" or sent to switch off VBS first.

WHY (2026-09-29 site review). The network accepts the VBS authenticator: the TPM certify proof decides, not the AAGUID
(doc/device-attestation.md §Windows — a real owner spent two evenings on Credential Guard for that sentence). The wallet
still carried a hint saying "Windows Hello is not using a TPM on this PC" and a guide whose FIRST advice was to disable
virtualization-based security and Credential Guard in the registry. The VBS hint now names the enrolment helper (the
chip proves itself directly) and the VBS case gets the no-AIK guide, where switching off VBS is only a last, reversible
step after certreq.

Run: python3 tests/test_vbs_owner_is_sent_to_the_chip.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
js = open(os.path.join(ROOT, "static", "interface.js")).read()
fails = 0


def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    fails += 0 if ok else 1


hint = re.search(r'if \(ag\.startsWith\("9ddd1817"\)\) return i18\("([a-zA-Z.]+)"', js)
check("the VBS hint names the enrolment helper", bool(hint) and hint.group(1) == "device.hint.useHelper")
check("no hint tells a VBS owner 'not using a TPM'", 'i18("device.hint.vbs"' not in js)
check("the VBS-first guide (disable Credential Guard before anything else) is gone", 'i18("device.guide.vbs"' not in js)
check("the VBS case gets the no-AIK guide",
      '|| ag.startsWith("9ddd1817")) return i18("device.guide.winAik"' in js)
print("ALL PASS — a VBS owner is sent to the chip" if not fails else f"{fails} FAILURES")
sys.exit(1 if fails else 0)
