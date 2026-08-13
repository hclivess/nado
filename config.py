import json
import os
import socket
import time

from hashing import create_nonce
from ops.data_ops import get_home


def _config_path():
    """Canonical config path: private/config.json (the file has always been JSON). A pre-rename
    config.dat is renamed ONCE to carry the operator's settings forward — data migration, not a
    compatibility layer: nothing keeps answering to the old name."""
    base = f"{get_home()}/private"
    canon, legacy = f"{base}/config.json", f"{base}/config.dat"
    if not os.path.exists(canon) and os.path.isfile(legacy) and not os.path.islink(legacy):
        os.replace(legacy, canon)
    return canon


def config_found(file=None):
    """Does the config exist? The 'is this a fresh node?' probe — genesis only network-probes for a
    public IP (and writes defaults) when this is False, so re-runs never clobber an existing config."""
    return os.path.isfile(file or _config_path())


def get_timestamp_seconds():
    """Current UNIX time as a whole INT of seconds — the one timestamp granularity used everywhere
    (block timestamps, uptime, pools), so nothing consensus-adjacent ever touches a float."""
    return int(time.time_ns() / 1000000000)


def get_protocol():
    """The node's protocol number — peers whose /status reports a LOWER protocol than ours are
    rejected at handshake, so bump this on breaking wire/consensus changes to shed old nodes.
    3 (2026-07-18): the bit-width-audit + reg-difficulty-v2 consensus changes, strict.
    4 (2026-07-18): reg-difficulty v3 — state-index counts (see reg_difficulty.py).
    5 (2026-07-18): the DEBRAND CUTOVER — betanet-7 genesis reroll: mldsa44/msig address
    prefixes, every domain-separation tag renamed brand-free (doc/debrand.md). STRICT.
    6 (2026-07-24): SNAPSHOT-ROOT DETERMINISM — the h76000 seed-split fix. Rollback now reverts a
    block's txs in reverse-application order (path-dependent bond_since restore); the reorg-path-dependent
    revert journals (bond_since_revert/hb_revert/msgkey_revert) left SNAPSHOT_DBS so they no longer feed
    the state_root; all-default account rows are canonicalized out of the root. These change how the
    state_root/snapshot_hash are computed, so old nodes MUST be shed (they would advertise a different
    root at the same height and never form the sync quorum). STRICT.
    7 (2026-07-27): the betanet-10 SECURITY + DETERMINISM reroll. Breaking on every axis, so old nodes
    must be shed: (a) the exec DA binding no longer hashes block_timestamp and the exec VM's TIME opcode
    now reads protocol.chain_clock(height) instead — block_timestamp is outside the block-hash preimage
    and legitimately differs between honest nodes, so both were non-deterministic (measured live: the same
    block produced different call leaves on two nodes); (b) settle now bounds exec_cursor to the carrying
    block height, closing a 10-NADO permanent capture of the settlement oracle that could drain every
    escrow; (c) faucet donations escrow to BRIDGE_ESCROW (where they are actually redeemed) instead of a
    FAUCET_ESCROW with no release path; (d) apply_slash books its burn into the supply counter; (e) the
    snapshot transfer payload is canonicalized (treasury_proposals + node-local meta rows excluded) and
    re-anchor/bootstrap now require a real quorum with seed anchoring. State transitions, the exec state
    root and the snapshot identity all change, so a gen-9/protocol-6 node can never agree with us. STRICT."""
    return 7


def get_port():
    # Port is CONFIGURABLE: NADO_PORT env wins (handy for local multi-node testing), else the "port" field
    # in config.json, else the 9173 default. Read the file DIRECTLY (not via get_config) — get_config seeds
    # "port" from get_port() at create time, so calling it here would recurse. Every node on a network must
    # still agree on the port (peer dialing uses the local node's port for all peers).
    env = os.environ.get("NADO_PORT")
    if env:
        try:
            return int(env)
        except ValueError:
            pass
    try:
        with open(_config_path()) as infile:
            return int(json.loads(infile.read()).get("port", 9173))
    except Exception:
        return 9173


def hostport(ip, port):
    """`host:port` for a URL, bracketing IPv6 literals (which contain ':') so the port still parses.
    IPv4 addresses and hostnames pass through unchanged. Every peer-dial URL goes through this."""
    return f"[{ip}]:{port}" if ip and ":" in str(ip) else f"{ip}:{port}"


