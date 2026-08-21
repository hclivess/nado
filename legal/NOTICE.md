# Third-Party Notices

NADO is licensed under the **GNU Affero General Public License v3.0** — see `LICENSE`.
Copyright © 2022–2026 the NADO authors and contributors (see `git log`).

The Rust crates under `native/` and `wasm/` are part of the same work and carry the same
AGPL-3.0-or-later licence (`license` field in each `Cargo.toml`).

This file lists third-party software included in, or required by, this repository, with
its licence. Licences listed here are all compatible with AGPL-3.0. Keep this file current
when adding a dependency (`CONTRIBUTING.md`).

## Python dependencies (`requirements.txt`)

| Package | Licence | Use |
|---|---|---|
| `dilithium-py` | MIT | ML-DSA-44 (FIPS 204) pure-Python reference / fallback |
| `coloredlogs` | MIT | log formatting |
| `requests` | Apache-2.0 | HTTP client |
| `zstandard` (python-zstandard, bundles zstd) | BSD-3-Clause (zstd: BSD-3-Clause / GPL-2.0) | compression |
| `lmdb` (py-lmdb, bundles liblmdb) | OpenLDAP Public License 2.8 | chain index key-value store |
| `psutil` | BSD-3-Clause | process/system metrics |
| `aiohttp` | Apache-2.0 AND MIT | async HTTP server/client |
| `PySide6` (Qt for Python) | LGPL-3.0 / GPL-2.0 / GPL-3.0 (optional, desktop wallet only) | `pyside_wallet.py` GUI |
| `pyflakes` | MIT (dev/test only) | static check in `tests/` |

## Rust dependencies (`native/`, `wasm/`)

| Crate | Licence | Use |
|---|---|---|
| `ml-dsa` (RustCrypto) | Apache-2.0 OR MIT | native ML-DSA-44 backend |

The `wasm/blake2b` and `wasm/goldilocks` crates are first-party with no external crates.
Run `cargo license` in each crate directory to regenerate the transitive list before a
release.

## Vendored browser assets (`static/`)

| File | Upstream | Licence |
|---|---|---|
| `static/bootstrap.bundle.min.js` | Bootstrap v5.2.0-beta1, © 2011–2022 The Bootstrap Authors | MIT |
| `static/vendor/nado-crypto.js` | bundle of `@noble/hashes` 1.4.0 and `@noble/post-quantum` 0.2.0, © Paul Miller | MIT |
| `static/vendor/qrcode.js` | `qrcode-generator`, © Kazuhiko Arase | MIT |
| `static/vendor/bip39_wordlist.js` | BIP-39 English wordlist (bitcoin/bips) | BSD-2-Clause |
| `static/vendor/blake2b-wasm.js`, `goldilocks-wasm.js` | first-party (`wasm/`) | AGPL-3.0 |

Full licence texts for the MIT-licensed components:

```
Permission is hereby granted, free of charge, to any person obtaining a copy of this
software and associated documentation files (the "Software"), to deal in the Software
without restriction, including without limitation the rights to use, copy, modify, merge,
publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons
to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR
PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE
FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
```

## Specifications implemented

- FIPS 204 (ML-DSA), FIPS 203 (ML-KEM), FIPS 202 (SHA-3/SHAKE) — NIST, public domain.
- BIP-39 — bitcoin/bips, BSD-2-Clause.
- BLAKE2 — RFC 7693, CC0 / OpenSSL / Apache-2.0 (triple-licensed reference).

## Fonts and graphics

Logos and images under `graphics/` are © the NADO authors and are **not** covered by the
AGPL; see `doc/debrand.md` for the trademark/rebranding policy when forking.
