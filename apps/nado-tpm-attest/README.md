
## Building the Windows binary

```bash
cargo install cargo-xwin --locked
rustup target add x86_64-pc-windows-msvc
RUSTFLAGS="-C target-feature=+crt-static" cargo xwin build --release --target x86_64-pc-windows-msvc
```

**Build with the MSVC target, not `x86_64-pc-windows-gnu`.** Both produce the same Rust program — the
triple selects the linker and C runtime, not the language — but the MinGW-linked binary was flagged by
Windows Defender on a real user's machine and the MSVC one looks like ordinary Windows software:

| | MinGW | MSVC + static CRT |
|---|---|---|
| size | 2,032,025 | 768,512 |
| PE sections | 10 | 6 |
| CRT imports | MinGW's own | none — statically linked |

Almost nothing legitimate on Windows ships MinGW-linked binaries; malware cross-compiled from Linux
routinely does. Combined with what this program legitimately needs to do — talk to the TPM, read the
registry, fetch certificates over HTTP — an unsigned MinGW binary lands squarely in a heuristic cluster.
`+crt-static` additionally removes the VC++ redistributable dependency, so the download runs on a clean
machine.

This is mitigation, not a cure: **Authenticode signing is the only thing that reliably clears
SmartScreen.** Publish `nado-tpm-enrol.sha256` beside the binary either way, so anyone can verify what
they downloaded without trusting a hash quoted in a chat.
