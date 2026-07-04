#!/usr/bin/env python3
"""
E2E: rolling-node onboarding via snapshot sync.

Stages a DONOR that produces blocks and publishes a finalized state checkpoint, then launches a
FRESH JOINER whose only peer is the donor. The joiner cannot full-sync (in a real net the donor is
pruned; here we assert it takes the snapshot path anyway) — it must snapshot-bootstrap to the donor's
checkpoint and tail-sync to the donor's tip.

Run:  NADO_SNAPSHOT_INTERVAL is forced small so a checkpoint is crossed + finalized quickly.
      python scripts/testnet/test_snapshot_sync.py
"""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from run_testnet import seed_node, node_ip, status, PORT        # noqa: E402
from Curve25519 import generate_keydict                          # noqa: E402
from protocol import B_MIN                                       # noqa: E402

INTERVAL = 5           # NADO_SNAPSHOT_INTERVAL for the test
DONOR_WAIT = 180       # seconds to wait for the donor to publish a finalized checkpoint
JOIN_WAIT = 180        # seconds to wait for the joiner to catch up


def main():
    work = tempfile.mkdtemp(prefix="nado_snapsync_")
    print(f"[snapsync] workdir {work}", flush=True)
    keys = [generate_keydict() for _ in range(2)]                # node0 donor, node1 joiner
    bonds = sorted(({"address": k["address"], "bonded": B_MIN} for k in keys),
                   key=lambda e: e["address"])                   # identical bonds => identical genesis
    homes = [os.path.join(work, f"node{i}") for i in range(2)]
    for i in range(2):
        seed_node(homes[i], i, keys, bonds)

    base_env = dict(os.environ, NADO_TESTNET="1",
                    NADO_SNAPSHOT_INTERVAL=str(INTERVAL),
                    NADO_TESTNET_BLOCKTIME="1")
    procs = {}

    def launch(i):
        env = dict(base_env, HOME=homes[i])
        lf = open(os.path.join(homes[i], "node.log"), "w")
        procs[i] = subprocess.Popen([sys.executable, "nado.py"], cwd=REPO, env=env,
                                    stdout=lf, stderr=subprocess.STDOUT)

    def logtail(i, n=45):
        try:
            return "".join(open(os.path.join(homes[i], "node.log")).readlines()[-n:])
        except Exception as e:
            return f"(no log: {e})"

    rc = 2
    try:
        # 1) DONOR — produce until it advertises a FINALIZED checkpoint
        launch(0)
        print("[snapsync] donor up; waiting for a finalized checkpoint advertisement...", flush=True)
        donor_snap = None
        t0 = time.time()
        while time.time() - t0 < DONOR_WAIT:
            time.sleep(3)
            s = status(0)
            if "error" in s:
                continue
            sh, fin = s.get("snapshot_height"), s.get("finalized_height")
            print(f"[snapsync] donor finalized={fin} snapshot_height={sh}", flush=True)
            if sh:
                donor_snap = sh
                break
        if not donor_snap:
            print("[snapsync] FAIL: donor never advertised a finalized checkpoint", flush=True)
            print("----- donor log -----\n" + logtail(0), flush=True)
            return 2
        print(f"[snapsync] donor advertises checkpoint @ {donor_snap}", flush=True)

        # 2) JOINER — fresh node, only peer is the donor; must snapshot-bootstrap + tail-sync
        launch(1)
        genesis_hash = status(1).get("latest_block_hash")   # its block-0 hash (may differ; capture it)
        print(f"[snapsync] joiner up (genesis {str(genesis_hash)[:10]}); waiting to catch up...", flush=True)
        caught_up = False
        t0 = time.time()
        while time.time() - t0 < JOIN_WAIT:
            time.sleep(3)
            sj, sd = status(1), status(0)
            jh = sj.get("latest_block_hash"); dh = sd.get("latest_block_hash")
            print(f"[snapsync] joiner tip={str(jh)[:10]} finalized={sj.get('finalized_height')} "
                  f"| donor tip={str(dh)[:10]}", flush=True)
            if jh and jh != genesis_hash and jh == dh:
                caught_up = True
                break
        boot = ("Snapshot bootstrap complete" in logtail(1, 400)
                or "bootstrapped from snapshot" in logtail(1, 400))
        print(f"\n[snapsync] joiner left genesis + matched donor tip: {caught_up}", flush=True)
        print(f"[snapsync] joiner took the SNAPSHOT path (not full replay): {boot}", flush=True)
        if not caught_up:
            print("----- joiner log -----\n" + logtail(1), flush=True)
        rc = 0 if (caught_up and boot) else 2
        print(f"\n[snapsync] RESULT: {'PASS' if rc == 0 else 'FAIL'}", flush=True)
        return rc
    finally:
        for p in procs.values():
            try: p.terminate()
            except Exception: pass
        time.sleep(2)
        for p in procs.values():
            try: p.kill()
            except Exception: pass
        print(f"[snapsync] torn down. logs under {work}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
