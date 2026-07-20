"""
Every LIVE game must actually be reachable — not merely present in the repo.

Run: python3 tests/test_site_deployed.py

This exists because of a fault that kept repeating: writing a file into the repo and treating that as
shipped. The repo is not the server. Two things in particular are hand-carried and therefore drift:

  * `website/nginx-<slug>.nadochain.com.conf` has to be INSTALLED into /etc/nginx and the config reloaded.
    Until it is, the subdomain does not fall through to nothing — nginx serves the alphabetically FIRST
    server block instead, so a brand-new game silently shows a completely different game. autogame.
    nadochain.com served Battleship for exactly this reason, and the page looked perfectly fine.
  * `website/games.html` (the lobby) is COPIED to /var/www/nadochain.com. Until it is, a new game is
    invisible to every visitor no matter how live its contract is.

The repo-only checks run anywhere. The deployment checks only run where the server actually is, and say so
rather than passing silently — a check that skips itself and reports PASS is how this got missed.

NOTE for whoever syncs the lobby: /var/www/nadochain.com/index.html legitimately DIFFERS from the repo copy
(it carries a production analytics tag the repo does not). Copy games.html specifically; never rsync the
directory wholesale.
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEBSITE = os.path.join(ROOT, "website")
STATIC = os.path.join(ROOT, "static")
SITES_ENABLED = "/etc/nginx/sites-enabled"
WWW = "/var/www/nadochain.com"

fails = []
notes = []


def ck(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def live_games():
    """(slug, url) for every entry in the lobby marked live:true."""
    src = open(os.path.join(WEBSITE, "games.html")).read()
    out = []
    for m in re.finditer(r"\{\s*svg:SVG\.\w+,(.*?)\}", src, re.S):
        body = m.group(1)
        if "live:true" not in body.replace(" ", ""):
            continue
        slug = re.search(r'slug:"([^"]+)"', body)
        url = re.search(r'url:"([^"]+)"', body)
        if slug:
            out.append((slug.group(1), url.group(1) if url else ""))
    return out


def host_of(url):
    """The subdomain label a game is served on. This is NOT always the lobby slug — tictactoe is listed as
    slug "ttt" (its i18n key prefix) but lives on tictactoe.nadochain.com as static/tictactoe.html. Deriving
    the page and the vhost from the URL is what the server actually does."""
    m = re.match(r"https?://([a-z0-9-]+)\.nadochain\.com", url or "")
    return m.group(1) if m else None


def main():
    games = live_games()
    print(f"lobby lists {len(games)} live games\n")
    assert games, "parsed no live games out of website/games.html — the parser is stale, fix it"

    print("repo:")
    for slug, url in games:
        host = host_of(url)
        if not host:
            continue                     # not on its own subdomain (hub-hosted) — nothing to install
        ck(os.path.exists(os.path.join(STATIC, f"{host}.html")), f"static/{host}.html exists")
        conf = os.path.join(WEBSITE, f"nginx-{host}.nadochain.com.conf")
        ck(os.path.exists(conf), f"website/nginx-{host}.nadochain.com.conf is CHECKED IN "
                                 f"(a vhost that only exists on the server is lost on any rebuild)")

    on_server = os.path.isdir(SITES_ENABLED) and os.path.isdir(WWW)
    if not on_server:
        print("\ndeployment: SKIPPED — not on the web server "
              f"({SITES_ENABLED} / {WWW} not present). The checks that actually catch the drift did NOT run.")
        return 1 if fails else 0

    print("\ndeployment (this is the part that catches the real fault):")
    for slug, url in games:
        host = host_of(url)
        if not host:
            continue
        ck(os.path.exists(os.path.join(SITES_ENABLED, f"{host}.nadochain.com")),
           f"{host}.nadochain.com vhost is INSTALLED and enabled")

    served = os.path.join(WWW, "games.html")
    if os.path.exists(served):
        same = open(served).read() == open(os.path.join(WEBSITE, "games.html")).read()
        ck(same, "the served lobby matches website/games.html "
                 "(cp website/games.html /var/www/nadochain.com/games.html)")
    else:
        ck(False, f"{served} exists")

    # nginx must also be happy, or a reload will refuse and the vhost stays dark
    try:
        r = subprocess.run(["nginx", "-t"], capture_output=True, text=True, timeout=30)
        ck(r.returncode == 0, "nginx config test passes")
    except Exception as e:
        notes.append(f"could not run `nginx -t`: {e}")

    return 1 if fails else 0


if __name__ == "__main__":
    rc = main()
    for n in notes:
        print("  note:", n)
    print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES"))
    sys.exit(rc)
