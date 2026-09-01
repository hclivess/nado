import json
import os
import socket
import time

from hashing import create_nonce
from protocol import AUTO_BOND_DEFAULT_PERCENT
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
    11 (2026-09-01): the presence lease is 36 h (POSW_LEASE_EPOCHS 240 -> 360) and the registration
    difficulty counts ENTRIES only (chain_entry_count) — both shipped while the chain was <19 h old so no
    committed epoch differs; a node on 10 would price/keep leases differently, so it is shed. STRICT.
    10 (2026-09-01): LINEAR dividend weight (min(fidelity, 30), 0 on probation) replaces the convex 1..25 curve,
    ungated at chain age <19 h (identical epochw rows until the first identity reaches fidelity 2); a node
    still on 9 would commit a different weight row at that epoch, so it is shed at the door. STRICT.
    9 (2026-09-01): the betanet-6 (gen 24) SYBIL-RULES + ACCOUNT-AUTH reroll — probation (no dividend, open weight 1
    until the first timely renewal), the 14-day-capped registration difficulty baseline, account authentication
    live (AUTH_ACTIVE) and the epochw root window from block 0; every amount carried forward. Old nodes would
    weight a fresh identity 2 and pay it dividends, so they are shed at the door. STRICT.
    8 (2026-08-25): the betanet-5 (gen 23) DIVIDEND-RULES reroll — linear bonded weight, the convex
    dividend weight curve, the halving lapse and the 40% bonded levy from block 0; old nodes would split
    every bonded block 70/20/10 and weight the dividend 2..10, so they are shed at the door. STRICT.
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
    return 11


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


def get_public_relay_url():
    """The origin at which BROWSERS can reach this node's API — e.g. "https://get.nadochain.com" — or ""
    when this node does not advertise one. Published in /status as `relay_url` and gossiped by /relays,
    so a web wallet can FAIL OVER to this node when its own relay goes quiet (static/interface.js).

    Why this has to be opt-in: every node speaks plain HTTP on the API port, but a wallet served over HTTPS
    cannot fetch http:// (mixed content is blocked by the browser), so a bare ip:port is useless to it. An
    operator who fronts the node with TLS (nginx + Let's Encrypt — the get.nadochain.com layout in
    doc/relays.md: the L1 API at /, the exec node at /exec/ and /da/) states the public origin here.
    NADO_PUBLIC_RELAY_URL env wins, else "public_relay_url" in private/config.json, else "". Scheme +
    host[:port] only, no path; anything else is ignored rather than advertised broken."""
    url = os.environ.get("NADO_PUBLIC_RELAY_URL") or ""
    if not url:
        try:
            with open(_config_path()) as infile:
                url = str(json.loads(infile.read()).get("public_relay_url") or "")
        except Exception:
            url = ""
    url = url.strip().rstrip("/")
    if not url.lower().startswith(("http://", "https://")):
        return ""
    host = url.split("://", 1)[1]
    if not host or "/" in host or any(c.isspace() for c in host):
        return ""
    return url


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

    # DISABLED BY OPERATOR DECISION (2026-08-17). No migration step may rewrite a node's config.
    #
    # The mechanism below was built to move nodes off a stale installer default, and the v1 step flipped
    # `archive: true` -> false. The objection is the one the docstring itself concedes: on disk, a value the
    # installer wrote is INDISTINGUISHABLE from a value the operator chose, so "only flip the old default"
    # is a guess about intent, and when it guesses wrong it silently turns an archive node into a rolling
    # one. An operator who wanted rolling mode can set one key; a node that quietly stopped keeping history
    # is discovered from a user's bug report, which is exactly the failure this repo has already had once.
    #
    # The VERSION STAMP still runs, so a config written before the mechanism existed is marked current and
    # no later step can claim it as un-migrated. Re-enabling any rewrite is a deliberate act: add the step
    # back here, and say so in the release notes.
    changed = {}

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
        # unattended, so a fresh node joins the bonded lane hands-free; 0 disables it. Overridable via
        # the NADO_AUTO_BOND_PERCENT env var.
        #
        # WRITE THE CONSTANT, never a literal. This said 80 while protocol.AUTO_BOND_DEFAULT_PERCENT was
        # raised to 99, so a FRESH install got 80 baked into its config file while a config that merely
        # lacked the key fell back to 99 — two nodes installed a week apart quietly compounding at
        # different rates, and no way to tell from the outside which one you had.
        "auto_bond_percent": AUTO_BOND_DEFAULT_PERCENT,
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
        # networks unpenalised. Counts ENTRY registrations only (renewals never spend it) and never applies
        # to peer push-gossip, so it prices exactly new identities from one network; 0 disables. Watch the
        # 429 rate on CGNAT/campus/conference networks before lowering it further. NADO_MAX_REG_PER_IP.
        "max_registrations_per_ip": 8,
        # The sliding window (seconds) the per-IP budget above is measured over. Longer = tighter (the budget
        # accumulates across more time), but keep it well under the ~1-day lease so renewals don't fill it.
        # Node-local admission control only (an IP can't be a consensus input). NADO_MAX_REG_WINDOW.
        "max_registrations_window": 3600
    }

    if not os.path.exists(config_path):
        with open(config_path, "w") as outfile:
            json.dump(config_contents, outfile)


if __name__ == "__main__":
    pass
