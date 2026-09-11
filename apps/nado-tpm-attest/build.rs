//! Stamp a build identifier into the binary so its output says which build produced it.
//!
//! Three builds of this program were in circulation on a single test machine at once, and a pasted
//! transcript could not be attributed to any of them. A short content hash costs nothing and makes
//! every report self-identifying.
use std::process::Command;

fn main() {
    let git = Command::new("git")
        .args(["rev-parse", "--short=8", "HEAD"])
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| String::from_utf8_lossy(&o.stdout).trim().to_string())
        .unwrap_or_else(|| "unknown".into());
    println!("cargo:rustc-env=NADO_BUILD={git}");
    println!("cargo:rerun-if-changed=src");
}
