"""
Daily network telemetry sampler (ops/daily_stats.py) — the data behind the wallet Stats tab's
txs/fees/miners/peers per-day charts (/daily_stats).

Load-bearing properties: the block walk credits each block to ITS OWN timestamp's UTC day (catch-up
backfills the right day); the walk resumes from last_height across restarts and is BOUNDED (a
long-dead node must not replay days); the first pass ever starts AT the tip (no history replay);
gauges keep the daily MAX; unobserved days serve null — never a fake zero; per-day fees are the
delta of cumulative_fees between observed days, serialized as strings (raw units can pass 2^53).

Run: python3 tests/test_daily_stats.py
"""
import json, os, sys, tempfile, time, traceback

os.environ["HOME"] = tempfile.mkdtemp(prefix="nado_dstats_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops import daily_stats as DS

fails = 0
def check(name, fn):
    """Run fn; print PASS/FAIL and count failures."""
    global fails
    try: fn(); print(f"PASS  {name}")
    except Exception as e:
        fails += 1; print(f"FAIL  {name}: {e}"); traceback.print_exc()


NOW = int(time.time())
DAY = lambda off: time.strftime("%Y-%m-%d", time.gmtime(NOW - off * 86400))


def mkchain(n_blocks, txs_per_block=2, fee=5, day_offset_of=lambda h: 0):
    """height -> block stub: `n_blocks` blocks, each with txs and a running cumulative_fees; each
    block's timestamp lands on the UTC day day_offset_of(height) days ago."""
    def load(h):
        if not (1 <= h <= n_blocks):
            return False
        return {"block_number": h, "block_timestamp": NOW - day_offset_of(h) * 86400,
                "block_transactions": [{} for _ in range(txs_per_block)], "cumulative_fees": h * fee}
    return load


def reset():
    try: os.remove(DS._stats_path())
    except FileNotFoundError: pass


def t_first_pass_starts_at_tip():
    """A fresh node must not replay history — pass one walks exactly the tip block."""
    reset()
    r = DS.sample(100, mkchain(100), {})
    assert r["walked"] == 1, r
    assert DS._load()["last_height"] == 100


def t_walk_resumes_and_credits_block_days():
    """Blocks land on their OWN day: a catch-up walk spanning yesterday+today fills BOTH days."""
    reset()
    load = mkchain(20, day_offset_of=lambda h: 1 if h <= 10 else 0)   # 1-10 yesterday, 11-20 today
    DS.sample(1, load, {})                        # first pass: at height 1 (yesterday's first block)
    r = DS.sample(20, load, {})                   # catch-up: walks 2..20 across the day boundary
    assert r["walked"] == 19, r
    days = DS._load()["days"]
    assert days[DAY(1)]["txs"] == 20 and days[DAY(1)]["blocks"] == 10, days.get(DAY(1))
    assert days[DAY(0)]["txs"] == 20 and days[DAY(0)]["blocks"] == 10, days.get(DAY(0))
    assert days[DAY(1)]["fees_last"] == 50 and days[DAY(0)]["fees_last"] == 100


def t_walk_is_bounded():
    """A node dead for ages resumes near the tip: one pass never walks more than _MAX_WALK."""
    reset()
    load = mkchain(50000)
    DS.sample(1, load, {})
    r = DS.sample(50000, load, {})
    assert r["walked"] == DS._MAX_WALK, r
    assert DS._load()["last_height"] == 50000, "must land ON the tip after the bounded walk"


def t_gauges_keep_daily_max():
    """Gauges are daily peaks; a missing gauge stays absent (served null), never a fake 0."""
    reset()
    load = mkchain(3)
    DS.sample(3, load, {"peers": 5, "open": 2})
    DS.sample(3, load, {"peers": 3, "open": 7, "bonded": 30})
    today = DS._load()["days"][DAY(0)]
    assert today["peers"] == 5 and today["open"] == 7 and today["bonded"] == 30, today
    assert "mempool" not in today, "unreported gauge must stay ABSENT, not zero"


def t_series_nulls_vs_fees_delta():
    """Unobserved days are null throughout; fees is the delta between OBSERVED days, as a string;
    the first observed day (no baseline) has null fees."""
    reset()
    data = {"last_height": 30, "days": {
        DAY(3): {"txs": 40, "blocks": 10, "fees_last": 2 ** 60, "peers": 4},
        DAY(1): {"txs": 60, "blocks": 20, "fees_last": 2 ** 60 + 12345},
    }}
    with open(DS._stats_path(), "w") as f:
        json.dump(data, f)
    rows = DS.daily_counts(days=5)
    assert len(rows) == 5 and rows[-1]["date"] == DAY(0)
    by = {r["date"]: r for r in rows}
    assert by[DAY(4)]["txs"] is None and by[DAY(4)]["fees"] is None, "unobserved day must be null"
    assert by[DAY(3)]["fees"] is None, "first observed day has no fees baseline"
    assert by[DAY(1)]["fees"] == "12345", f"delta skips the unobserved gap: {by[DAY(1)]}"
    assert isinstance(by[DAY(1)]["fees"], str), "raw fees must ride as strings (2^53 hazard)"
    assert by[DAY(3)]["peers"] == 4 and by[DAY(1)]["peers"] is None, "per-field nulls preserved"


def t_corrupt_file_and_retention():
    """Garbage on disk = empty history (never raises); old days fall off, newest stay."""
    with open(DS._stats_path(), "w") as f:
        f.write("]not json")
    assert DS._load()["days"] == {}
    assert DS.daily_counts(days=3)[-1]["txs"] is None
    reset()
    with open(DS._stats_path(), "w") as f:
        json.dump({"last_height": 5, "days": {f"2001-01-{d:02d}": {"txs": 1, "blocks": 1} for d in range(1, 11)}}, f)
    real, DS._RETENTION_DAYS = DS._RETENTION_DAYS, 3
    try:
        DS.sample(6, mkchain(6), {})
    finally:
        DS._RETENTION_DAYS = real
    kept = DS._load()["days"]
    assert len(kept) == 3 and DAY(0) in kept and "2001-01-01" not in kept, sorted(kept)


for name, fn in [
    ("first pass starts AT the tip (no history replay)", t_first_pass_starts_at_tip),
    ("walk resumes and credits blocks to their own day", t_walk_resumes_and_credits_block_days),
    ("catch-up walk is bounded", t_walk_is_bounded),
    ("gauges keep the daily max; absent stays absent", t_gauges_keep_daily_max),
    ("nulls for unobserved days; fees delta as string", t_series_nulls_vs_fees_delta),
    ("corrupt file tolerated; retention prunes oldest", t_corrupt_file_and_retention),
]:
    check(name, fn)

print("ALL PASSED" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