def test_self_port(ip, port):
    """True if a TCP connect to ip:port succeeds within 3s — the self-reachability probe that gates
    can_mine: a node whose own port isn't reachable from its public IP shouldn't produce blocks
    nobody can fetch. Family-aware (see below) so IPv6 nodes aren't wrongly reported shut."""
    # family-aware: an IPv6 literal needs AF_INET6, else connect_ex raises and we'd wrongly report the
    # port shut. hostnames/edge cases fall back to IPv4.
    family = socket.AF_INET6 if ip and ":" in str(ip) else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.settimeout(3)
        result = sock.connect_ex((ip, port))
        return not result


def get_config(config_path: str = None):
    """Load the node config dict from private/config.json. Deliberately uncached and raising on a
    missing file — callers either checked config_found() first or WANT the loud failure (a node
    without a config must not limp along on invented defaults)."""
    with open(config_path or _config_path()) as infile:
        return json.loads(infile.read())


def update_config(new_config: dict, config_path: str = None):
    """Read-merge-write: overlay `new_config` keys onto the existing config and persist. Keys not
    mentioned pass through untouched, so a caller can flip one knob without knowing (or wiping)
    the full schema. NOT crash-atomic — a plain truncate-and-rewrite of a non-consensus file."""
    config_path = config_path or _config_path()
    config = get_config(config_path)
    for key, value in new_config.items():
        config[key] = value

    with open(config_path, "w") as outfile:
        json.dump(config, outfile)


# Bumped when a DEFAULT changes in a way an already-written config would otherwise pin forever.
# create_config stamps it; migrate_config applies the delta once to older files. See migrate_config.
CONFIG_VERSION = 1


def migrate_config(logger=None, config_path: str = None) -> dict:
    """Apply one-time default changes to a config written by an older installer. Returns what it did.

    THE PROBLEM THIS SOLVES. create_config writes EVERY default into config.json at install time, and it
    is deliberately create-only. So a default change reaches new installs and NOTHING ELSE: the value the
    old installer wrote is indistinguishable, on disk, from a value the operator chose, and it pins the old
    behaviour forever. Observed directly — flipping "archive" to False moved exactly the one node whose
    config predated the key, while five nodes carrying an installer-written "archive": true kept archiving.
    Those are the nodes the change is FOR, and none of them can be reached with a shell.

    So: version the file. A config with no `config_version` was written before this mechanism existed, and
    its knobs are old DEFAULTS, not decisions. Migrating them once is a data migration in the same spirit
    as the config.dat -> config.json rename above — not a compatibility layer, and it never runs twice.

    Deliberately narrow. It touches ONLY keys listed in a migration step, only when they still hold the old
    default (a value the operator changed to anything else is left alone), and it stamps the version so a
    later deliberate "archive": true is permanent. Non-consensus, and reversible by editing one key."""
    config_path = config_path or _config_path()
    try:
        config = get_config(config_path)
    except Exception:
        return {"migrated": False, "reason": "no config"}
    have = int(config.get("config_version", 0) or 0)
    if have >= CONFIG_VERSION:
        return {"migrated": False, "version": have}

    changed = {}
    # v1: rolling mode became the default. An archive node costs a measured ~47.6 GB/year of block bodies,
    # and a node that fills its disk stops UPDATING, not just archiving. Only flip the value the old
    # installer wrote; an operator who set it to anything else has already made a decision.
    if have < 1 and config.get("archive") is True:
        changed["archive"] = False

    changed["config_version"] = CONFIG_VERSION
    update_config(changed, config_path)
    if logger and len(changed) > 1:
        logger.warning(f"config migrated to v{CONFIG_VERSION}: "
                       + ", ".join(f"{k}={v}" for k, v in changed.items() if k != "config_version")
                       + " (set it back explicitly if that was a deliberate choice)")
    return {"migrated": True, "from": have, "to": CONFIG_VERSION,
            "changed": {k: v for k, v in changed.items() if k != "config_version"}}


