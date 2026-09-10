//! nado-tpm-attest — the client half of vendor-endorsed TPM attestation.
//!
//!   nado-tpm-attest enrol --relay <host[:port]> --keys <keys.dat>
//!       Enrol this machine's TPM and register the identity. Runs the four-message exchange of
//!       doc/tpm-attestation-without-a-ca.md against a relay, one step at a time, waiting for each
//!       message to land before sending the next — the ORDER is what makes the exchange a proof, so
//!       the client cannot hurry it.
//!
//!   nado-tpm-attest selftest-tx
//!       Read a transaction vector on stdin, print the txid and a signature. Exists so the Python
//!       node can check that this binary's encoding and signing agree with the chain's, which is the
//!       one thing that would otherwise fail silently and look like a network problem.
//!
//!   nado-tpm-attest            (Windows only)
//!       The original Windows Hello diagnostic.

// EVERYTHING SHARED LIVES IN THE LIB. When the binary re-declared `mod tpm` alongside the library's,
// the two copies of the `Tpm` trait were distinct types and a transport implementing one did not
// satisfy the other — a confusing error for a mistake that is purely structural.
#[cfg(windows)]
mod imp;

use nado_tpm_attest::{enrol, tx};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match args.first().map(String::as_str) {
        Some("enrol") => {
            if let Err(e) = enrol::run(&args[1..]) {
                eprintln!("\n  FAILED: {e}\n");
                std::process::exit(1);
            }
        }
        Some("selftest-tx") => {
            if let Err(e) = tx::selftest() {
                eprintln!("selftest-tx: {e}");
                std::process::exit(1);
            }
        }
        Some("--help") | Some("-h") | Some("help") => print_help(),
        _ => default_command(),
    }
}

fn print_help() {
    println!("nado-tpm-attest");
    println!();
    println!("  enrol --relay <host[:port]> --keys <path-to-keys.dat>");
    println!("        Enrol this machine's TPM and register the identity.");
    println!();
    println!("  selftest-tx");
    println!("        Read a transaction vector on stdin; print txid + signature (used by the tests).");
}

#[cfg(windows)]
fn default_command() {
    imp::main();
}

#[cfg(not(windows))]
fn default_command() {
    eprintln!("Nothing to do. Run `nado-tpm-attest enrol --relay <host> --keys <keys.dat>`,");
    eprintln!("or `nado-tpm-attest --help`.");
}
