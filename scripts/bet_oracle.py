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

# The live contract id is DISCOVERED, never pasted here. It used to be a constant, and when the contract was
# redeployed the constant kept pointing at a dead cid: every fill/resolve 404'd against a contract that no
# longer existed, the timer failed silently for days, and the site showed "no matches" with nothing in the
# logs to explain it. A hardcoded id is a bug waiting for the next redeploy, so resolve_cid() asks, in order:
# an explicit --cid, the cid the WEBSITE is using (static/bet.js — the deployed truth, and the one place that
# is guaranteed to be current because it is what players load), then a shape match against the exec node's
# own contract list. Every candidate is verified to exist and expose the bet methods before it is used.
BET_CID = None
BET_METHODS = {"create_market", "bet", "resolve", "void", "claim"}   # the signature of a bet contract
CLIENT_JS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "bet.js")
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


def _contract(exec_url, cid):
    """The deployed contract, or None if the exec node doesn't have it."""
    try:
        c = _get(f"{exec_url}/exec/contract?ns=default&cid={cid}")
        return c if c and BET_METHODS.issubset(set(c.get("methods") or [])) else None
    except Exception:
        return None


def _cid_from_client():
    """The cid static/bet.js is pointing at — what the website actually reads and writes."""
    try:
        import re
        with open(CLIENT_JS) as f:
            m = re.search(r'const\s+CID\s*=\s*"([0-9a-f]{32})"', f.read())
        return m.group(1) if m else None
    except Exception:
        return None


def resolve_cid(exec_url, explicit=None):
    """The live bet contract id. Tries --cid, then the website's cid, then a method-shape match over every
    deployed contract; each candidate must EXIST on this exec node and expose the bet methods. Raises with
    what it tried, so a redeploy can never turn into a silent no-op again."""
    tried = []
    for src, cid in (("--cid", explicit), ("static/bet.js", _cid_from_client())):
        if not cid:
            continue
        tried.append(f"{src}={cid}")
        if _contract(exec_url, cid):
            return cid, src
    try:
        for c in (_get(f"{exec_url}/exec/contracts?ns=default").get("contracts") or []):
            if BET_METHODS.issubset(set(c.get("methods") or [])):
                return c["cid"], "exec-node discovery"
    except Exception as ex:
        tried.append(f"discovery failed: {ex}")
    raise SystemExit("bet_oracle: no live bet contract found on " + exec_url
                     + (" (tried " + ", ".join(tried) + ")" if tried else ""))


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


def submit(l1, method, args, keys, fee, retries=2):
    """Sign and submit one contract call. NEVER raises: a single dropped connection used to abort the whole
    run mid-fill (the node restarts, or a burst of submissions trips it), leaving a half-seeded board and a
    systemd unit in `failed` with no markets to show for it. One retry, then report and move on."""
    for attempt in range(retries + 1):
        try:
            tip = int(_get(f"{l1}/get_latest_block")["block_number"])
            payload = {"op": "call", "contract": BET_CID, "method": method, "args": args}
            tx = construct_blob_tx(keys, payload, max_block=tip + 20, fee=fee, min_block=tip + TX_INCLUSION_DELAY)
            resp = _post(f"{l1}/submit_transaction", tx)
            return tx["txid"][:16], resp.get("message")
        except Exception as ex:
            if attempt >= retries:
                return None, f"submit failed: {type(ex).__name__}: {ex}"
            time.sleep(2)


def chain_time(l1):
    """The L1 tip's wall-clock timestamp — the same clock the contract's TIME opcode reads. Markets close/void
    by real time now, so this replaces the old block-height ↔ time conversion entirely (that conversion assumed a
    fixed block rate; when the rate drifted, height deadlines fired at the wrong real moment and voided live matches)."""
    try:
        return int(_get(f"{l1}/get_latest_block")["block_timestamp"])
    except Exception:
        return int(time.time())


