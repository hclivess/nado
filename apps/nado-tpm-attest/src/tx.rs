//! Building and signing NADO transactions, from the client side.
//!
//! THIS FILE MUST AGREE WITH THE CHAIN BYTE FOR BYTE OR NOTHING IT PRODUCES IS ACCEPTED. Two encodings
//! carry that weight and both are pinned by tests/txvectors.rs against vectors the Python node itself
//! generated:
//!
//!   canonical_bytes  `json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
//!                    — sorted keys, no whitespace, ASCII-escaped.
//!   txid             blake2b-256, hex, over the canonical encoding of the body with `public_key`
//!                    REMOVED. The key is a recoverable authentication witness, not identity, so a
//!                    later transaction may omit it and hash the same.
//!
//! The signature is ML-DSA-44 in FIPS 204 *internal* mode (no context string), over the 32 RAW bytes
//! of the txid — not over its hex. It is hedged, so it is deliberately not byte-reproducible; the
//! chain checks `verify() == true`, never signature equality, which is why using the same `ml-dsa`
//! crate as the node's own backend is what matters rather than matching bytes.

use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;
use ml_dsa::{B32, Keypair, MlDsa44, SigningKey};
use serde_json::{Map, Value};

/// The chain's canonical encoding. serde_json emits compact separators already; the sorting is ours,
/// and it has to be recursive because a transaction's `data` is itself an object.
pub fn canonical_bytes(v: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    write_canonical(v, &mut out);
    out
}

fn write_canonical(v: &Value, out: &mut Vec<u8>) {
    match v {
        Value::Object(map) => {
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push(b'{');
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_string(k, out);
                out.push(b':');
                write_canonical(&map[*k], out);
            }
            out.push(b'}');
        }
        Value::Array(items) => {
            out.push(b'[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push(b',');
                }
                write_canonical(item, out);
            }
            out.push(b']');
        }
        Value::String(s) => write_string(s, out),
        Value::Null => out.extend_from_slice(b"null"),
        Value::Bool(b) => out.extend_from_slice(if *b { b"true" } else { b"false" }),
        Value::Number(n) => out.extend_from_slice(n.to_string().as_bytes()),
    }
}

/// Python's `json.dumps(..., ensure_ascii=True)` escaping. Everything this client sends is hex, an
/// address, or a small integer, so the non-ASCII path is never exercised in practice — it is written
/// out anyway because "never exercised in practice" is how encodings diverge silently.
fn write_string(s: &str, out: &mut Vec<u8>) {
    out.push(b'"');
    for c in s.chars() {
        match c {
            '"' => out.extend_from_slice(b"\\\""),
            '\\' => out.extend_from_slice(b"\\\\"),
            '\n' => out.extend_from_slice(b"\\n"),
            '\r' => out.extend_from_slice(b"\\r"),
            '\t' => out.extend_from_slice(b"\\t"),
            c if (c as u32) < 0x20 => {
                out.extend_from_slice(format!("\\u{:04x}", c as u32).as_bytes())
            }
            c if (c as u32) < 0x7f => out.push(c as u8),
            c => {
                // ensure_ascii escapes astral characters as a surrogate pair, exactly like Python.
                let cp = c as u32;
                if cp > 0xFFFF {
                    let v = cp - 0x10000;
                    out.extend_from_slice(
                        format!("\\u{:04x}\\u{:04x}", 0xD800 + (v >> 10), 0xDC00 + (v & 0x3FF))
                            .as_bytes(),
                    );
                } else {
                    out.extend_from_slice(format!("\\u{:04x}", cp).as_bytes());
                }
            }
        }
    }
    out.push(b'"');
}

pub fn blake2b_hex(data: &[u8], size: usize) -> String {
    let mut h = Blake2bVar::new(size).expect("blake2b size");
    h.update(data);
    let mut buf = vec![0u8; size];
    h.finalize_variable(&mut buf).expect("blake2b finalize");
    hex(&buf)
}

pub fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{:02x}", b)).collect()
}

