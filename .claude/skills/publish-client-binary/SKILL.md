---
name: publish-client-binary
description: Build and publish the TPM enrolment helper (apps/nado-tpm-attest) so users download it. Use for any change to that client - the order of the steps is the whole point.
---

# Publishing the enrolment helper

People download this and run it on a machine you cannot see. Every claim you make about it — which fix is
in it, which commit it is — is a claim they cannot check unless you make it checkable.

## The order is the point

**Commit → build → copy → verify.** Get it wrong and you ship a binary that is not what you say it is.
Both of these happened in one night:

- built, then committed: the build stamp named the *previous* commit
- built and committed, but never copied to `static/`: the served `.exe` was byte-identical to the old
  one, so "the fix is in this build" was false for the artefact anyone would actually download

```bash
cd /srv/nado-home/nado
git add apps/nado-tpm-attest/src/... && git commit && git push origin main    # FIRST

cd apps/nado-tpm-attest
export PATH=$PATH:/root/.cargo/bin
touch src/main.rs                                                # force the stamp to re-read HEAD
RUSTFLAGS="-C target-feature=+crt-static" cargo xwin build --release --target x86_64-pc-windows-msvc
cargo build --release --target x86_64-pc-windows-gnu             # fallback build
cargo build --release                                            # linux

cd /srv/nado-home/nado
cp apps/nado-tpm-attest/target/x86_64-pc-windows-msvc/release/nado-tpm-attest.exe static/nado-tpm-enrol.exe
cp apps/nado-tpm-attest/target/x86_64-pc-windows-gnu/release/nado-tpm-attest.exe static/nado-tpm-enrol-mingw.exe
cp apps/nado-tpm-attest/target/release/nado-tpm-attest            static/nado-tpm-enrol-linux
sha256sum static/nado-tpm-enrol.exe static/nado-tpm-enrol-mingw.exe static/nado-tpm-enrol-linux \
  > static/nado-tpm-enrol.sha256
```

## MSVC, not MinGW

Both are Rust — the triple selects the linker and C runtime, not the language. But Defender flagged the
MinGW build on a real user's machine as a trojan: almost nothing legitimate on Windows ships MinGW-linked
binaries while malware cross-compiled from Linux routinely does. MSVC + `crt-static` is 768 KB and 6
sections against 2 MB and 10, imports the normal Windows API sets, and needs no VC++ redistributable.

Keep the MinGW build published as a fallback. No Windows machine is available here to run either.

## Verify by downloading it back

Not the file on disk — the bytes the **public URL** serves, which is what the user gets:

```bash
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36"
curl -s -A "$UA" -o /tmp/dl.exe "https://get.nadochain.com/download_enrol?address=<addr>"
sha256sum /tmp/dl.exe static/nado-tpm-enrol.exe          # must match
strings /tmp/dl.exe | grep -oE "<commit8>" | head -1     # stamp must be HEAD
```

Cloudflare 403s a bare python UA; send a browser one. The filename carries the address
(`nado-tpm-enrol-<addr>.exe`) — the client parses it, so a renamed artefact silently enrols a throwaway
identity instead.

## Report the hash, always

State the sha256 of what you published. `static/nado-tpm-enrol.sha256` is served beside the download so
verification does not depend on a hash quoted in a chat.