def espn_result(ev):
    """ESPN's public summary for one event -> (status, home_score, away_score). Free, keyless and
    CORS-open, which is why the website can browse the same feed the resolver reads: a market listed from
    the fixture picker can be checked by the bettor against the exact source that will settle it."""
    try:
        d = _get("https://site.api.espn.com/apis/site/v2/sports/soccer/all/summary?event="
                 + urllib.parse.quote(str(ev)))
        c = ((d or {}).get("header") or {}).get("competitions") or []
        if not c:
            return (None, None, None)
        c = c[0]
        st = (((c.get("status") or {}).get("type") or {}).get("description") or "").strip()
        comp = c.get("competitors") or []
        home = next((x for x in comp if x.get("homeAway") == "home"), None)
        away = next((x for x in comp if x.get("homeAway") == "away"), None)
        if not home or not away or home.get("score") in (None, "") or away.get("score") in (None, ""):
            return (st or "unknown", None, None)
        return (st or "Final", int(home["score"]), int(away["score"]))
    except Exception as ex:
        return (f"fetch-error: {ex}", None, None)


def source_result(source, ev, sportsdb_key):
    """Ask the market's OWN named source for the result. A market names its source at creation and the
    resolver must honour that — reading a different feed than the one advertised to bettors would settle
    a bet on evidence they were never shown."""
    if source == "thesportsdb":
        return thesportsdb_result(ev, sportsdb_key)
    if source == "espn":
        return espn_result(ev)
    return (None, None, None)


# a source is auto-resolvable when this bot knows how to read it AND the market names an event on it
RESOLVABLE = ("thesportsdb", "espn")
# ESPN reports finished games as "Final"/"FT"; TheSportsDB as "Match Finished". Both must be recognised or
# the bot silently lets a settled match run to its deadline and void — refunding a decided bet.
def _is_final(st):
    return isinstance(st, str) and ("finished" in st.lower() or st.strip().upper() in ("FT", "FINAL"))


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



# ---- normalized fixture feeds ---------------------------------------------------------------------
# Each source yields the SAME dict, so fill() has one code path: {ev, home, away, title, league, kickoff}.
# ESPN is asked for a six-week window because its scoreboard defaults to today (empty most days); that one
# parameter is the difference between 1 fixture per competition and ~20, which is what keeps the board full
# between the free tier's stingy "next event only" answers.
ESPN_LEAGUES = ["fifa.world", "uefa.champions", "uefa.europa", "eng.1", "esp.1", "ita.1", "ger.1",
                "fra.1", "ned.1", "por.1", "usa.1", "bra.1", "arg.1", "mex.1"]
ESPN_WINDOW_DAYS = 45


def espn_next(league):
    """Upcoming fixtures for an ESPN soccer league slug, normalized."""
    try:
        now = int(time.time())
        dd = lambda t: time.strftime("%Y%m%d", time.gmtime(t))
        d = _get("https://site.api.espn.com/apis/site/v2/sports/soccer/" + urllib.parse.quote(league)
                 + f"/scoreboard?dates={dd(now)}-{dd(now + ESPN_WINDOW_DAYS * 86400)}")
    except Exception:
        return []
    lg = (((d or {}).get("leagues") or [{}])[0] or {}).get("name") or league
    out = []
    for e in (d or {}).get("events") or []:
        comp = ((e.get("competitions") or [{}])[0] or {}).get("competitors") or []
        home = ((next((x for x in comp if x.get("homeAway") == "home"), {}) or {}).get("team") or {}).get("displayName") or ""
        away = ((next((x for x in comp if x.get("homeAway") == "away"), {}) or {}).get("team") or {}).get("displayName") or ""
        ko = _iso_epoch(e.get("date"))
        if not (e.get("id") and home and away and ko):
            continue
        out.append({"ev": str(e["id"]), "home": home, "away": away,
                    "title": f"{home} vs {away}", "league": lg, "kickoff": ko})
    return out


def _iso_epoch(s):
    """epoch seconds from an ISO timestamp that may or may not carry a zone (the feeds are UTC either way)."""
    if not s:
        return None
    s = s.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return calendar.timegm(time.strptime(s[:len(time.strftime(fmt))], fmt))
        except Exception:
            continue
    return None


def sportsdb_next_norm(league, key):
    """thesportsdb_next, normalized to the shared fixture shape (soccer only — see the soccer guard)."""
    out = []
    for e in thesportsdb_next(league, key):
        if (e.get("strSport") or "Soccer") != "Soccer":
            continue
        ev = str(e.get("idEvent") or "")
        home, away = event_teams(e)
        ko = kickoff_epoch(e)
        if not (ev.isdigit() and home and away and ko):
            continue
        out.append({"ev": ev, "home": home, "away": away,
                    "title": (e.get("strEvent") or f"{home} vs {away}").strip(),
                    "league": e.get("strLeague") or "?", "kickoff": ko})
    return out


