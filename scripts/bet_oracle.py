#!/usr/bin/env python3
"""bet_oracle.py — the resolver for the NADO Bet (parimutuel sports) contract.

A blockchain can't see the real world, so the Bet contract trusts an ORACLE KEY to post match
results. This script IS that oracle's helper: it reads the free public source named on each market
(TheSportsDB by default), works out the winning outcome, and submits resolve()/void() blob txs signed
by the oracle key. The oracle SET and threshold live in the contract (admin-configurable) — this tool
just posts one key's vote; run one copy per oracle key for M-of-N.

SAFETY (this moves money): resolution is DRY-RUN by default — it prints what it WOULD post and submits
nothing. Add --submit to actually vote. Only markets whose betting has CLOSED (past lock) and that are
still unresolved are considered, and only when the source reports the match FINISHED with a clear
scoreline; anything ambiguous is skipped, never guessed.

Market convention the bot understands (set this way when you list the match):
    source == "thesportsdb", ev == the event's TheSportsDB id, and outcomes ordered
        2 outcomes -> [HOME, AWAY]        (draw impossible / handled as void)
        3 outcomes -> [HOME, DRAW, AWAY]  (1X2)
Markets with any other shape are listed but skipped (resolve them by hand from the web UI).

Usage (HOME must point at the oracle wallet's data dir so keys.dat is found — the node key by default):
    HOME=/root python scripts/bet_oracle.py list                     # markets + fetched results
    HOME=/root python scripts/bet_oracle.py resolve                  # DRY-RUN: print proposed votes
    HOME=/root python scripts/bet_oracle.py resolve --submit         # actually post resolve()/void()
    HOME=/root python scripts/bet_oracle.py void <marketId> --submit # force-void one market
        [--l1 URL] [--exec URL] [--cid CID] [--sportsdb-key K]
"""
import argparse, calendar, json, os, sys, time, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ops.transaction_ops import construct_blob_tx
from ops.key_ops import load_keys
from protocol import MIN_TX_FEE

BET_CID = "fe303d9880c8222dcf3b9953eb86a0fa"   # execnode/contracts/bet.json (nonce "bet-v1")
# Major soccer leagues to seed matches from (TheSportsDB league ids). 1X2 (home/draw/away) markets.
# Override with --leagues "4328,4335,…". All soccer, so the 3-outcome shape is always right.
DEFAULT_LEAGUES = ["4328", "4335", "4332", "4331", "4334", "4480", "4346", "4337"]
# EPL · La Liga · Serie A · Bundesliga · Ligue 1 · UEFA Champions League · MLS · Eredivisie


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, body, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def read_storage(exec_url, cid):
    """The contract's full {map: {key: val}} storage, provisional tail included."""
    return _get(f"{exec_url}/exec/contract?ns=default&cid={cid}").get("storage", {})


def parse_markets(sto, cursor):
    """Reconstruct every market from storage (mirrors static/bet.js parseMarket)."""
    mk = sto.get("mk", {})
    out = []
    for mid in mk:
        g = lambda m: sto.get(m, {}).get(mid)
        nout = int(g("no") or 0)
        lines = str(g("ds") or "").split("\n")
        labels = [lines[i + 1] if i + 1 < len(lines) else f"Outcome {i}" for i in range(nout)]
        lock, deadline = int(g("lk") or 0), int(g("dl") or 0)
        out.append({
            "id": mid, "nout": nout, "title": lines[0] if lines else f"Match #{mid}",
            "labels": labels, "lock": lock, "deadline": deadline,
            "resolved": bool(g("dn")), "void": bool(g("vd")),
            "source": str(g("so") or ""), "ev": str(g("ev") or ""),
            "locked": cursor is not None and cursor >= lock,
            "past_deadline": cursor is not None and cursor >= deadline,
        })
    return out


def thesportsdb_result(ev, key):
    """Fetch one event; return (status, home_score, away_score) or (None,..) if unknown/unfinished."""
    try:
        url = f"https://www.thesportsdb.com/api/v1/json/{key}/lookupevent.php?id={urllib.parse.quote(ev)}"
        data = _get(url)
        evs = (data or {}).get("events") or []
        if not evs:
            return (None, None, None)
        e = evs[0]
        status = (e.get("strStatus") or "").strip()
        hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
        if hs is None or as_ in (None, ""):
            return (status or "unknown", None, None)
        return (status or "Match Finished", int(hs), int(as_))
    except Exception as ex:
        return (f"fetch-error: {ex}", None, None)


