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

/// Enrol with an identity this machine resolves for itself. No prompting and nothing pasted: the
/// enrolment proves a CHIP, not an owner, so it needs no secret from a person — and a program that
/// asks a user to paste a private key teaches a habit that is otherwise the definition of a scam.
pub fn run_auto(relay_arg: &str) -> Result<(), String> {
    let relay = Relay::parse(relay_arg)?;
    // The signing identity and the identity being VOUCHED FOR are different things, and separating
    // them is what removes every prompt. Enrolment messages are signed by a key this machine owns;
    // the chip's certify then names whichever address the wallet asked for.
    let (seed, own_address, path) = load_or_create_identity()?;
    let keys = crate::tx::Keys::from_seed_hex(&seed)?;
    let target = address_from_filename();
    let vouch_for = target.clone().unwrap_or_else(|| own_address.clone());
    if target.is_some() {
        println!("  vouching for {vouch_for}");
        println!("               (from this file's name — your wallet put it there)");
    } else {
        println!("  identity   {vouch_for}");
        println!("             key stored in {}", path.display());
    }
    println!("  relay      {}:{}", relay.host, relay.port);
    let out = enrol_with(&relay, &keys, &own_address, &vouch_for);
    if out.is_ok() && target.is_none() {
        println!("  Import {} into your wallet to use this identity.", path.display());
    }
    out
}

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
            "--auto" => {
                i += 1;
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    if keys_path.is_empty() {
        return run_auto(if relay_arg.is_empty() { DEFAULT_RELAY } else { &relay_arg });
    }
    if relay_arg.is_empty() {
        relay_arg = DEFAULT_RELAY.to_string();
    }
    let relay = Relay::parse(&relay_arg)?;
    let (seed, address) = read_keys(&keys_path)?;
    let keys = tx::Keys::from_seed_hex(&seed)?;
    println!("  identity   {address}");
    println!("  relay      {}:{}", relay.host, relay.port);
    enrol_with(&relay, &keys, &address, &address)
}

/// `signer` sends the enrolment messages; `vouch_for` is the identity the chip's certify names. They
/// are the same account when a node enrols itself, and different when a wallet user runs the helper.
fn enrol_with(relay: &Relay, keys: &tx::Keys, signer: &str, vouch_for: &str) -> Result<(), String> {
    let relay = relay;
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

    let id = enrol_id(relay, &chain, &aik_pub)?;
    println!("  enrolment  {id}");

    let started = Instant::now();
    loop {
        if started.elapsed() > GIVE_UP {
            return Err("gave up waiting: the drawn challengers did not answer in time. \
                        Re-run to start a fresh enrolment."
                .into());
        }
        let rec = fetch(relay, &id)?;
        match rec {
            None => {
                println!("  -> publishing this chip's endorsement chain");
                let data = json!({"ek": hexed(&chain), "pub": tx::hex(&aik_pub)});
                submit(relay, keys, signer, "tpm_enrol", data)?;
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
                            submit(relay, keys, signer, "tpm_commit",
                                   json!({"id": id, "commit": commit}))?;
                        }
                    }
                    "commit" => {
                        let n = rec.get("reveals").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
                        println!("  .. committed; {n} challenger(s) have revealed");
                    }
                    "proven" => {
                        println!("  -> proven. Registering with a fresh certify.");
                        register(relay, keys, signer, vouch_for, &id, &rec, &mut chip)?;
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

fn register(relay: &Relay, keys: &tx::Keys, signer: &str, vouch_for: &str, id: &str,
            rec: &Map<String, Value>, chip: &mut Chip) -> Result<(), String> {
    let ek = rec.get("ek").and_then(|x| x.as_str()).ok_or("record has no endorsement identity")?;
    let text = relay.get("/get_latest_block")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    let tip = v.get("block_number").and_then(|x| x.as_i64()).ok_or("relay gave no tip")?;
    let max_block = tip + 12;

    // The challenge is what makes this registration fresh rather than a replay: it binds this sender,
    // this anchor block and this landing height. The relay computes it so the client never has to
    // reproduce the chain's hash of them.
    let body = json!({"sender": vouch_for, "max_block": max_block}).to_string();
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
    // ONLY THE OWNER OF AN ADDRESS CAN REGISTER IT, and that is the correct limit rather than an
    // obstacle: a registration is signed by its sender, so naming someone else's address here produces
    // a transaction nobody can sign. When the helper is vouching for a wallet's address it therefore
    // hands the finished proof back for the wallet to submit, and only self-registers its own identity.
    if vouch_for != signer {
        return hand_back(relay, vouch_for, id, &device, max_block);
    }
    let mut t = Map::new();
    t.insert("sender".into(), json!(signer));
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

/// Leave the finished device proof where the wallet will find it. The wallet signs the registration,
/// because only it can — see the comment at the call site.
fn hand_back(relay: &Relay, address: &str, id: &str, device: &Value,
             max_block: i64) -> Result<(), String> {
    let body = json!({"address": address, "id": id, "device": device, "max_block": max_block})
        .to_string();
    relay.post_json("/tpm_proof_drop", &body)?;
    println!();
    println!("  This PC's chip has vouched for {address}.");
    println!("  Open your wallet and confirm the registration — it must sign that itself, because a");
    println!("  registration is signed by the identity it registers. The proof is waiting for it.");
    Ok(())
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

/// The address baked into this binary's own filename by /download_enrol.
///
/// A DOWNLOADED BINARY CANNOT BE TOLD ANYTHING AT LAUNCH — it has no arguments, because a person
/// double-clicks it — but it can read its own name, and a browser saves the name the server sent. So
/// the wallet, which already knows the address, hands it over through the one channel that survives
/// the round trip, and the user pastes nothing.
///
/// Renaming the file changes which identity this vouches for, which is fine: the address is not a
/// credential. Whoever owns it still has to sign the registration.
fn address_from_filename() -> Option<String> {
    let exe = std::env::current_exe().ok()?;
    let stem = exe.file_stem()?.to_str()?;
    let rest = stem.strip_prefix("nado-tpm-enrol-")?;
    let addr = rest.trim_end_matches("-linux");
    let ok = (12..=64).contains(&addr.len()) && addr.chars().all(|c| c.is_ascii_hexdigit());
    if ok { Some(addr.to_ascii_lowercase()) } else { None }
}

/// Where an identity file lives, in the order worth trying.
///
/// NEXT TO THE EXE FIRST. Someone who downloads this and runs it has no NADO directory and no reason
/// to make one; the identity belongs with the thing that created it. A node's own keyfile is checked
/// second so that running this on a machine that already has an identity enrols THAT one rather than
/// silently minting a second.
fn identity_paths() -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            out.push(dir.join("nado-identity.json"));
        }
    }
    if let Some(home) = home_dir() {
        out.push(home.join("nado").join("private").join("keys.dat"));
    }
    out
}

fn home_dir() -> Option<std::path::PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("USERPROFILE").map(std::path::PathBuf::from)
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("HOME").map(std::path::PathBuf::from)
    }
}

