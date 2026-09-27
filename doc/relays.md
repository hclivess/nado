# Relays — where a web wallet talks to the chain, and how it switches

A **relay** is any NADO node's HTTP API as seen from a browser. The web wallet (`static/interface.js`)
reads balances, mining status and blocks from one, and submits every signed transaction through it. The
relay is not trusted with anything that matters — a transaction binds to `chain_id`, the node it lands on
validates it fully, and balances are re-derived by every node — but it *is* a single point of
availability: when `get.nadochain.com` stalls, every wallet loaded from it goes "relay offline" together.

## Automatic relay switching (wallet side)

The wallet keeps a **relay pool** next to its home relay (the origin it was served from, or the URL the user
typed in Settings):

1. Every 5 minutes it asks its current relay `GET /relays` for the other nodes on this chain and stores
   the usable ones (with their live heights) in `localStorage`, so a browser whose home relay is down at
   boot still has candidates.
2. After **3 consecutive hard failures** of the current relay (timeouts, connection errors, 5xx — never a
   429 rate limit, and never a 404 from an older node) it probes candidates, home first if it had left
   home, then by height. A candidate is adopted only if its own `/status` reports the **same `chain_id`**
   and a tip within **20 blocks** of the best tip the wallet knows about.
3. The header shows `via <host> · auto` while it is away. Every 2 minutes it re-probes home and switches
   back the moment home answers — the user's relay choice is bridged over, never replaced.
4. The execution-node base follows the relay automatically (`/exec` and `/da` on the same origin, or
   `:9273` on the same host for a bare node).

Nothing in `/relays` is trusted: a listed node is used only after it passed the chain + height checks, and
the node's own "Wrong or missing chain id" rejection backstops every signed transaction.

### What one lying relay cannot do (2026-09-27)

Pool heights are **self-reported**, so any height a relay claims is treated as a claim:

- **The wallet's tip estimate** (`relayTipEstimate`) is the pool's highest height, but never more than
  `RELAY_LEAD_MAX` (30) blocks above the pool's **median**. The propagation guard (`guardFrom`), the duty window and
  the failover ranking all use it. Before this, one relay claiming height 10^9 put every transaction's `min_block`
  past its `max_block` (nothing the wallet signed could land) and ranked itself first for failover.
- **Failover acceptance** compares a candidate with the median, which a single liar cannot move.
- **When home is unreachable** — exactly when failover happens — a candidate is adopted only if at least one other
  pool relay holds the **same finalized block** (`relayCorroborated`); with no other relay to ask it is used as before.
- **Programs are downloaded from home only.** The TPM enrolment helper and its checksum are built from the home
  relay (`enrolBase`), never from a failover relay a stranger may be running.
- **`/relays` clamps** each peer's reported height to this node's tip + `_RELAYS_LEAD_MAX` (30) before handing it to
  wallets. Tests: `tests/test_relay_trust.mjs`, `tests/test_guard_from_best_height.mjs`.

## What a browser can actually reach

Every node speaks **plain HTTP** on the API port (`9173`). A wallet served over **HTTPS** cannot fetch
`http://…` — browsers block mixed content — so to a wallet on `https://get.nadochain.com` a bare
`http://ip:9173` peer is invisible. Two consequences:

- A miner who loads the wallet from their **own node over http** (`http://<ip>:9173/`) gets the whole
  peer set as failover candidates with no configuration at all.
- For everyone else, failover targets have to be nodes whose operators put **TLS** in front and
  **advertise** the public origin. That is the opt-in below.

## Publishing your node as a relay (operator side)

1. Front the node with TLS the way `get.nadochain.com` is (nginx + Let's Encrypt): the L1 API at `/`,
   the exec node at `/exec/` and `/da/` (`nado.py` serves the wallet itself at `/`, so the same host can
   also serve the wallet). The nginx block used in production is reproduced at the end of this page.
2. Tell the node its public origin — either

       NADO_PUBLIC_RELAY_URL=https://relay.example.org

   in the service environment, or `"public_relay_url": "https://relay.example.org"` in
   `private/config.json` — and restart. Scheme + host[:port] only, no path.
3. Verify: `GET /status` on your node now carries `"relay_url": "https://relay.example.org"`, and within a
   peer-loop pass every peer's `GET /relays` lists it. Wallets pick it up at their next pool refresh.

An unset value advertises nothing (`relay_url: null`); the node is still listed by its bare `api`
address for http-loaded wallets.

## `GET /relays`

```json
{"chain_id": "betanet-5",
 "relays": [
   {"self": true,  "ip": "38.242.201.206", "url": "https://get.nadochain.com", "api": "http://38.242.201.206:9173",
    "address": "ebd2…", "chain_id": "betanet-5", "height": 82901, "finalized": 82851, "version": "…", "node_type": "archive"},
   {"self": false, "ip": "185.238.249.208", "url": null, "api": "http://185.238.249.208:9173", …}
 ]}
```

Peers come from the node's `status_pool`, which `peer_loop` already gates on genesis hash and chain — a
node on a foreign generation never appears. Rate-limited 60/min per IP.

## Production nginx block (get.nadochain.com)

```nginx
server {
    listen 443 ssl http2;  listen [::]:443 ssl http2;
    server_name relay.example.org;
    ssl_certificate     /etc/letsencrypt/live/relay.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/relay.example.org/privkey.pem;

    location /exec/ { proxy_pass http://127.0.0.1:9273; proxy_http_version 1.1; proxy_read_timeout 300; client_max_body_size 20m;
                      proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; }
    location /da/   { proxy_pass http://127.0.0.1:9273; proxy_http_version 1.1; proxy_read_timeout 300; client_max_body_size 20m;
                      proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; }
    location = /    { proxy_pass http://127.0.0.1:9173/static/interface.html; proxy_http_version 1.1; proxy_set_header Host $host; }
    location /      { proxy_pass http://127.0.0.1:9173; proxy_http_version 1.1; proxy_read_timeout 300; client_max_body_size 20m;
                      proxy_set_header Host $host; proxy_set_header X-Real-IP $remote_addr; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; }
}
```

**`trusted_proxies` is REQUIRED, not cosmetic.** Add your proxy's address(es) to `trusted_proxies` in
`private/config.json` (`["127.0.0.1", "::1"]` for a same-host nginx). Without it every proxied request resolves
to the proxy's own loopback address: the per-IP rate limits and the anti-Sybil registration budget see one
client, and — before 2026-09-01 — the loopback-authorized operator endpoints (`/terminate`, `/log`,
`/force_sync`, `/health`) were open to the world through the proxy. Since 2026-09-01 the node refuses the
loopback shortcut for any request carrying a forwarding header (`nado._is_local_request`), so a missing
`trusted_proxies` fails closed — but you still want it for the rate limits.