def winning_outcome(mk, hs, as_):
    """Map a scoreline to the market's outcome index using the HOME/(DRAW/)AWAY convention.
    Returns (index, reason) or (None, reason) if the shape isn't understood."""
    if mk["nout"] == 3:      # 1X2
        idx = 0 if hs > as_ else (2 if as_ > hs else 1)
        return idx, f"{hs}-{as_} -> {['HOME','DRAW','AWAY'][idx]}"
    if mk["nout"] == 2:      # HOME/AWAY, a draw voids (no valid outcome)
        if hs == as_:
            return None, f"{hs}-{as_} draw -> void (2-way market)"
        return (0 if hs > as_ else 1), f"{hs}-{as_} -> {'HOME' if hs > as_ else 'AWAY'}"
    return None, f"{mk['nout']}-way market — resolve by hand"


def submit(l1, method, args, keys, fee):
    latest = _get(f"{l1}/get_latest_block")
    payload = {"op": "call", "contract": BET_CID, "method": method, "args": args}
    tx = construct_blob_tx(keys, payload, max_block=int(latest["block_number"]) + 20, fee=fee)
    resp = _post(f"{l1}/submit_transaction", tx)
    return tx["txid"][:16], resp.get("message")


def secs_per_block(l1, n=20):
    """Measure the recent wall-clock seconds/block so lock heights land near real kickoff time (the
    live chain can run slower than the 6s target)."""
    try:
        tip = int(_get(f"{l1}/get_latest_block")["block_number"])
        a = _get(f"{l1}/get_block_number?number={tip - n}").get("block_timestamp")
        b = _get(f"{l1}/get_block_number?number={tip}").get("block_timestamp")
        if a and b and b > a:
            return max(1.0, (b - a) / n)
    except Exception:
        pass
    return 6.0


def thesportsdb_next(league, key):
    """Upcoming events for a TheSportsDB league id (free endpoint)."""
    try:
        d = _get(f"https://www.thesportsdb.com/api/v1/json/{key}/eventsnextleague.php?id={urllib.parse.quote(league)}")
        return (d or {}).get("events") or []
    except Exception:
        return []


def event_teams(e):
    """(home, away) from an event, falling back to splitting 'A vs B'."""
    home, away = (e.get("strHomeTeam") or "").strip(), (e.get("strAwayTeam") or "").strip()
    if not home or not away:
        parts = (e.get("strEvent") or "").split(" vs ")
        if len(parts) == 2:
            home, away = home or parts[0].strip(), away or parts[1].strip()
    return home, away


def kickoff_epoch(e):
    """UTC epoch seconds of an event's kickoff, or None."""
    ts = e.get("strTimestamp")
    if not ts:
        d, t = e.get("dateEvent"), e.get("strTime")
        ts = f"{d}T{t}" if d and t else None
    if not ts:
        return None
    try:
        return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return None


