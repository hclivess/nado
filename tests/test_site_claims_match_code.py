"""
The public website states what the code does — and says it in every language it offers.

Run: python3 tests/test_site_claims_match_code.py

Pure file reads: protocol.py is parsed as TEXT (never imported), nothing touches a node, a database or the network.

Every check here is a claim the 2026-09-29 site review found false on nadochain.com while the code said otherwise:

  * /emission's simulator used M_MIN = 0.1656 — the curve's FLOOR at 100 % bonded — as the curve's constant, so the
    whole modelled mint curve sat above consensus (m(r) = 0.15 + 0.85·e^(−4r), protocol.BOND_ELASTIC_MULT_BPS), and
    its badge put the perpetual tail at ~52k NADO/yr when BASE_SUBSIDY × m(1) at 6 s blocks is ~87k.
  * /emission's "Collect Rewards" button had no .btn rule on that page: dark text on a dark page, invisible.
  * the landing page said a mining farm was "impossible" (device gating is LINEAR — a farm pays per device), that
    there was "no pre-quantum crypto anywhere" (attestation checks the makers' classical certificates), that "a relay
    assembles the block" (every node builds it), that consensus overhead was constant for "16 or 16 million miners",
    that VBS keys were refused (the VBS AAGUID is accepted: the TPM's certify proof decides), and quoted a
    "Start mining" button the wallet does not have.
  * eleven languages still called the network "alpha" / "testnet" after betanet; /emission said "testnet-stage alpha".
  * two keys whose translations carry <b> were rendered with textContent, so readers saw literal "<b>" tags.
  * the sitemap listed a 301 (/games) and another host (get.nadochain.com).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "website")
fails = []


def ck(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    if not cond:
        fails.append(msg)


def read(*p):
    return open(os.path.join(*p), encoding="utf8").read()


PROTO = read(ROOT, "protocol.py")


def const(name):
    m = re.search(r"^%s\s*=\s*([0-9_]+)" % name, PROTO, re.M)
    return int(m.group(1).replace("_", ""))


table = [int(x) for x in re.findall(r"\d+", re.search(r"^BOND_ELASTIC_MULT_BPS\s*=\s*\[(.*?)\]", PROTO, re.S | re.M).group(1))]
BASE = const("BASE_SUBSIDY") / 1e10              # 1 NADO = 10^10 raw
BLOCK_TIME = const("BLOCK_TIME")

index = read(WEB, "index.html")
emission = read(WEB, "emission.html")
production = read(WEB, "production.html")
apps = read(WEB, "apps.html")
T = json.loads(re.search(r"<script>window.__NADO_I18N__=(\{.*?\});?</script>", index).group(1))

print("emission page vs consensus:")
# The simulator no longer carries the constants: it imports them from the relay's /protocol.js (protocol.CLIENT_EXPORTS,
# tests/test_constant_mirrors.py renders and pins that module). What this page must still get right is HOW it uses them.
ck("protocol.js" in emission and re.search(r"await import\(PROTOCOL_URL\)", emission) is not None,
   "the simulator imports the chain's constants from the relay's /protocol.js")
for name in ("BASE_SUBSIDY", "DENOMINATION", "BOND_ELASTIC_MULT_BPS", "BLOCK_TIME"):
    ck(re.search(r"\bP\.%s\b" % name, emission) is not None, f"the simulator reads {name} from the imported module")
ck(re.search(r"\b(M_MIN|K|BLOCK_TIME|BASE)\s*=\s*[0-9]", emission) is None,
   "no simulator constant is declared as a literal any more (BASE / M_MIN / K / BLOCK_TIME)")
ck(re.search(r"MULT\[Math\.max\(0,Math\.min\(100,Math\.floor\(r\*100", emission) is not None,
   "m(r) indexes BOND_ELASTIC_MULT_BPS by whole percent, as ops/block_ops does (no float formula)")
tail_k = round(BASE * table[100] / 10000 * 365 * 86400 / BLOCK_TIME / 1000)
stated = set(int(x) for x in re.findall(r"(\d+)k(?: NADO)?/yr", emission))
ck(stated == {tail_k}, f"every 'Nk NADO/yr' tail figure on /emission is the consensus tail, ~{tail_k}k (found {sorted(stated)})")
ck(re.search(r"^\s*\.btn\{", emission, re.M) is not None, "emission.html defines the base .btn its nav CTA uses")

print("\nclaims the code contradicts are gone (every page, every language):")
langs_text = [index, emission, production, apps] + [json.dumps(T, ensure_ascii=False)]
blob = "\n".join(langs_text)
for pat, why in [
    (r"farm impossible|makes a mining farm impossible", "farms are not impossible — each identity costs a device"),
    (r"[Nn]o pre-quantum crypto", "attestation checks classical vendor certificates"),
    (r"relay assembles the block", "every node builds the block"),
    (r"16 million", "no million-miner claim: validator traffic is constant, open-lane renewals are not"),
    (r"VBS-only keys are refused|VBS-only key is the usual reason", "the VBS AAGUID is accepted"),
    (r"142-line|1,000,000×", "stale line counts / 10^6 upper bound only"),
    (r"Start mining", "the wallet's button is 'Start collecting'"),
    (r"instantly mining", "registration needs a device attestation"),
    (r"testnet-stage|\balpha\b|\bAlpha\b", "the network is betanet (pre-mainnet)"),
]:
    ck(re.search(pat, blob) is None, f"no '{pat}' ({why})")
ck("Start collecting" in index, "the landing page quotes the wallet's real button label")
ALPHA = r"alfa|alpha|альфа|アルファ|알파|ألفا|अल्फ़ा|testnet|тестнет|テストネット|테스트넷|测试网|टेस्टनेट|test ağı"
for lang in T:
    ck(not re.search(ALPHA, T[lang].get("foot.tag", ""), re.I), f"{lang} foot.tag does not call the network alpha/testnet")

print("\nlanding page translations:")
plain = set(re.findall(r'data-i18n="([^"]+)"', index))
htmlk = set(re.findall(r'data-i18n-html="([^"]+)"', index))
checked = set(re.findall(r'paint\("(dev\.check\.\w+)"', index))
for lang, d in T.items():
    missing = sorted((plain | htmlk | checked) - set(d))
    ck(not missing, f"{lang}: every data-i18n key on the page is translated" + (f" (missing {missing})" if missing else ""))
    marked = sorted(k for k in plain if re.search(r"<[a-z/]", d.get(k, "")))
    ck(not marked, f"{lang}: no key rendered as text carries markup" + (f" ({marked})" if marked else ""))
en_body = index.split("<script>window.__NADO_I18N__")[0]
for m in re.finditer(r'data-i18n="([^"]+)">([^<]*<(?:b|i|br|span)\b)', en_body):
    ck(False, f"English default of {m.group(1)} carries markup but is rendered as text")

print("\nsitemap:")
sm = read(WEB, "sitemap.xml")
locs = re.findall(r"<loc>([^<]+)</loc>", sm)
ck(all(u.startswith("https://nadochain.com/") for u in locs), "every sitemap URL is on nadochain.com (a sitemap covers one host)")
ck("https://nadochain.com/games" not in locs, "no redirecting URL (/games is a 301 to /apps)")
ck("https://nadochain.com/apps" in locs, "/apps is listed")

print("\n/apps:")
ck('<link rel="canonical" href="https://nadochain.com/apps"' in apps, "apps.html has a canonical URL")
ck('property="og:title"' in apps and 'property="og:image"' in apps, "apps.html has Open Graph tags")

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILURES"))
sys.exit(1 if fails else 0)
