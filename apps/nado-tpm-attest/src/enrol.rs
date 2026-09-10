//! The four-message enrolment, from the machine that owns the chip.
//!
//! WHAT THIS DOES THAT A BROWSER CANNOT. A WebAuthn ceremony asks the platform for an attestation and
//! the platform decides. For a large share of machines it decides "no" — the vendor's attestation
//! service has no authority registered for the chip — and there is no client-side appeal. This talks
//! to the TPM directly, so the platform is not in the loop at all.
//!
//! THE CLIENT CANNOT HURRY THE EXCHANGE, and that is the whole design rather than a limitation. Each
//! message must be published strictly later than the one it answers, so the client sends one, waits
//! for it to land, waits for the drawn challengers to answer, and only then continues. A client that
//! sent everything at once would be describing a proof rather than producing one.

use crate::http::Relay;
use crate::chip::{self, Chip};
use crate::tx;
use serde_json::{json, Map, Value};
use std::thread::sleep;
use std::time::{Duration, Instant};

pub const DEFAULT_RELAY: &str = "38.242.201.206:9173";

const POLL: Duration = Duration::from_secs(10);
const GIVE_UP: Duration = Duration::from_secs(60 * 90);

pub fn run(args: &[String]) -> Result<(), String> {
    let mut relay_arg = String::new();
    let mut keys_path = String::new();
    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--relay" => {
                relay_arg = args.get(i + 1).cloned().unwrap_or_default();
                i += 2;
            }
            "--keys" => {
                keys_path = args.get(i + 1).cloned().unwrap_or_default();
                i += 2;
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    if relay_arg.is_empty() || keys_path.is_empty() {
        return Err("usage: nado-tpm-attest enrol --relay <host[:port]> --keys <keys.dat>".into());
    }
    let relay = Relay::parse(&relay_arg)?;
    let (seed, address) = read_keys(&keys_path)?;
    let keys = tx::Keys::from_seed_hex(&seed)?;

    println!("  identity   {address}");
    println!("  relay      {}:{}", relay.host, relay.port);

    let mut chip = chip::open()?;
    let chain = chip.ek_chain()?;
    if chain.is_empty() {
        return Err("this TPM holds no endorsement certificate, so no silicon vendor vouches for it. \
                    Without that signature the proof would only say \"some TPM somewhere\", which a \
                    software TPM says just as convincingly."
            .into());
    }
    // The endorsement PUBLIC key is not sent: it is inside the certificate, and the node lifts it from
    // there with the lenient parser it has to use for that certificate anyway. Deriving it here would
    // cost an RSA primary — seconds on a real firmware TPM — to produce a value nobody reads.
    let aik_pub = chip.aik_public()?;
    println!("  chip       endorsement chain: {} certificate(s), {} bytes; attestation key ready",
             chain.len(), chain.iter().map(|c| c.len()).sum::<usize>());

    let id = enrol_id(&relay, &chain, &aik_pub)?;
    println!("  enrolment  {id}");

    let started = Instant::now();
    loop {
        if started.elapsed() > GIVE_UP {
            return Err("gave up waiting: the drawn challengers did not answer in time. \
                        Re-run to start a fresh enrolment."
                .into());
        }
        let rec = fetch(&relay, &id)?;
        match rec {
            None => {
                println!("  -> publishing this chip's endorsement chain");
                let data = json!({"ek": hexed(&chain), "pub": tx::hex(&aik_pub)});
                submit(&relay, &keys, &address, "tpm_enrol", data)?;
            }
            Some(rec) => {
                let state = rec.get("state").and_then(|v| v.as_str()).unwrap_or("");
                match state {
                    "open" => {
                        let blobs = rec.get("blobs").and_then(|v| v.as_array()).cloned().unwrap_or_default();
                        let drawn = rec
                            .get("challengers")
                            .and_then(|v| v.as_array())
                            .map(|a| a.len())
                            .unwrap_or(0);
                        if blobs.len() < drawn {
                            println!("  .. {}/{} challengers have answered", blobs.len(), drawn);
                        } else {
                            println!("  -> opening every challenge inside the chip");
                            let secret = activate_all(&mut chip, &blobs)?;
                            let commit = crate::sha::sha256_hex(&secret);
                            submit(&relay, &keys, &address, "tpm_commit",
                                   json!({"id": id, "commit": commit}))?;
                        }
                    }
                    "commit" => {
                        let n = rec.get("reveals").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
                        println!("  .. committed; {n} challenger(s) have revealed");
                    }
                    "proven" => {
                        println!("  -> proven. Registering with a fresh certify.");
                        register(&relay, &keys, &address, &id, &rec, &mut chip)?;
                        println!("\n  DONE: this machine's TPM is enrolled and the identity is registered.\n");
                        return Ok(());
                    }
                    other => return Err(format!("unexpected enrolment state {other:?}")),
                }
            }
        }
        sleep(POLL);
    }
}

