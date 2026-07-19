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
    5 (2026-07-18): the DEBRAND CUTOVER — alphanet-7 genesis reroll: mldsa44/msig address
    prefixes, every domain-separation tag renamed brand-free (doc/debrand.md). STRICT."""
    return 5


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
        "min_peers": 2,
        # Per-burst rollback allowance. MUST stay < FINALITY_DEPTH (45) so an honest reorg inside the
        # unfinalized window always completes instead of stopping half-way and leaving the node wedged.
        # Raised 10 -> 40 with the finality widening: a 10-deep cap could not even traverse its own
        # unfinalized window, so a perfectly legal reorg hit "Rollbacks exhausted" and fell through to
        # the snapshot path for no reason.
        "max_rollbacks": 40,
        "finality_depth": 12,
        "block_time": 6,
        # AUTO-BOND (non-consensus): % of newly-mined earnings to auto-compound into bonded stake,
        # unattended. Defaults to protocol.AUTO_BOND_DEFAULT_PERCENT (80) so a fresh node joins the
        # bonded lane hands-free; set 0 to disable. Overridable via the NADO_AUTO_BOND_PERCENT env var.
        "auto_bond_percent": 80,
        # INTEGRATED AUTO-UPDATE (non-consensus, ops/self_update.py): keep the node on origin/main of the
        # official repo — a daily fast-forward check plus the remote /update trigger (harmless for anyone
        # to call: it only decides WHEN, the code always comes from the repo you already run). Set False
        # to update manually.
        "auto_update": True,
        # ROLLING MODE (non-consensus, doc/rolling-mode-and-da.md): archive=True keeps ALL block bodies
        # forever (default — no data loss, current behaviour). Set False for a "rolling"/pruned node that
        # drops block BODIES older than history_retention_blocks (state + number<->hash indexes are always
        # kept, so it still validates + serves the beacon/FFG). Overridable via NADO_ARCHIVE / env.
        "archive": True,
        "history_retention_blocks": 0,  # 0 = use protocol.HISTORY_RETENTION_BLOCKS default
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
