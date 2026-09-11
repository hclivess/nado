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

/// Identifies the binary in its own output — see run_interactive.
pub const BUILD: &str = env!("NADO_BUILD");

pub const DEFAULT_RELAY: &str = "38.242.201.206:9173";

const POLL: Duration = Duration::from_secs(10);

/// How long to wait for a submitted message to be included before sending another.
///
/// A MESSAGE TAKES BLOCKS TO LAND, AND THE CLIENT MUST NOT KEEP SENDING WHILE IT WAITS. Publishing on
/// every poll produced a pool full of duplicates twice: once when the transaction could never be
/// included at all, and again when it could — each duplicate of an enrolment supersedes the last and
/// re-draws its challengers, so a client racing itself would reset the very set it is waiting on. The
/// chain refuses the duplicates, but only after they have cost a round trip each.
const AWAIT_INCLUSION: Duration = Duration::from_secs(90);

/// HOW OFTEN TO SAY SOMETHING WHILE WAITING ON A DRAW. There is deliberately no "give up and rotate the
/// attestation key" path any more; see the waiting branch below for why rotating cannot work.
const REPORT_EVERY: u32 = 18;
const GIVE_UP: Duration = Duration::from_secs(60 * 90);

/// Enrol with an identity this machine resolves for itself. No prompting and nothing pasted: the
/// enrolment proves a CHIP, not an owner, so it needs no secret from a person — and a program that
/// asks a user to paste a private key teaches a habit that is otherwise the definition of a scam.
pub fn run_auto(relay_arg: &str, vouch_override: Option<String>) -> Result<(), String> {
    let relay = Relay::parse(relay_arg)?;
    // The signing identity and the identity being VOUCHED FOR are different things, and separating
    // them is what removes every prompt. Enrolment messages are signed by a key this machine owns;
    // the chip's certify then names whichever address the wallet asked for.
    let (seed, own_address, path) = load_or_create_identity()?;
    let keys = crate::tx::Keys::from_seed_hex(&seed)?;
    // SAY WHOSE IDENTITY THIS BINDS, ALWAYS, INCLUDING THE FALLBACK. An earlier build printed this
    // line only when an address had been found, so when a rename dropped the address out of the
    // filename the program said nothing at all and proceeded to enrol its own throwaway identity.
    // Silence read as "fine". The whole value of an enrolment is WHICH identity gains the weight, so
    // the fallback is the case that most needs announcing, not the one to stay quiet about.
    let (vouch_for, source) = match (vouch_override, address_from_filename()) {
        (Some(a), _) => (a, "from --vouch on the command line"),
        (None, Some(a)) => (a, "from this file's name — your wallet put it there"),
        (None, None) => (own_address.clone(), "NO ADDRESS GIVEN — this enrols the throwaway identity \
                                               beside this program, which has no stake and no weight. \
                                               Download the file from your wallet, or pass --vouch."),
    };
    let target = if vouch_for == own_address { None } else { Some(vouch_for.clone()) };
    let _ = &path;
    println!("  vouching for {vouch_for}");
    println!("               ({source})");
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
    let mut vouch_arg = String::new();
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
            // AN EXPLICIT ADDRESS TO VOUCH FOR. The filename is the channel a double-clicked download
            // uses, but it is fragile in exactly one way that bit us: rename the artifact and the
            // address silently disappears. Anyone invoking this by hand gets a flag that cannot be
            // lost by a rename.
            "--vouch" => {
                vouch_arg = args.get(i + 1).cloned().unwrap_or_default();
                i += 2;
            }
            "--auto" => {
                i += 1;
            }
            other => return Err(format!("unknown argument {other}")),
        }
    }
    if keys_path.is_empty() {
        return run_auto(if relay_arg.is_empty() { DEFAULT_RELAY } else { &relay_arg },
                        if vouch_arg.is_empty() { None } else { Some(vouch_arg) });
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
    println!("  chip       endorsement chain: {} certificate(s), {} bytes",
             chain.len(), chain.iter().map(|c| c.len()).sum::<usize>());

    // ONE ATTESTATION KEY PER CHIP, FIXED FOR THE LIFE OF THE PROCESS. The attempt number still selects
    // the key (and so the enrolment id, and so the draw), but it never advances: the chain bounds a chip
    // to one open enrolment, so deriving a second key while a record is live produces an enrolment the
    // relay must refuse — HTTP 403, "this chip already has an enrolment in progress". An earlier build
    // advanced it to escape a slow draw and threw away a two-thirds-answered set doing so. A fresh draw
    // comes from superseding an EXPIRED record instead, which re-publishes at a new height and is drawn
    // against the duty senders and beacon as of THAT height. Kept as a parameter because the chip helpers
    // are keyed on it and a future reroll may need more than one.
    let attempt: u32 = 0;
    let aik_pub = chip.aik_public_for(attempt)?;
    let id = enrol_id(relay, &chain, &aik_pub)?;
    println!("  enrolment  {id}");
    let mut stalled_polls: u32 = 0;

    let started = Instant::now();
    // What we last sent and when, so a message in flight is waited for rather than sent again.
    let mut in_flight: Option<(&'static str, Instant)> = None;
    loop {
        if started.elapsed() > GIVE_UP {
            return Err("gave up waiting: the drawn challengers did not answer in time. \
                        Re-run to start a fresh enrolment."
                .into());
        }
        // A SLOW ANSWER MUST NOT END AN EIGHT-MINUTE RUN. One read timeout killed a run at poll 38 while
        // the relay was demonstrably up and serving — a busy node can simply take longer than the socket
        // timeout on one request, and the enrolment is a multi-minute exchange by design. Transient
        // network failures are retried; only a protocol answer ends the loop.
        let rec = match fetch(relay, &id) {
            Ok(v) => v,
            Err(e) => {
                println!("  .. relay did not answer ({e}); retrying");
                sleep(POLL);
                continue;
            }
        };
        // A DEAD RECORD IS NOT A RECORD. An expired, unproven enrolment has a challenger set drawn under
        // whatever rule applied when it opened, and waiting on it waits forever — the two that never
        // answered are not coming back. Re-publishing supersedes it with a fresh draw. Without this a
        // chip could never escape one bad attempt, because the enrolment id is derived and identical
        // every time.
        let rec = match rec {
            Some(ref r) if r.get("expired").and_then(|v| v.as_bool()) == Some(true) => {
                println!("  .. the previous attempt expired; starting a fresh one");
                None
            }
            other => other,
        };

        // WAIT OUT A SLOW DRAW; NEVER ROTATE THE ATTESTATION KEY TO ESCAPE ONE. An earlier build gave up
        // after 18 polls and derived the next attestation key, on the theory that a new enrolment id
        // draws a fresh challenger set. That can never work, and it actively destroys good draws:
        //
        //   * a new attestation key means a new enrolment id, which is a NEW enrolment — and the chain
        //     bounds this chip to one open enrolment at a time. While the current record is live the
        //     relay refuses it outright: HTTP 403, "this chip already has an enrolment in progress".
        //     The rotation therefore cannot succeed by construction, and it cost a real draw that was
        //     two-thirds answered before anyone noticed.
        //   * it was never needed anyway. Superseding an EXPIRED record (the branch above) re-publishes
        //     at a new height, and the challenger set is drawn from the duty senders and beacon AS OF
        //     THAT HEIGHT — so the supersede already yields a completely different set without touching
        //     the attestation key. Observed on mainnet: one supersede replaced the whole drawn set.
        //
        // So the only legal escape from an unanswered draw is the enrolment window elapsing, and the
        // expired branch above then supersedes it. Until then the right thing is to say so and wait:
        // the challengers answer ON CHAIN, not to this process, so waiting costs nothing but patience.
        if let Some(ref r) = rec {
            let got = r.get("blobs").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
            let want = r.get("challengers").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
            let waiting = r.get("state").and_then(|v| v.as_str()) == Some("open") && got < want;
            if waiting {
                stalled_polls += 1;
                if stalled_polls % REPORT_EVERY == 0 {
                    println!("  .. still {got}/{want} after {}s. Waiting for the enrolment window to \
                              elapse; it then re-publishes with a freshly drawn set.",
                             stalled_polls * POLL.as_secs() as u32);
                }
            } else {
                stalled_polls = 0;
            }
        }
        if let Some((what, at)) = in_flight {
            if at.elapsed() < AWAIT_INCLUSION {
                println!("  .. waiting for {what} to be included ({}s)", at.elapsed().as_secs());
                sleep(POLL);
                continue;
            }
            println!("  .. {what} did not land within {}s; sending again",
                     AWAIT_INCLUSION.as_secs());
            in_flight = None;
        }
        match rec {
            None => {
                println!("  -> publishing this chip's endorsement chain");
                let data = json!({"ek": hexed(&chain), "pub": tx::hex(&aik_pub)});
                submit(relay, keys, signer, "tpm_enrol", data)?;
                in_flight = Some(("the enrolment", Instant::now()));
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
                            let secret = activate_all(&mut chip, attempt, &blobs)?;
                            let commit = crate::sha::sha256_hex(&secret);
                            submit(relay, keys, signer, "tpm_commit",
                                   json!({"id": id, "commit": commit}))?;
                            in_flight = Some(("the commitment", Instant::now()));
                        }
                    }
                    "commit" => {
                        let n = rec.get("reveals").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
                        println!("  .. committed; {n} challenger(s) have revealed");
                    }
                    "proven" => {
                        println!("  -> proven. Registering with a fresh certify.");
                        register(relay, keys, signer, vouch_for, &id, &rec, &mut chip, attempt)?;
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

fn activate_all(chip: &mut Chip, attempt: u32, blobs: &[Value]) -> Result<Vec<u8>, String> {
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
        out.extend_from_slice(&chip.activate_credential_for(attempt, &blob, &enc)?);
    }
    Ok(out)
}

fn register(relay: &Relay, keys: &tx::Keys, signer: &str, vouch_for: &str, id: &str,
            rec: &Map<String, Value>, chip: &mut Chip, attempt: u32) -> Result<(), String> {
    let ek = rec.get("ek").and_then(|x| x.as_str()).ok_or("record has no endorsement identity")?;
    let text = relay.get("/get_latest_block")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    let tip = v.get("block_number").and_then(|x| x.as_i64()).ok_or("relay gave no tip")?;
    // HOW LONG THE FINISHED PROOF STAYS USABLE, and it depends on WHO submits it. A `register` lands at
    // EXACTLY max_block, and the certify is bound to that height, so max_block is the proof's entire
    // shelf life.
    //
    //   self-submit: this program sends the transaction itself, seconds from now. A short window is right.
    //   HAND-BACK  : the proof goes to a wallet for a PERSON to confirm. tip + 12 gave them about eighty
    //                seconds, which is not a confirmation window, it is a race. The first proof this
    //                program ever produced on real silicon expired unsubmitted for exactly that reason:
    //                max_block 57017 against a tip of 57034 by the time anyone looked at it.
    //
    // The ceiling is the RELAY DROP STORE's, not the mempool's: ops/node_attest.drop refuses anything past
    // tip + POSW_TARGET_MARGIN + 30 = tip + 120, because that store was built for the wallet's old proving
    // budget. 110 sits inside it and buys about twelve minutes. If it does lapse, re-running this program
    // is cheap: the enrolment is already PROVEN on chain, so it skips the whole four-message ceremony and
    // only produces a fresh certify.
    let max_block = if vouch_for != signer { tip + 110 } else { tip + 12 };

    // The challenge is what makes this registration fresh rather than a replay: it binds this sender,
    // this anchor block and this landing height. The relay computes it so the client never has to
    // reproduce the chain's hash of them.
    let body = json!({"sender": vouch_for, "max_block": max_block}).to_string();
    let ch_text = relay.post_json("/register_challenge", &body)?;
    let ch: Value = serde_json::from_str(&ch_text).map_err(|e| format!("bad relay reply: {e}"))?;
    let challenge = tx::unhex(ch.get("challenge").and_then(|x| x.as_str())
        .ok_or_else(|| format!("relay gave no challenge: {ch_text}"))?)?;

    let (cert_info, sig) = chip.certify_for(attempt, &challenge)?;
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
        // PRINT THE REFUSAL, DO NOT ONLY RETURN IT. Two separate bugs presented to a remote tester as a
        // silent line repeating with an empty stderr, because the loop's error path was reached on a
        // later iteration or not at all. The relay always says why; the client should always show it.
        println!("  !! the relay refused it: {}", reply.trim());
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

/// The identity file: beside the program, and ONLY beside the program.
///
/// IT USED TO FALL BACK TO THE NODE'S OWN KEYFILE, and that was a bad idea that a test on a machine
/// running a node exposed immediately: it silently signed as the production node's address. A program
/// someone downloads and double-clicks must not reach into `~/nado/private/keys.dat` and use an
/// operator's live signing key because it happens to be on the same disk. The blast radius of a
/// downloaded helper should be the folder it was downloaded into.
///
/// A node operator who genuinely wants to enrol an existing identity passes `--keys` and says so.
fn identity_paths() -> Vec<std::path::PathBuf> {
    let mut out = Vec::new();
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            out.push(dir.join("nado-identity.json"));
        }
    }
    out
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
            println!("  signing as {} (from {})", keys.address, path.display());
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
    // A KEY THAT CANNOT BE SAVED MUST BE A HARD FAILURE, not a shrug. An ephemeral signing key changes
    // the account between runs, and the exchange requires the commitment to come from the same account
    // that opened the enrolment — so a silently unwritten identity breaks message 3 and looks like a
    // consensus rule rejecting a legitimate prover.
    write_private(&path, &serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())?)
        .map_err(|e| format!("{e}. The enrolment needs a signing key it can keep: without one the \
                              account changes between runs and the exchange cannot complete. Copy the \
                              program somewhere writable and run it there."))?;
    println!("  signing as {} (new, saved to {})", keys.address, path.display());
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
    // SELF-IDENTIFYING OUTPUT. Three builds of this program were in circulation on one test machine at
    // once, and a pasted transcript could not be attributed to any of them. A report that does not say
    // which binary produced it costs a round trip to find out.
    println!("  build {}", BUILD);
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
    run_auto(DEFAULT_RELAY, None)
}