/// Accept EITHER a keyfile path or a bare private key. A wallet user has a private key; they do not
/// necessarily have a file, and telling them to construct one is a step where this stops being usable.
fn read_keys(arg: &str) -> Result<(String, String), String> {
    let bare = arg.trim();
    if bare.len() == 64 && bare.chars().all(|c| c.is_ascii_hexdigit()) {
        let keys = crate::tx::Keys::from_seed_hex(&bare.to_ascii_lowercase())?;
        return Ok((bare.to_ascii_lowercase(), keys.address));
    }
    let path = bare.trim_matches('"');
    let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read {path}: {e}"))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("{path} is not JSON: {e}"))?;
    let seed = v.get("private_key").and_then(|x| x.as_str())
        .ok_or("keyfile has no private_key")?.to_string();
    // The address is DERIVED, so a keyfile that lacks it (or carries a stale one from an address
    // format change) still works rather than failing with a confusing mismatch later.
    let address = v.get("address").and_then(|x| x.as_str()).map(String::from)
        .unwrap_or_else(|| crate::tx::make_address(""));
    let derived = crate::tx::Keys::from_seed_hex(&seed)?.address;
    if address != derived {
        return Ok((seed, derived));
    }
    Ok((seed, address))
}

/// The enrolment id is DERIVED from public content, so the relay computes it the same way we do. We
/// ask it rather than reimplementing the chain's hash here: one fewer encoding to keep in step.
fn hexed(chain: &[Vec<u8>]) -> Vec<String> {
    chain.iter().map(|c| tx::hex(c)).collect()
}

fn enrol_id(relay: &Relay, chain: &[Vec<u8>], aik_pub: &[u8]) -> Result<String, String> {
    let body = json!({"ek": hexed(chain), "pub": tx::hex(aik_pub)}).to_string();
    let text = relay.post_json("/tpm_enrol_id", &body)?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    v.get("id").and_then(|x| x.as_str()).map(String::from)
        .ok_or_else(|| format!("relay could not derive the enrolment id: {text}"))
}

fn fetch(relay: &Relay, id: &str) -> Result<Option<Map<String, Value>>, String> {
    let text = relay.get(&format!("/tpm_enrolment?id={id}"))?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    if v.get("found").and_then(|x| x.as_bool()) != Some(true) {
        return Ok(None);
    }
    Ok(v.as_object().cloned())
}

fn activate_all(chip: &mut Chip, blobs: &[Value]) -> Result<Vec<u8>, String> {
    // THE CONCATENATION ORDER IS CONSENSUS, not a local choice: the commitment is checked against the
    // secrets sorted by challenger, so any other order fails at the very last reveal — after every
    // other check has passed, which is the most confusing possible place to fail.
    let mut rows: Vec<(String, Vec<u8>, Vec<u8>)> = Vec::new();
    for b in blobs {
        let a = b.as_array().ok_or("malformed blob row")?;
        let who = a.first().and_then(|x| x.as_str()).ok_or("blob row has no challenger")?;
        let blob = tx::unhex(a.get(1).and_then(|x| x.as_str()).ok_or("blob row has no blob")?)?;
        let enc = tx::unhex(a.get(2).and_then(|x| x.as_str()).ok_or("blob row has no seed")?)?;
        rows.push((who.to_string(), blob, enc));
    }
    rows.sort_by(|x, y| x.0.cmp(&y.0));
    let mut out = Vec::new();
    for (_who, blob, enc) in rows {
        out.extend_from_slice(&chip.activate_credential(&blob, &enc)?);
    }
    Ok(out)
}

fn register(relay: &Relay, keys: &tx::Keys, address: &str, id: &str,
            rec: &Map<String, Value>, chip: &mut Chip) -> Result<(), String> {
    let ek = rec.get("ek").and_then(|x| x.as_str()).ok_or("record has no endorsement identity")?;
    let text = relay.get("/get_latest_block")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    let tip = v.get("block_number").and_then(|x| x.as_i64()).ok_or("relay gave no tip")?;
    let max_block = tip + 12;

    // The challenge is what makes this registration fresh rather than a replay: it binds this sender,
    // this anchor block and this landing height. The relay computes it so the client never has to
    // reproduce the chain's hash of them.
    let body = json!({"sender": address, "max_block": max_block}).to_string();
    let ch_text = relay.post_json("/register_challenge", &body)?;
    let ch: Value = serde_json::from_str(&ch_text).map_err(|e| format!("bad relay reply: {e}"))?;
    let challenge = tx::unhex(ch.get("challenge").and_then(|x| x.as_str())
        .ok_or_else(|| format!("relay gave no challenge: {ch_text}"))?)?;

    let (cert_info, sig) = chip.certify(&challenge)?;
    let device = json!({
        "ek": ek, "id": id,
        "certinfo": tx::hex(&cert_info),
        "sig": tx::hex(&sig),
    });
    let mut t = Map::new();
    t.insert("sender".into(), json!(address));
    t.insert("recipient".into(), json!("register"));
    t.insert("amount".into(), json!(0));
    t.insert("data".into(), json!(""));
    t.insert("device".into(), device);
    submit_built(relay, keys, t, max_block)
}