def main():
    global BET_CID
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "fill", "resolve", "void"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--exec", dest="exec_url", default=os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/"))
    ap.add_argument("--cid", default=BET_CID)
    ap.add_argument("--sportsdb-key", default=os.environ.get("SPORTSDB_KEY", "3"))
    ap.add_argument("--leagues", default=os.environ.get("BET_LEAGUES", ""), help="comma-separated TheSportsDB league ids (default: majors)")
    ap.add_argument("--max", type=int, default=int(os.environ.get("BET_FILL_MAX", "24")), help="max new markets to create per fill")
    ap.add_argument("--min-lead-min", type=int, default=30, help="skip matches kicking off sooner than this (need a betting window)")
    ap.add_argument("--void-hours", type=float, default=6.0, help="auto-void a market this many hours after kickoff if unresolved")
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    ap.add_argument("--submit", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args()
    BET_CID = args.cid

    root = _get(f"{args.exec_url}/exec/root")
    cursor = root.get("cursor")
    sto = read_storage(args.exec_url, BET_CID)
    markets = parse_markets(sto, cursor)

    if args.action == "fill":
        keys = load_keys()
        now = int(time.time())
        tip = int(_get(f"{args.l1}/get_latest_block")["block_number"])
        spb = secs_per_block(args.l1)
        existing_ev = {str(sto.get("ev", {}).get(m, "")) for m in sto.get("mk", {})}
        leagues = [x.strip() for x in (args.leagues.split(",") if args.leagues else DEFAULT_LEAGUES) if x.strip()]
        created = 0
        print(f"fill: tip {tip} · ~{spb:.1f}s/block · {len(leagues)} leagues · cap {args.max}"
              + ("" if args.submit else "  (DRY-RUN — add --submit to create)"))
        for lg in leagues:
            if created >= args.max:
                break
            for e in thesportsdb_next(lg, args.sportsdb_key):
                if created >= args.max:
                    break
                ev = str(e.get("idEvent") or "")
                if not ev or not ev.isdigit() or ev in existing_ev:
                    continue
                ko = kickoff_epoch(e)
                if ko is None:
                    continue
                lead = ko - now
                if lead < args.min_lead_min * 60:      # too soon / already kicked off -> no betting window
                    continue
                home, away = event_teams(e)
                if not home or not away:
                    continue
                title = (e.get("strEvent") or f"{home} vs {away}").strip()
                desc = "\n".join([title, home, "Draw", away])
                lock = tip + max(1, int(lead / spb))
                deadline = lock + max(1, int(args.void_hours * 3600 / spb))
                mid = int(ev)
                existing_ev.add(ev)
                created += 1
                tag = f"{e.get('strLeague', '?')}, kickoff {e.get('strTimestamp', '?')}Z"
                if args.submit:
                    txid, msg = submit(args.l1, "create_market", [mid, 3, lock, deadline, desc, "thesportsdb", ev], keys, args.fee)
                    print(f"  + {mid}  {title}  ({tag}) -> {msg}")
                else:
                    print(f"  [dry] {mid}  {title}  ({tag}, lock +{int(lead / spb)} blk)")
        print(f"\n{created} market(s) {'created' if args.submit else 'proposed'}"
              + ("" if args.submit else " — re-run with --submit to create them"))
        return

    if args.action == "void":
        if not args.rest:
            sys.exit("usage: void <marketId> [--submit]")
        keys = load_keys()
        mid = args.rest[0]
        if not args.submit:
            print(f"[dry-run] would void market #{mid} (refund everyone). Add --submit to post.")
            return
        txid, msg = submit(args.l1, "void", [int(mid)], keys, args.fee)
        print(f"void #{mid}: tx {txid} -> {msg}")
        return

    # list / resolve
    keys = load_keys() if args.action == "resolve" else None
    pending = [m for m in markets if m["locked"] and not m["resolved"] and not m["void"]]
    print(f"exec cursor {cursor} · {len(markets)} markets · {len(pending)} awaiting resolution\n")
    for m in markets:
        state = "VOID" if m["void"] else "RESOLVED" if m["resolved"] else ("LOCKED" if m["locked"] else "OPEN")
        print(f"#{m['id']}  [{state}]  {m['title']}  ({'/'.join(m['labels'])})  src={m['source']} ev={m['ev']}")

    if args.action == "list":
        # also show what the source currently reports for each pending market
        print("\n--- source results for pending markets ---")
        for m in pending:
            if m["source"] == "thesportsdb" and m["ev"]:
                st, hs, as_ = thesportsdb_result(m["ev"], args.sportsdb_key)
                print(f"#{m['id']} {m['title']}: status={st} score={hs}-{as_}")
            else:
                print(f"#{m['id']} {m['title']}: no automatic source (resolve by hand)")
        return

    # resolve
    print("\n--- resolution plan" + ("" if args.submit else " (DRY-RUN — add --submit to post)") + " ---")
    for m in pending:
        if m["source"] != "thesportsdb" or not m["ev"]:
            print(f"#{m['id']} SKIP — no automatic source")
            continue
        st, hs, as_ = thesportsdb_result(m["ev"], args.sportsdb_key)
        finished = isinstance(st, str) and ("Finished" in st or "FT" == st) and hs is not None
        if not finished:
            if m["past_deadline"]:
                print(f"#{m['id']} PAST DEADLINE, not finished (status={st}) -> void" + ("" if args.submit else " [dry-run]"))
                if args.submit:
                    txid, msg = submit(args.l1, "void", [int(m["id"])], keys, args.fee)
                    print(f"    void tx {txid} -> {msg}")
            else:
                print(f"#{m['id']} not final yet (status={st}) — skip")
            continue
        idx, reason = winning_outcome(m, hs, as_)
        if idx is None:      # e.g. a 2-way market that drew, or an unknown shape -> void
            print(f"#{m['id']} {reason} -> void" + ("" if args.submit else " [dry-run]"))
            if args.submit:
                txid, msg = submit(args.l1, "void", [int(m["id"])], keys, args.fee)
                print(f"    void tx {txid} -> {msg}")
            continue
        print(f"#{m['id']} resolve -> outcome {idx} ({m['labels'][idx]}) [{reason}]" + ("" if args.submit else " [dry-run]"))
        if args.submit:
            txid, msg = submit(args.l1, "resolve", [int(m["id"]), idx], keys, args.fee)
            print(f"    resolve tx {txid} -> {msg}")


if __name__ == "__main__":
    main()
