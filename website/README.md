# nadochain.com — marketing site + interface hosting

A tiny static landing page for **nadochain.com**, plus a reverse-proxy vhost so
**get.nadochain.com** serves the in-node NADO Interface (`static/interface.html`) over the domain.

## Files
- `index.html` — the landing page (self-contained; no build step). Deploy to the web root.
- `nginx-nadochain.com.conf` — the nginx vhost (marketing site + `get.` proxy).

## Deploy
```bash
# 1) web root + brand assets (copied from the repo's graphics/)
sudo mkdir -p /var/www/nadochain.com
sudo cp website/index.html /var/www/nadochain.com/
sudo cp graphics/logo.svg      /var/www/nadochain.com/logo.svg
sudo cp graphics/bauhaus.png   /var/www/nadochain.com/wordmark.png
sudo cp graphics/180_logo.png  /var/www/nadochain.com/logo.png
sudo cp graphics/favicon.ico   /var/www/nadochain.com/favicon.ico

# 2) nginx vhost
sudo cp website/nginx-nadochain.com.conf /etc/nginx/sites-available/nadochain.com
sudo ln -sfn /etc/nginx/sites-available/nadochain.com /etc/nginx/sites-enabled/nadochain.com
sudo nginx -t && sudo systemctl reload nginx
```

## DNS
Point these records at the server that runs the NADO node + nginx (`A` = its IPv4, `AAAA` = its IPv6):
`nadochain.com`, `www.nadochain.com`, `get.nadochain.com`.

### Cloudflare (this deployment is proxied through Cloudflare)
The records are the orange-cloud (proxied) A/AAAA records to the origin. Cloudflare terminates public HTTPS with
its own edge cert and connects to the origin on `:443`, so:
- The origin must serve valid HTTPS for these names (Let's Encrypt cert below) — set the Cloudflare **SSL/TLS
  mode to "Full (strict)"**.
- This vhost serves the SAME content on `:80` and `:443` with NO origin-side HTTP→HTTPS redirect, so there is no
  redirect loop regardless of the Cloudflare SSL mode; Cloudflare's "Always Use HTTPS" handles the public redirect.

## HTTPS cert (Let's Encrypt on the origin)
The ACME HTTP-01 challenge passes through Cloudflare, so certbot works even while proxied:
```bash
sudo certbot certonly --webroot -w /var/www/html \
  -d nadochain.com -d www.nadochain.com -d get.nadochain.com
sudo systemctl reload nginx
```
(The vhost already references `/etc/letsencrypt/live/nadochain.com/…`; certbot auto-renews.)

## How get.nadochain.com works
`get.` reverse-proxies `/` to the L1 node (`127.0.0.1:9173`) and `/exec/` to the shielded-pool /
execution node (`127.0.0.1:9273`). The interface's `execBase()` uses the same origin (no `:9273`) when it
is served behind a proxy on 80/443, so the whole app — wallet, miner, explorer, and shielded pool — works
through one HTTPS origin.