fn submit(relay: &Relay, keys: &tx::Keys, address: &str, recipient: &str,
          data: Value) -> Result<(), String> {
    let text = relay.get("/get_latest_block")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    let tip = v.get("block_number").and_then(|x| x.as_i64()).ok_or("relay gave no tip")?;
    let mut t = Map::new();
    t.insert("sender".into(), json!(address));
    t.insert("recipient".into(), json!(recipient));
    t.insert("amount".into(), json!(0));
    t.insert("data".into(), data);
    t.insert("min_block".into(), json!(tip + 8));
    submit_built(relay, keys, t, tip + 60)
}

fn submit_built(relay: &Relay, keys: &tx::Keys, mut t: Map<String, Value>,
                max_block: i64) -> Result<(), String> {
    let mut nonce = [0u8; 16];
    crate::rand_bytes(&mut nonce);
    t.insert("timestamp".into(), json!(now_secs()));
    t.insert("nonce".into(), json!(u128::from_be_bytes(nonce) % 1_000_000_000));
    t.insert("max_block".into(), json!(max_block));
    t.insert("fee".into(), json!(0));
    t.insert("chain_id".into(), json!(chain_id(relay)?));
    t.insert("public_key".into(), json!(keys.public_key));
    let txid = tx::create_txid(&t);
    let signature = keys.sign_txid(&txid)?;
    t.insert("txid".into(), json!(txid));
    t.insert("signature".into(), json!(signature));

    let body = serde_json::to_string(&Value::Object(t)).map_err(|e| e.to_string())?;
    let reply = relay.post_json("/submit_transaction", &body)?;
    if reply.contains("\"result\": true") || reply.contains("\"result\":true") {
        Ok(())
    } else {
        Err(format!("the relay refused the transaction: {}", reply.trim()))
    }
}

fn chain_id(relay: &Relay) -> Result<String, String> {
    let text = relay.get("/status")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    v.get("chain_id").and_then(|x| x.as_str()).map(String::from)
        .ok_or_else(|| "relay did not report a chain id".into())
}

fn now_secs() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Keep a double-clicked window open long enough to be read. Without this the process exits, the
/// console host closes, and whatever it printed — including the reason it failed — is gone.
pub fn pause() {
    use std::io::{BufRead, Write};
    print!("\n  Press Enter to close this window.");
    std::io::stdout().flush().ok();
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line).ok();
}

fn ask(prompt: &str, default: &str) -> String {
    use std::io::{BufRead, Write};
    if default.is_empty() {
        print!("  {prompt}: ");
    } else {
        print!("  {prompt} [{default}]: ");
    }
    std::io::stdout().flush().ok();
    let mut line = String::new();
    std::io::stdin().lock().read_line(&mut line).ok();
    let line = line.trim().to_string();
    if line.is_empty() { default.to_string() } else { line }
}

/// What happens when someone double-clicks the exe, which is how this is actually run.
pub fn run_interactive() -> Result<(), String> {
    println!();
    println!("  NADO — enrol this PC's security chip");
    println!();
    println!("  Your PC has a TPM whose maker (AMD, Intel, Infineon, Nuvoton) signed a certificate");
    println!("  saying it is genuine. This proves to the chain that a key lives inside that chip, so");
    println!("  your identity is anchored to real hardware instead of to a password.");
    println!();
    println!("  It does NOT use Microsoft's attestation service, which is the part that fails on a");
    println!("  quarter of otherwise healthy machines. Nothing here asks Microsoft anything.");
    println!();
    println!("  This takes a few minutes: the chain has to carry four messages, each one in a later");
    println!("  block than the one before it. That ordering is what makes the proof a proof.");
    println!();

    let relay = ask("Relay", DEFAULT_RELAY);
    println!();
    println!("  Now your identity. Either the path to a keys.dat file, or paste the private key");
    println!("  itself (64 hex characters) — the address is derived from it, nothing is uploaded.");
    let ident = ask("Keyfile or private key", "");
    if ident.is_empty() {
        return Err("no identity given".into());
    }
    println!();
    run(&[
        "--relay".to_string(), relay,
        "--keys".to_string(), ident,
    ])
}
