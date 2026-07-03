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

## DNS (do this first — at your registrar)
Point these records at the server that runs the NADO node + nginx:

| Record | Type | Value |
|--------|------|-------|
| `nadochain.com`      | A / AAAA | `<server IPv4>` / `<server IPv6>` |
| `www.nadochain.com`  | A / AAAA | `<server IPv4>` / `<server IPv6>` |
| `get.nadochain.com`  | A / AAAA | `<server IPv4>` / `<server IPv6>` |

## HTTPS (after DNS resolves to this server)
```bash
sudo certbot --nginx -d nadochain.com -d www.nadochain.com -d get.nadochain.com
```
certbot rewrites the vhost to add the `443` listeners and an HTTP→HTTPS redirect.

## How get.nadochain.com works
`get.` reverse-proxies `/` to the L1 node (`127.0.0.1:9173`) and `/exec/` to the shielded-pool /
execution node (`127.0.0.1:9273`). The interface's `execBase()` uses the same origin (no `:9273`) when it
is served behind a proxy on 80/443, so the whole app — wallet, miner, explorer, and shielded pool — works
through one HTTPS origin.
