#!/usr/bin/env python3
"""bet_oracle.py — the resolver bot for the NADO Bet (parimutuel sports) zkVM contract.

Parimutuel = all stakes on a match pool together and the winners split the whole pot pro-rata — no house,
no bookmaker (see execnode/games/bet.py for the full plain-language explainer). A blockchain can't see the
real world, so each market names RESOLVER keys at creation. This script IS the official resolver's helper:
it reads the free public source named on each market (TheSportsDB by default), works out the winning
outcome, and submits resolve()/void() blob txs signed by its key. Markets it fills name this key as their
sole resolver (1-of-1); user-created markets name their own resolver sets — this tool just posts one key's
vote, so run one copy per key for an M-of-N panel.

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
from protocol import MIN_TX_FEE, TX_INCLUSION_DELAY

BET_CID = "066b76360e669c91d81e57197d0c88e3"   # execnode/games/bet.py (zkVM port, nonce "a5")
VOID_GRACE_SEC = 300   # wiggle room past the deadline before auto-voiding (the chain clock is only ~tens-of-seconds precise)
# Soccer competitions to seed 1X2 (home/draw/away) markets from (TheSportsDB league ids). Override with
# --leagues "4328,4335,…". The free key returns only the SINGLE next fixture per league, so BREADTH of leagues
# is what fills the board — especially with the European majors in their summer break (their next fixture is a
# far-off August one). The list below spans continents + divisions so whatever is in-season contributes a match;
# fill's soccer-guard skips any league id that (on the free key) maps to a non-soccer event. Internationals first
# so World Cup / continental ties surface. Kept moderate + paced (see fill) to stay under the free-key rate limit.
DEFAULT_LEAGUES = [
    "4429", "4480", "4481", "4485", "4422",          # World Cup · UCL · UEL · UECL · Copa Sudamericana
    "4328", "4329", "4335", "4332", "4331", "4334",  # EPL · EFL Championship · La Liga · Serie A · Bundesliga · Ligue 1
    "4337", "4344", "4346", "4354",                  # Eredivisie · Portugal Primeira · MLS · Ukrainian PL
    "4351", "4404", "4356", "4499", "4368",          # Brazil Serie A/B · Argentine Primera · Swedish Allsvenskan · Norway Eliteserien
    "4621", "4632", "4628", "4963",                  # Austrian Bundesliga · Danish 2nd · China League One · Finnish Ykkönen
]


def _get(url, timeout=15):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, body, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def read_storage(exec_url, cid):
    """The contract's full {map: {key: val}} storage, provisional tail included (so a just-submitted void/create
    is visible on the next run without waiting for finality — same fresh view the website reads)."""
    return _get(f"{exec_url}/exec/contract?ns=default&cid={cid}&provisional=1").get("storage", {})


def parse_markets(sto, chain_now):
    """Reconstruct every market from storage (mirrors static/bet.js parseMarket). lk/dl are WALL-CLOCK epoch
    seconds (the contract's TIME opcode); chain_now is the L1 block timestamp the contract gates on."""
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
            "locked": chain_now is not None and chain_now >= lock,
            # wiggle room: only treat a market as past-deadline once we're VOID_GRACE_SEC beyond it, so the
            # chain clock's tens-of-seconds imprecision can never trigger an auto-void right on the boundary.
            "past_deadline": chain_now is not None and chain_now >= deadline + VOID_GRACE_SEC,
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
    tip = int(latest["block_number"])
    payload = {"op": "call", "contract": BET_CID, "method": method, "args": args}
    tx = construct_blob_tx(keys, payload, max_block=tip + 20, fee=fee, min_block=tip + TX_INCLUSION_DELAY)
    resp = _post(f"{l1}/submit_transaction", tx)
    return tx["txid"][:16], resp.get("message")


def chain_time(l1):
    """The L1 tip's wall-clock timestamp — the same clock the contract's TIME opcode reads. Markets close/void
    by real time now, so this replaces the old block-height ↔ time conversion entirely (that conversion assumed a
    fixed block rate; when the rate drifted, height deadlines fired at the wrong real moment and voided live matches)."""
    try:
        return int(_get(f"{l1}/get_latest_block")["block_timestamp"])
    except Exception:
        return int(time.time())


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

    root = _get(f"{args.exec_url}/exec/root?ns=default&provisional=1")
    cursor = root.get("cursor")
    # the wall-clock the contract gates on: the exec node's applied block_ts, falling back to the L1 tip.
    chain_now = int(root.get("block_ts") or chain_time(args.l1))
    sto = read_storage(args.exec_url, BET_CID)
    markets = parse_markets(sto, chain_now)

    if args.action == "fill":
        keys = load_keys()
        # official markets name THIS oracle key as their sole resolver (threshold 1); users who create
        # their own markets from the UI name their own resolver set instead.
        resolver = keys["address"]
        # lk/dl are wall-clock epoch seconds now (the contract compares them to TIME), so there is no block-rate
        # conversion at all — kickoff maps to a fixed real instant regardless of how fast the chain runs.
        now = chain_now
        # Dedup by event, but only a LIVE market (neither voided nor resolved) blocks re-listing its event —
        # a postponed/voided/finished match may be listed again with fresh timing (create_market needs a fresh
        # market id, so a re-list gets a NEW id below; ev stays the same for source mapping).
        vd, dn = sto.get("vd", {}), sto.get("dn", {})
        live_ev = {str(sto.get("ev", {}).get(m, "")) for m in sto.get("mk", {}) if not vd.get(m) and not dn.get(m)}
        existing_mk = set(sto.get("mk", {}))
        leagues = [x.strip() for x in (args.leagues.split(",") if args.leagues else DEFAULT_LEAGUES) if x.strip()]
        created = 0
        print(f"fill: chain-time {now} · {len(leagues)} leagues · cap {args.max}"
              + ("" if args.submit else "  (DRY-RUN — add --submit to create)"))
        for li, lg in enumerate(leagues):
            if created >= args.max:
                break
            if li:
                time.sleep(0.3)   # pace the per-league calls so a wide list stays under the free-key rate limit
            for e in thesportsdb_next(lg, args.sportsdb_key):
                if created >= args.max:
                    break
                # soccer-guard: on the free key some league ids map to a non-soccer event (ice hockey, motorsport).
                # We only build 3-way 1X2 (HOME/DRAW/AWAY) markets, so anything that isn't soccer is skipped —
                # this makes it safe to seed a broad league list without minting nonsense markets.
                if (e.get("strSport") or "Soccer") != "Soccer":
                    continue
                ev = str(e.get("idEvent") or "")
                if not ev or not ev.isdigit() or ev in live_ev:
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
                lock = ko                                          # betting closes at kickoff (epoch secs)
                deadline = ko + int(args.void_hours * 3600)        # anyone may void this long after kickoff if unresolved
                # market id defaults to the event id; if that id is taken (a prior VOID market for the same match),
                # bump DETERMINISTICALLY (ev + k·OFFSET) to the next free id. Deterministic (not random) so two fills
                # racing before either's create is visible pick the SAME id — the contract's fresh-id gate then makes
                # the second a no-op revert instead of a duplicate market. OFFSET is huge so it never hits another ev.
                # zkVM market ids must be < 2^32 (composite-slot keys) — the offset is sized so an event id
                # (~7 digits) survives 4 relists before hitting the ceiling.
                RELIST_OFFSET = 10**9
                mid = int(ev)
                while str(mid) in existing_mk:
                    mid += RELIST_OFFSET
                if mid >= (1 << 32):
                    continue
                existing_mk.add(str(mid))
                live_ev.add(ev)
                created += 1
                tag = f"{e.get('strLeague', '?')}, kickoff {e.get('strTimestamp', '?')}Z"
                if args.submit:
                    txid, msg = submit(args.l1, "create_market", [mid, 3, lock, deadline, desc, "thesportsdb", ev, 1, resolver, 0, 0], keys, args.fee)
                    print(f"  + {mid}  {title}  ({tag}) -> {msg}")
                else:
                    print(f"  [dry] {mid}  {title}  ({tag}, closes in {int(lead / 60)} min)")
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