def main():
    global BET_CID
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["list", "fill", "resolve", "void"])
    ap.add_argument("rest", nargs="*")
    ap.add_argument("--l1", default=os.environ.get("NADO_L1_URL", "http://127.0.0.1:9173").rstrip("/"))
    ap.add_argument("--exec", dest="exec_url", default=os.environ.get("NADO_EXEC_URL", "http://127.0.0.1:9273").rstrip("/"))
    ap.add_argument("--cid", default=None, help="pin the contract id (default: discover — see resolve_cid)")
    ap.add_argument("--sportsdb-key", default=os.environ.get("SPORTSDB_KEY", "3"))
    ap.add_argument("--sources", default=os.environ.get("BET_SOURCES", "all"),
                    choices=["all", "espn", "thesportsdb"], help="which public feeds to seed fixtures from")
    ap.add_argument("--leagues", default=os.environ.get("BET_LEAGUES", ""), help="comma-separated TheSportsDB league ids (default: majors)")
    ap.add_argument("--max", type=int, default=int(os.environ.get("BET_FILL_MAX", "24")), help="max new markets to create per fill")
    ap.add_argument("--min-lead-min", type=int, default=30, help="skip matches kicking off sooner than this (need a betting window)")
    ap.add_argument("--void-hours", type=float, default=6.0, help="auto-void a market this many hours after kickoff if unresolved")
    ap.add_argument("--fee", type=int, default=MIN_TX_FEE)
    ap.add_argument("--submit", action="store_true", help="actually post (default: dry-run)")
    args = ap.parse_args()
    BET_CID, _src = resolve_cid(args.exec_url, args.cid)
    print(f"bet contract {BET_CID} (via {_src})")

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
        # (source, league) pairs. Both feeds are free, keyless and CORS-open — the same two the website's
        # fixture picker browses, so a market the bot lists can be checked by a bettor against the exact
        # source that will settle it. ESPN goes first because its date-window query returns whole
        # fixture lists rather than the free tier's single next event.
        feeds = ([("espn", lg) for lg in ESPN_LEAGUES] if args.sources in ("all", "espn") else []) \
              + ([("thesportsdb", lg) for lg in leagues] if args.sources in ("all", "thesportsdb") else [])
        created = 0
        print(f"fill: chain-time {now} · {len(feeds)} feeds · cap {args.max}"
              + ("" if args.submit else "  (DRY-RUN — add --submit to create)"))
        for li, (src, lg) in enumerate(feeds):
            if created >= args.max:
                break
            if li:
                time.sleep(0.3)   # pace the per-league calls so a wide list stays under the free-key rate limit
            fixtures = espn_next(lg) if src == "espn" else sportsdb_next_norm(lg, args.sportsdb_key)
            for e in fixtures:
                if created >= args.max:
                    break
                ev = e["ev"]
                if ev in live_ev:
                    continue
                ko = e["kickoff"]
                lead = ko - now
                if lead < args.min_lead_min * 60:      # too soon / already kicked off -> no betting window
                    continue
                home, away, title = e["home"], e["away"], e["title"]
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
                if not ev.isdigit():
                    continue                        # market ids are ints (composite-slot keys)
                mid = int(ev)
                while str(mid) in existing_mk:
                    mid += RELIST_OFFSET
                if mid >= (1 << 32):
                    continue
                existing_mk.add(str(mid))
                live_ev.add(ev)
                created += 1
                tag = f"{e['league']}, kickoff {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(ko))}, via {src}"
                if args.submit:
                    txid, msg = submit(args.l1, "create_market", [mid, 3, lock, deadline, desc, src, ev, 1, resolver, 0, 0], keys, args.fee)
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
            if m["source"] in RESOLVABLE and m["ev"]:
                st, hs, as_ = source_result(m["source"], m["ev"], args.sportsdb_key)
                print(f"#{m['id']} {m['title']}: status={st} score={hs}-{as_}")
            else:
                print(f"#{m['id']} {m['title']}: no automatic source (resolve by hand)")
        return

    # resolve
    print("\n--- resolution plan" + ("" if args.submit else " (DRY-RUN — add --submit to post)") + " ---")
    for m in pending:
        if m["source"] not in RESOLVABLE or not m["ev"]:
            print(f"#{m['id']} SKIP — no automatic source")
            continue
        st, hs, as_ = source_result(m["source"], m["ev"], args.sportsdb_key)
        finished = _is_final(st) and hs is not None
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