def create_config(ip: str, config_path: str = None):
    """Write the initial config.json with every default knob (all NON-consensus, operator-tunable).
    Strictly create-only: an existing file is NEVER overwritten, so re-running genesis/bootstrap
    over an initialized node cannot clobber operator edits. The freshly generated server_key is
    this node's local auth secret — the file lives in private/ (gitignored) for a reason."""
    config_path = config_path or _config_path()
    config_contents = {
        "port": get_port(),
        "ip": ip,
        "server_key": create_nonce(length=64),
        # Stamps the defaults this file was born with, so a LATER default change can be applied once
        # to it (migrate_config) instead of being pinned forever by a value the installer wrote.
        "config_version": CONFIG_VERSION,
        "min_peers": 2,
        # Per-burst rollback allowance. MUST stay < FINALITY_DEPTH (45) so an honest reorg inside the
        # unfinalized window always completes instead of stopping half-way and leaving the node wedged.
        # Raised 10 -> 40 with the finality widening: a 10-deep cap could not even traverse its own
        # unfinalized window, so a perfectly legal reorg hit "Rollbacks exhausted" and fell through to
        # the snapshot path for no reason.
        "max_rollbacks": 40,
        # MUST match protocol.FINALITY_DEPTH (45, the 2026-07-19 widening — depth 12 froze incompatible
        # histories after a 72s partition and split the network three ways). This line briefly said 12
        # after the widening, which made every FRESH install fail memserver's boot assert
        # (max_rollbacks 40 < finality_depth 12 is false) — new nodes could not start at all. Old
        # configs without the key correctly fall back to the protocol constant.
        "finality_depth": 45,
        "block_time": 6,
        # AUTO-BOND (non-consensus): % of newly-mined earnings to auto-compound into bonded stake,
        # unattended. Defaults to protocol.AUTO_BOND_DEFAULT_PERCENT (80) so a fresh node joins the
        # bonded lane hands-free; set 0 to disable. Overridable via the NADO_AUTO_BOND_PERCENT env var.
        "auto_bond_percent": 80,
        # INTEGRATED AUTO-UPDATE (non-consensus, ops/self_update.py): keep the node on origin/main of the
        # official repo — a daily fast-forward check plus the remote /update trigger (harmless for anyone
        # to call: it only decides WHEN, the code always comes from the repo you already run). Set False
        # to update manually — that also DISABLES the /update and /update_peer endpoints (403), so an
        # opted-out node can neither be update-triggered remotely nor used as a proxy to trigger others.
        "auto_update": True,
        # BOOT-TIME SELF-HEAL (non-consensus, ops/self_update.ensure_updatable): a node diagnosed as
        # un-updatable (no git checkout, no systemd unit, ...) repairs itself by running the LOCAL
        # scripts/install.sh once per boot. Set False to only diagnose and log — never run the installer.
        "auto_heal": True,
        # ROLLING MODE (non-consensus, doc/rolling-mode-and-da.md) is the DEFAULT: a rolling node drops
        # block BODIES older than history_retention_blocks, keeping state and the number<->hash indexes,
        # so it still validates, produces, and serves the beacon/FFG — it just cannot serve ancient bodies.
        #
        # WHY THIS FLIPPED. archive=True keeps every body forever, and "forever" is not a rounding error:
        # measured on betanet-3 at 133 MB/day of bodies, an archive node costs ~47.6 GB/year. That is a
        # fine default for the one box that hosts an explorer and a terrible one for the volunteer VPSes
        # that are most of the network — and a node that fills its disk does not merely stop archiving, it
        # stops UPDATING (git fetch cannot write) and eventually forks. Rolling caps bodies at
        # HISTORY_RETENTION_BLOCKS (7 days, ~930 MB) with a hard consensus floor underneath it that config
        # cannot lower (block_ops.prune_block_bodies).
        #
        # Set True to keep everything — do that on an explorer/seed node, where old bodies are the product.
        # Overridable via NADO_ARCHIVE / env.
        "archive": False,
        "history_retention_blocks": 0,  # 0 = use protocol.HISTORY_RETENTION_BLOCKS default
        # TX HISTORY retention (rolling mode only). The tx index is what actually dominates disk at scale:
        # bodies plateau once pruned, the tx history did not. 0 = keep protocol.TX_HISTORY_MIN_RETENTION
        # (~8 h), which is the floor the replay guard needs; a LARGER value keeps more explorer depth.
        # Any value is floored in code — a small number cannot open a replay hole. Archive nodes ignore it.
        "tx_history_retention_blocks": 0,
        # PROGRESSIVE IP-DIVERSITY registration budget (non-consensus relay admission control). Expressed
        # as "equivalent same-EXACT-IP addresses" per hour: a same-/32 peer costs 1.0 of it, same-/24 0.5,
        # /16 0.25, /8 0.125, unrelated 0 — so the effective limit scales ~64/exact IP, ~128 per /24, ~256
        # per /16, ~512 per /8. Bounds a datacenter's whole range, not just one IP, while leaving distinct
        # networks unpenalised. Generous so legit CGNAT/NAT isn't bricked; 0 disables. NADO_MAX_REG_PER_IP.
        "max_registrations_per_ip": 64,
        # The sliding window (seconds) the per-IP budget above is measured over. Longer = tighter (the budget
        # accumulates across more time), but keep it well under the ~1-day lease so renewals don't fill it.
        # Node-local admission control only (an IP can't be a consensus input). NADO_MAX_REG_WINDOW.
        "max_registrations_window": 7200
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    pass