/// Find an identity, or make one. NO PROMPTING, EVER: this asks a person for nothing, least of all a
/// private key — a program that asks a user to paste their key teaches a habit that is otherwise the
/// definition of a scam, and there is no reason to, because the key never needs to leave this machine
/// and this machine can make its own.
fn load_or_create_identity() -> Result<(String, String, std::path::PathBuf), String> {
    for path in identity_paths() {
        if !path.exists() {
            continue;
        }
        let text = match std::fs::read_to_string(&path) {
            Ok(t) => t,
            Err(_) => continue,
        };
        let v: Value = match serde_json::from_str(&text) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if let Some(seed) = v.get("private_key").and_then(|x| x.as_str()) {
            let keys = crate::tx::Keys::from_seed_hex(seed)?;
            return Ok((seed.to_string(), keys.address, path));
        }
    }
    // Nothing found: mint one. An attested identity starts from zero by design — the open lane exists
    // so that a participant with no capital can produce blocks from ordinary hardware.
    let mut seed = [0u8; 32];
    crate::rand_bytes(&mut seed);
    let seed_hex = crate::tx::hex(&seed);
    let keys = crate::tx::Keys::from_seed_hex(&seed_hex)?;
    let path = identity_paths()
        .into_iter()
        .next()
        .ok_or("cannot determine where to store the identity")?;
    let doc = json!({
        "private_key": seed_hex,
        "public_key": keys.public_key,
        "address": keys.address,
    });
    write_private(&path, &serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())?)?;
    println!("  identity   created {}", path.display());
    Ok((seed_hex, keys.address, path))
}

/// Write a file only the owner can read. THE FILE IS THE IDENTITY — the 32-byte seed alone can spend
/// and can sign as this machine — so a default-permissions write on a shared box hands it away.
fn write_private(path: &std::path::Path, contents: &str) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;
        let mut f = std::fs::OpenOptions::new()
            .write(true).create_new(true).mode(0o600)
            .open(path)
            .map_err(|e| format!("cannot create {}: {e}", path.display()))?;
        f.write_all(contents.as_bytes()).map_err(|e| e.to_string())?;
    }
    #[cfg(not(unix))]
    {
        // Windows inherits the parent directory's ACL; a per-user folder is already owner-only, and
        // this deliberately refuses to overwrite an existing identity.
        std::fs::OpenOptions::new()
            .write(true).create_new(true)
            .open(path)
            .map_err(|e| format!("cannot create {}: {e}", path.display()))
            .and_then(|mut f| {
                use std::io::Write;
                f.write_all(contents.as_bytes()).map_err(|e| e.to_string())
            })?;
    }
    Ok(())
}

/// What happens when someone double-clicks the exe: everything, with no questions.
pub fn run_interactive() -> Result<(), String> {
    println!();
    println!("  NADO — enrolling this PC's security chip");
    println!();
    println!("  Your PC has a TPM whose maker (AMD, Intel, Infineon, Nuvoton) signed a certificate");
    println!("  saying it is genuine. This proves a key lives inside that chip, so an identity is");
    println!("  anchored to real hardware. It does not ask Microsoft anything — that service is the");
    println!("  part that fails on a quarter of otherwise healthy machines.");
    println!();
    println!("  Nothing is asked of you and nothing leaves this PC except the proof itself.");
    println!("  It takes a few minutes: the chain carries four messages, each in a later block than");
    println!("  the one before it, and that ordering is what makes the proof a proof.");
    println!();
    run_auto(DEFAULT_RELAY)
}
