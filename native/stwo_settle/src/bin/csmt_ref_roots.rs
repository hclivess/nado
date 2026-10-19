//! Reads lines `key_hex vh_hex sib1_hex,sib2_hex,...` (32-byte hex each, siblings root first, possibly empty) and prints
//! the root csmt_ref::root_from_path implies, one hex line per input — for the Python cross-check.
use std::io::{self, BufRead, Write};

use nado_stwo_settle::csmt_ref::{bytes, root_from_path, words};

fn h32(s: &str) -> [u8; 32] {
    let v: Vec<u8> = (0..32).map(|i| u8::from_str_radix(&s[2 * i..2 * i + 2], 16).unwrap()).collect();
    v.try_into().unwrap()
}

fn main() {
    let out = io::stdout();
    let mut out = out.lock();
    for line in io::stdin().lock().lines() {
        let line = line.unwrap();
        let p: Vec<&str> = line.split(' ').collect();
        let sibs: Vec<[u32; 8]> =
            if p.len() > 2 && !p[2].is_empty() { p[2].split(',').map(|s| words(&h32(s))).collect() } else { vec![] };
        let r = root_from_path(&words(&h32(p[0])), &words(&h32(p[1])), &sibs);
        writeln!(out, "{}", bytes(&r).iter().map(|b| format!("{b:02x}")).collect::<String>()).unwrap();
    }
}
