//! nado-tpm-attest — enrol this machine's TPM so it can vouch for a NADO identity.
//!
//! DOUBLE-CLICKING RUNS THE ENROLMENT. That is the whole point of the binary, so it must be what
//! happens when someone runs it the way people actually run an exe: no terminal, no arguments. An
//! earlier version defaulted to the old diagnostic, which meant the new binary printed the old
//! binary's output and looked, correctly, like the wrong file had been shipped.
//!
//!   (no arguments)                     enrol, asking for what it needs
//!   enrol --relay <host> --keys <file> enrol without prompts, for scripts and scheduled tasks
//!   diagnose                           the older Windows Hello device check (Windows only)
//!   selftest-tx                        encoding self-check, used by the test suite

#[cfg(windows)]
mod imp;

use nado_tpm_attest::{enrol, tx};

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("enrol") => enrol::run(&args[1..]),
        Some("diagnose") => {
            diagnose();
            Ok(())
        }
        Some("selftest-tx") => tx::selftest(),
        Some("check-creation") => nado_tpm_attest::chip::check_creation(),
        Some("check-cert") => match args.get(1) {
            Some(p) => nado_tpm_attest::chip::selftest_chain(p),
            None => Err("usage: nado-tpm-attest check-cert <certificate file>".into()),
        },
        Some("--help") | Some("-h") | Some("help") => {
            print_help();
            Ok(())
        }
        Some(other) => Err(format!("unknown command {other:?}. Run with --help.")),
        None => enrol::run_interactive(),
    };
    if let Err(e) = result {
        eprintln!("\n  FAILED: {e}\n");
        // A double-clicked window vanishes on exit and takes the error with it, which is exactly how
        // a first run reports nothing at all to the person who needed to read it.
        if args.is_empty() {
            enrol::pause();
        }
        std::process::exit(1);
    }
    if args.is_empty() {
        enrol::pause();
    }
}

fn print_help() {
    println!("nado-tpm-attest — enrol this machine's TPM");
    println!();
    println!("  (no arguments)                        enrol, asking for what it needs");
    println!("  enrol --relay <host[:port]> --keys <keys.dat>");
    println!("                                        enrol without prompts");
    println!("  diagnose                              the older Windows device check");
    println!("  check-cert <file>                     assemble a chain from a certificate, no TPM");
    println!("  check-creation                        probe: will this chip parent a key under its EK?");
    println!("  selftest-tx                           encoding self-check (tests)");
}

#[cfg(windows)]
fn diagnose() {
    imp::main();
}

#[cfg(not(windows))]
fn diagnose() {
    eprintln!("The device check is Windows-only; on Linux the enrolment talks to /dev/tpmrm0 directly.");
}
