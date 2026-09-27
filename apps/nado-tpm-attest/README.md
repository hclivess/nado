
## Building the Windows binary

```bash
cargo install cargo-xwin --locked
rustup target add x86_64-pc-windows-msvc
RUSTFLAGS="-C target-feature=+crt-static" cargo xwin build --release --target x86_64-pc-windows-msvc
```

**The Windows binary is built ONLY with the MSVC target above** (static CRT, no runtime to install). No other Windows
target is installed on the build host, built, or published — the operator removed it (2026-09-27).

**Authenticode signing is the only thing that reliably clears SmartScreen.** Publish `nado-tpm-enrol.sha256` beside the binary either way, so anyone can verify what
they downloaded without trusting a hash quoted in a chat.
