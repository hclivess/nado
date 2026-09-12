//! Colour for the enrolment run.
//!
//! The diagnostic command had colour and the ENROLMENT did not, which is backwards: `diagnose` prints a
//! dozen lines and exits, while an enrolment is what someone watches for twenty minutes wondering whether
//! it is working. A wall of identical grey lines hides the one that matters — the count going up, the
//! step that failed, the address being vouched for.
//!
//! Every line stays readable with colour off: this only ever ADDS an escape sequence around text that
//! already said the same thing, so a pipe, a log file or a terminal that does not support it loses
//! nothing. Disabled automatically when stdout is not a terminal.

use std::sync::atomic::{AtomicBool, Ordering};

static ON: AtomicBool = AtomicBool::new(false);

/// Turn colour on if the terminal will render it. On Windows this also asks the console to interpret
/// escape sequences, which it does not do by default on older builds.
pub fn enable() {
    #[cfg(windows)]
    let supported = crate::win::enable_colour();
    #[cfg(not(windows))]
    let supported = unsafe { libc_isatty() };
    ON.store(supported && std::env::var_os("NO_COLOR").is_none(), Ordering::Relaxed);
}

#[cfg(not(windows))]
unsafe fn libc_isatty() -> bool {
    extern "C" {
        fn isatty(fd: i32) -> i32;
    }
    isatty(1) == 1
}

fn c(code: &str, s: &str) -> String {
    if ON.load(Ordering::Relaxed) {
        format!("\x1b[{code}m{s}\x1b[0m")
    } else {
        s.to_string()
    }
}

/// A step that succeeded, or a value that is good news.
pub fn ok(s: &str) -> String { c("1;32", s) }
/// A failure the user has to act on.
pub fn bad(s: &str) -> String { c("1;31", s) }
/// Something that is not wrong but is worth reading.
pub fn warn(s: &str) -> String { c("1;33", s) }
/// A heading or a milestone.
pub fn head(s: &str) -> String { c("1;36", s) }
/// An identifier — an address, a hash, an enrolment id.
pub fn id(s: &str) -> String { c("35", s) }
/// Detail that should not compete with the line it belongs to.
pub fn dim(s: &str) -> String { c("2", s) }

/// "2/3" — green once complete, yellow while it is still climbing, so progress is visible at a glance
/// rather than by reading two numbers on every poll.
pub fn progress(got: usize, want: usize) -> String {
    let t = format!("{got}/{want}");
    if got >= want && want > 0 { ok(&t) } else { warn(&t) }
}