pub fn unhex(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd-length hex".into());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

/// The transaction identity: blake2b-256 over the canonical body with `public_key` excluded.
pub fn create_txid(tx: &Map<String, Value>) -> String {
    let mut body = tx.clone();
    body.remove("public_key");
    blake2b_hex(&canonical_bytes(&Value::Object(body)), 32)
}

/// ADDRESS_PREFIX + the first ADDRESS_BODY hex chars of the public key + a 4-hex checksum.
///
/// THE CHECKSUM IS BLAKE2B WITH AN OUTPUT LENGTH OF 2 BYTES — not the first two bytes of a 32-byte
/// digest. blake2b keys its output length into the IV, so those are different values, and slicing a
/// long hash yields a checksum that rejects every valid address. And the input is the CANONICAL
/// encoding of the body string, quotes included, because that is what the node hashes.
pub fn make_address(public_key: &str) -> String {
    let body: String = public_key.chars().take(42).collect();
    let checksum = blake2b_hex(&canonical_bytes(&Value::String(body.clone())), 2);
    format!("{body}{checksum}")
}

pub struct Keys {
    pub seed: [u8; 32],
    pub address: String,
    pub public_key: String,
}

impl Keys {
    /// The 32-byte seed alone IS the identity: the node stores nothing else and re-derives the
    /// keypair on every use, so a client that holds the seed can sign exactly what the owner can.
    pub fn from_seed_hex(seed_hex: &str) -> Result<Self, String> {
        let seed = unhex(seed_hex)?;
        if seed.len() != 32 {
            return Err(format!("ML-DSA seed must be exactly 32 bytes, got {}", seed.len()));
        }
        let mut s = [0u8; 32];
        s.copy_from_slice(&seed);
        let b = B32::try_from(&s[..]).map_err(|_| "seed")?;
        let sk = SigningKey::<MlDsa44>::from_seed(&b);
        let public_key = hex(sk.verifying_key().encode().as_slice());
        Ok(Keys { seed: s, address: make_address(&public_key), public_key })
    }

    /// Sign the RAW txid bytes, FIPS 204 internal mode, hedged. Not byte-reproducible by design.
    pub fn sign_txid(&self, txid: &str) -> Result<String, String> {
        let msg = unhex(txid)?;
        let b = B32::try_from(&self.seed[..]).map_err(|_| "seed")?;
        let sk = SigningKey::<MlDsa44>::from_seed(&b);
        let mut rnd = [0u8; 32];
        crate::rand_bytes(&mut rnd);
        let r = B32::try_from(&rnd[..]).map_err(|_| "rnd")?;
        // sign_internal takes message PARTS that get concatenated; one part == the whole message,
        // matching the node's own backend and dilithium-py's single-message _sign_internal.
        // sign_internal lives on the EXPANDED key, which is the same path the node's own backend
        // takes (native/mldsa44) — deliberately, so the client and the verifier are one implementation.
        #[allow(deprecated)]
        let esk = sk.expanded_key();
        let sig = esk.sign_internal(&[&msg], &r);
        Ok(hex(sig.encode().as_slice()))
    }
}


/// Read a transaction vector on stdin, print the txid and a signature over it.
///
/// THE POINT OF THIS COMMAND is that the chain, not this crate, gets to say whether the encoding is
/// right. tests/test_tpm_client_tx.py generates a transaction with the node's own code, runs it
/// through here, and asserts that the txid matches and that the node's verify() accepts the
/// signature. An encoding divergence would otherwise surface as transactions the relay silently
/// rejects, which looks like a network fault.
pub fn selftest() -> Result<(), String> {
    use std::io::Read;
    let mut input = String::new();
    std::io::stdin().read_to_string(&mut input).map_err(|e| e.to_string())?;
    let v: Value = serde_json::from_str(&input).map_err(|e| format!("stdin is not JSON: {e}"))?;
    let obj = v.as_object().ok_or("vector must be an object")?;
    let seed = obj.get("seed").and_then(|x| x.as_str()).ok_or("vector needs `seed`")?;
    let tx = obj.get("tx").and_then(|x| x.as_object()).ok_or("vector needs `tx`")?;

    let keys = Keys::from_seed_hex(seed)?;
    let txid = create_txid(tx);
    let sig = keys.sign_txid(&txid)?;
    let canonical = {
        let mut body = tx.clone();
        body.remove("public_key");
        String::from_utf8_lossy(&canonical_bytes(&Value::Object(body))).into_owned()
    };
    let out = serde_json::json!({
        "txid": txid,
        "public_key": keys.public_key,
        "address": keys.address,
        "signature": sig,
        "canonical": canonical,
    });
    println!("{}", out);
    Ok(())
}
