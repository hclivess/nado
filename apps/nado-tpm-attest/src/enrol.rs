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

use crate::colour::{bad, dim, head, id, ok, progress, warn};
use crate::http::Relay;
use crate::chip::{self, Chip};
use crate::tx;
use serde_json::{json, Map, Value};
use std::thread::sleep;
use std::time::{Duration, Instant};

/// Identifies the binary in its own output — see run_interactive.
pub const BUILD: &str = env!("NADO_BUILD");

/// Relays to try, in order, when none was given.
///
/// PORT 80 FIRST, because the node's own port is the thing most likely to be blocked. A home or office
/// network that filters outbound traffic, and a host firewall deciding what an unsigned download may do,
/// both let 80 through and both stop 9173 — a real machine failed here with nothing but "connection
/// attempt failed", on a network where the relay was up and answering everyone else. The hostname is
/// served over plain HTTP by the same relay, so this needs no TLS in a program people download and run.
///
/// The numeric address stays as the fallback: it needs no DNS, which is the other thing that breaks.
pub const DEFAULT_RELAYS: [&str; 6] = [
    "get.nadochain.com:80",       // port 80: the one a filtered network lets through
    "38.242.201.206:9173",
    "185.100.232.131:9173",
    "89.143.197.28:9173",
    "208.87.242.141:9173",
    "173.242.56.148:9173",
];
pub const DEFAULT_RELAY: &str = DEFAULT_RELAYS[0];

/// The first relay that answers, then everything that relay knows about.
///
/// ONE RELAY IS A SINGLE POINT OF FAILURE for something that takes twenty minutes. The enrolment is
/// entirely on chain — any node can serve it — so there is no reason to bind a run to the host that
/// happened to be compiled in. The list below is a STARTING POINT, not the network: whichever of them
/// answers is asked for its peers, so the client ends up choosing among every relay that node can see,
/// and a host that goes down mid-enrolment is not the end of the attempt.
fn relay_candidates() -> Vec<String> {
    let mut out: Vec<String> = DEFAULT_RELAYS.iter().map(|s| s.to_string()).collect();
    for cand in DEFAULT_RELAYS {
        let r = match Relay::parse(cand) {
            Ok(r) => r,
            Err(_) => continue,
        };
        let text = match r.get("/peers") {
            Ok(t) => t,
            Err(_) => continue,
        };
        if let Ok(Value::Array(peers)) = serde_json::from_str::<Value>(&text) {
            for p in peers {
                if let Some(ip) = p.as_str() {
                    // IPv6 needs brackets before a port can be appended, and a client on an IPv4-only
                    // network cannot use one anyway — skip rather than build an address that hangs.
                    if ip.contains(':') {
                        continue;
                    }
                    let hp = format!("{ip}:9173");
                    if !out.contains(&hp) {
                        out.push(hp);
                    }
                }
            }
        }
        break;                                  // one relay's view is enough to learn the rest
    }
    out
}

/// How far a relay may trail the best height seen and still be used. An enrolment spans many blocks,
/// so a few blocks of propagation lag is normal and irrelevant; hundreds mean the node is not
/// participating in the chain this enrolment has to land on.
const RELAY_STALE_BLOCKS: i64 = 120;

/// Height a relay reports, or None when it does not answer or does not say.
fn relay_height(r: &Relay) -> Option<i64> {
    let text = r.get("/status").ok()?;
    let v: Value = serde_json::from_str(&text).ok()?;
    crate::tx::set_address_format(&v);          // before any key is derived: every relay of a chain reports the same
    v.get("latest_block_height").and_then(|x| x.as_i64())
}

/// The most CURRENT relay that answers — not merely the first one that does.
///
/// ANSWERING IS NOT THE SAME AS PARTICIPATING (2026-09-13). This took the first relay to answer
/// `/status`, and a wedged node answers that instantly, correctly-shaped, forever. On the day this was
/// written get.nadochain.com — DEFAULT_RELAYS[0], the first thing every run tries — sat 5,200 blocks
/// behind the chain for eleven hours while answering every request in milliseconds. Every enrolment
/// started that day picked it, and the enrolment is a four-message exchange in which each message must
/// LAND before the next is sent: against a relay whose mempool never produces, the run cannot progress
/// and cannot say why.
///
/// So probe the candidates, read what height each is actually at, and take the highest. Relays that
/// trail it by more than RELAY_STALE_BLOCKS are named and skipped rather than silently preferred.
fn pick_relay() -> String {
    let cands = relay_candidates();
    let mut best: Option<(String, i64)> = None;
    let mut seen: Vec<(String, i64)> = Vec::new();
    for cand in &cands {
        let r = match Relay::parse(cand) {
            Ok(r) => r,
            Err(_) => continue,
        };
        match relay_height(&r) {
            Some(h) => {
                seen.push((cand.clone(), h));
                if best.as_ref().map_or(true, |(_, bh)| h > *bh) {
                    best = Some((cand.clone(), h));
                }
            }
            None => println!("  {} {}", warn(".."),
                             dim(&format!("{cand} did not answer; trying the next relay"))),
        }
    }
    let (chosen, top) = match best {
        Some(b) => b,
        // Nothing answered at all. Keep the compiled-in default so the caller's own error path reports
        // the real failure (no network / everything blocked) rather than this function inventing one.
        None => return DEFAULT_RELAYS[0].to_string(),
    };
    for (cand, h) in &seen {
        if top - *h > RELAY_STALE_BLOCKS {
            println!("  {} {}", warn(".."),
                     dim(&format!("{cand} is {} blocks behind the chain — skipping it", top - h)));
        }
    }
    println!("  {} {}", ok(".."), dim(&format!("using {chosen} at block {top}")));
    chosen
}

const POLL: Duration = Duration::from_secs(10);

/// How long to wait for a submitted message to be included before sending another.
///
/// A MESSAGE TAKES BLOCKS TO LAND, AND THE CLIENT MUST NOT KEEP SENDING WHILE IT WAITS. Publishing on
/// every poll produced a pool full of duplicates twice: once when the transaction could never be
/// included at all, and again when it could — each duplicate of an enrolment supersedes the last and
/// re-draws its challengers, so a client racing itself would reset the very set it is waiting on. The
/// chain refuses the duplicates, but only after they have cost a round trip each.
const AWAIT_INCLUSION: Duration = Duration::from_secs(90);

/// How long to watch for an auto-signing wallet to collect a handed-back proof before telling the owner
/// to do it by hand. Long enough for a couple of blocks plus the wallet's own poll interval, short
/// enough that someone whose wallet is closed is not left staring at a spinner.
const WALLET_PICKUP_WAIT: Duration = Duration::from_secs(60);

/// HOW OFTEN TO SAY SOMETHING WHILE WAITING ON A DRAW. There is deliberately no "give up and rotate the
/// attestation key" path any more; see the waiting branch below for why rotating cannot work.
const REPORT_EVERY: u32 = 18;
const GIVE_UP: Duration = Duration::from_secs(60 * 90);

/// Enrol with an identity this machine resolves for itself. No prompting and nothing pasted: the
/// enrolment proves a CHIP, not an owner, so it needs no secret from a person — and a program that
/// asks a user to paste a private key teaches a habit that is otherwise the definition of a scam.
pub fn run_auto(relay_arg: &str, vouch_override: Option<String>) -> Result<(), String> {
    crate::colour::enable();
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
    println!("  vouching for {}", id(&vouch_for));
    println!("               ({source})");
    println!("  relay      {}", dim(&format!("{}:{}", relay.host, relay.port)));
    let out = enrol_with(&relay, &keys, &own_address, &vouch_for);
    if out.is_ok() && target.is_none() {
        println!("  Import {} into your wallet to use this identity.", path.display());
    }
    out
}

pub fn run(args: &[String]) -> Result<(), String> {
    crate::colour::enable();
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
        let picked = if relay_arg.is_empty() { pick_relay() } else { relay_arg.clone() };
        return run_auto(&picked,
                        if vouch_arg.is_empty() { None } else { Some(vouch_arg) });
    }
    if relay_arg.is_empty() {
        relay_arg = pick_relay();
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
    let (id, chain) = enrol_id(relay, &chain, &aik_pub)?;
    println!("  enrolment  {}", crate::colour::id(&id));
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
            // A FAILED RECORD THAT HAS EXPIRED IS NOT "EXPIRED" TO ITS OWNER, it is a failure: say which, then try
            // again. If the chain's retry spacing has not run out yet the relay refuses the fresh enrolment and
            // names the block (submit_built, retry_refusal) — the program stops there instead of looping.
            Some(ref r) if r.get("expired").and_then(|v| v.as_bool()) == Some(true)
                && r.get("state").and_then(|v| v.as_str()) == Some("failed") => {
                println!("  {}", warn(".. the previous attempt failed (its answer did not match its \
                                       challengers); starting a fresh one"));
                None
            }
            Some(ref r) if r.get("expired").and_then(|v| v.as_bool()) == Some(true) => {
                println!("  {}", warn(".. the previous attempt expired; starting a fresh one"));
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
                            println!("  {} opening every challenge inside the chip", head("->"));
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
                        println!("  {} Registering with a fresh certify.", head("-> proven."));
                        register(relay, keys, signer, vouch_for, &id, &rec, &mut chip, attempt)?;
                        // SAY WHICH OF THE TWO THINGS ACTUALLY HAPPENED. This printed "the identity is
                        // registered" unconditionally — including directly after telling the owner to go
                        // and confirm the registration themselves, which is the opposite claim. A person
                        // read DONE and went looking for a registration that by construction could not
                        // have happened yet, because only the wallet holding the address can sign it.
                        if vouch_for == signer {
                            println!("\n  DONE: this chip is enrolled and the registration is submitted.\n");
                        } else {
                            println!("\n  The chip's part is DONE. The registration is NOT submitted yet —");
                            println!("  it is waiting for the wallet that owns {vouch_for}");
                            println!("  to confirm it, because only that wallet can sign it.\n");
                        }
                        return Ok(());
                    }
                    // ops/tpm_enrol.STATE_FAILED (live from TPM_ENROL_V3_HEIGHT): every challenger revealed, and
                    // the commitment this program sent did not match the secrets they had sealed. The chain
                    // will never prove this record, so waiting on it waits forever — and SAYING NOTHING TRUE
                    // IS NOT AN OPTION: an earlier build printed `unexpected enrolment state "failed"`, which
                    // tells the owner neither that nothing was registered nor when the chip may try again.
                    // INVARIANT: never print a success line on this branch, and always exit non-zero.
                    "failed" => {
                        let lines = failed_lines(&rec);
                        println!();
                        for (i, l) in lines.iter().enumerate() {
                            if i == 0 { println!("{}", bad(l)); } else { println!("{l}"); }
                        }
                        return Err("this enrolment failed; nothing was registered. Run this program \
                                    again after the waiting period described above.".into());
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

/// The enrolment id, AND the chain the relay actually verified.
///
/// TAKE THE RELAY'S CHAIN BACK. The relay finishes the AIA walk when this machine could not — a platform
/// that stores only a leaf, or a network that blocks the vendor's PKI, otherwise presents a short path and
/// is refused for something that is not about its hardware. If we then published OUR copy, consensus would
/// refuse the enrolment for the very reason the relay just repaired. The returned chain is not trusted
/// blindly: every node re-verifies it offline to a pinned root, so the worst a lying relay achieves is an
/// enrolment nobody accepts.
fn enrol_id(relay: &Relay, chain: &[Vec<u8>], aik_pub: &[u8]) -> Result<(String, Vec<Vec<u8>>), String> {
    let body = json!({"ek": hexed(chain), "pub": tx::hex(aik_pub)}).to_string();
    let text = relay.post_json("/tpm_enrol_id", &body)?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    let id = v.get("id").and_then(|x| x.as_str()).map(String::from)
        .ok_or_else(|| format!("relay could not derive the enrolment id: {text}"))?;
    let mut verified: Vec<Vec<u8>> = Vec::new();
    if let Some(arr) = v.get("chain").and_then(|x| x.as_array()) {
        for h in arr {
            if let Some(hs) = h.as_str() {
                if let Ok(der) = tx::unhex(hs) {
                    verified.push(der);
                }
            }
        }
    }
    if verified.len() > chain.len() {
        println!("  chip       the relay completed the chain to {} certificate(s)", verified.len());
    }
    let out = if verified.is_empty() { chain.to_vec() } else { verified };
    Ok((id, out))
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
    // THE CHAIN'S RETRY SPACING IS AN ANSWER, NOT AN ERROR TO RETRY. A chip whose last enrolment its client did not
    // complete must wait (ops/transaction_ops, ops/tpm_enrol.retry_ready_at), and the relay refuses with HTTP 403
    // and the exact block. Say that block and the rough wait, then STOP: resubmitting is refused identically until
    // then, so a loop would only spend the relay's rate limit. Every other refusal is passed through unchanged.
    let reply = match relay.post_json("/submit_transaction", &body) {
        Ok(r) => r,
        Err(e) => match retry_block(&e) {
            Some(n) => return Err(retry_refusal(relay, n)),
            None => return Err(e),
        },
    };
    if let Some(n) = retry_block(&reply) {
        println!("  !! the relay refused it: {}", reply.trim());
        return Err(retry_refusal(relay, n));
    }
    if reply.contains("\"result\": true") || reply.contains("\"result\":true") {
        // ACCEPTED IS NOT LANDED. `result: true` means one relay put it in its MEMPOOL — it says nothing
        // about whether any block ever carried it. A relay that is not producing (wedged, or far behind)
        // accepts happily and the transaction simply evaporates at max_block, which is how this program
        // could print a success line for a registration that never existed. The chain is the only
        // authority on whether a transaction happened, so ask it.
        await_inclusion(relay, &txid, max_block);
        Ok(())
    } else {
        // PRINT THE REFUSAL, DO NOT ONLY RETURN IT. Two separate bugs presented to a remote tester as a
        // silent line repeating with an empty stderr, because the loop's error path was reached on a
        // later iteration or not at all. The relay always says why; the client should always show it.
        println!("  !! the relay refused it: {}", reply.trim());
        Err(format!("the relay refused the transaction: {}", reply.trim()))
    }
}

/// The block a retry-spacing refusal names, if `text` is one. The node's message is "this chip's last enrolment was
/// not completed by its client — it can enrol again from block N" (ops/transaction_ops); the dash arrives JSON-escaped,
/// so this keys on the words after it. INVARIANT: if that message changes on the node, change this and its test.
pub fn retry_block(text: &str) -> Option<i64> {
    const MARK: &str = "can enrol again from block ";
    let at = text.find(MARK)? + MARK.len();
    let digits: String = text[at..].chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse().ok()
}

/// A rough duration for `blocks` blocks. ROUGH ON PURPOSE: block pacing is each node's local choice and not
/// consensus (CLAUDE.md "How a block gets made"), so this says "about" and uses the measured ~6.5 s cadence.
pub fn approx_wait(blocks: i64) -> String {
    if blocks <= 0 {
        return "now".into();
    }
    let secs = blocks * 13 / 2;
    let mins = (secs + 59) / 60;
    if mins < 2 {
        "about a minute".into()
    } else if mins < 120 {
        format!("about {mins} minutes")
    } else if mins < 48 * 60 {
        format!("about {} hours", (mins + 30) / 60)
    } else {
        format!("about {} days", (mins + 12 * 60) / (24 * 60))
    }
}

/// What to tell the owner when the relay refuses a fresh enrolment because the chip must still wait. Prints the
/// explanation and returns the one-line error main() shows on exit.
fn retry_refusal(relay: &Relay, ready: i64) -> String {
    let tip = relay.get("/status").ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v.get("latest_block_height").and_then(|x| x.as_i64()));
    for (i, l) in retry_lines(ready, tip).iter().enumerate() {
        if i == 0 { println!("{}", bad(l)); } else { println!("{l}"); }
    }
    format!("this chip can enrol again from block {ready}; run this program again after that")
}

/// The text of retry_refusal, separated so it can be tested without a relay.
pub fn retry_lines(ready: i64, tip: Option<i64>) -> Vec<String> {
    let mut out = vec![
        "  !! This chip has to wait before it can enrol again.".to_string(),
        "     Its last enrolment was not completed by its client, so the chain spaces out the next try.".to_string(),
    ];
    match tip {
        Some(t) if t < ready => out.push(format!(
            "     It can enrol again from block {ready}. The chain is at block {t}: {} blocks to go, {}.",
            ready - t, approx_wait(ready - t))),
        _ => out.push(format!("     It can enrol again from block {ready}.")),
    }
    out.push("     Nothing was registered by this run. Run this program again once that block is reached.".to_string());
    out
}

/// What to tell the owner about a FAILED enrolment record (ops/tpm_enrol.STATE_FAILED).
///
/// THE EXACT RETRY BLOCK COMES FROM THE RELAY, never from a copy of the rule: a relay that serves `retry_ready_at`
/// (transaction_ops.tpm_retry_view — the block validation accepts the next enrolment at) is quoted exactly. An older
/// relay serves only `expires_at`, a true lower bound, so then say "not before" that; the relay names the exact block
/// when asked too early either way. Copying the node's constants here would be a second copy of a consensus rule.
pub fn failed_lines(rec: &Map<String, Value>) -> Vec<String> {
    let ready = rec.get("retry_ready_at").and_then(|v| v.as_i64());
    let expires = rec.get("expires_at").and_then(|v| v.as_i64());
    let tip = rec.get("tip").and_then(|v| v.as_i64());
    let mut out = vec![
        "  !! This enrolment did NOT complete.".to_string(),
        "     The answer this machine sent its challengers did not match the secrets they had sealed to".to_string(),
        "     this chip, so the chain marked the enrolment failed. Nothing was registered, and no".to_string(),
        "     identity gained anything from this attempt.".to_string(),
    ];
    match (expires, tip) {
        _ if ready.is_some() => {
            let r = ready.unwrap_or(0);
            match tip {
                Some(t) if t < r => out.push(format!(
                    "     This chip can start a new enrolment from block {r} (the chain is at block {t}, so {});\n     \
                     each failed attempt makes the wait longer.", approx_wait(r - t))),
                _ => out.push(format!("     This chip can start a new enrolment now (from block {r}).")),
            }
        }
        (Some(e), Some(t)) if t < e => out.push(format!(
            "     This chip can start a new enrolment after a waiting period that ends no earlier than\n     \
             block {e} (the chain is at block {t}, so at least {}); each failed attempt makes the\n     \
             wait longer.", approx_wait(e - t))),
        (Some(e), _) => out.push(format!(
            "     This chip can start a new enrolment after a waiting period that ends no earlier than\n     \
             block {e}; each failed attempt makes the wait longer.")),
        _ => out.push("     This chip can start a new enrolment after a waiting period; each failed attempt \
                       makes the wait longer.".to_string()),
    }
    out.push("     To retry, run this program again later. If it is still too early, the relay refuses and".to_string());
    out.push("     this program prints the exact block it can enrol from.".to_string());
    out
}

/// Leave the finished device proof where the wallet will find it. The wallet signs the registration,
/// because only it can — see the comment at the call site.
fn hand_back(relay: &Relay, address: &str, id: &str, device: &Value,
             max_block: i64) -> Result<(), String> {
    let body = json!({"address": address, "id": id, "device": device, "max_block": max_block})
        .to_string();
    // LEAVE IT ON EVERY RELAY, NOT JUST OURS. The drop store is a per-node IN-MEMORY dict — never
    // persisted, never gossiped (ops/node_attest.py) — and the wallet looks for the proof on whichever
    // relay IT is using. Those are not the same host: this helper now picks the most CURRENT relay while
    // a browser defaults to get.nadochain.com and rotates on its own when that one stalls. So a proof
    // dropped on one node was invisible to a wallet on another, and the owner pressed Renew against a
    // relay that had never heard of their chip. Reported within the hour of shipping the relay choice.
    //
    // Broadcasting is cheap and safe: a statement is 1-8 KB, the store is bounded and expiring, and a drop
    // is not a credential — consensus re-verifies the certify and the register is still signed by the
    // wallet alone. One relay accepting is enough; we only fail if none did.
    let mut accepted = 0usize;
    let mut tried = 0usize;
    for cand in relay_candidates() {
        let r = match Relay::parse(&cand) {
            Ok(r) => r,
            Err(_) => continue,
        };
        tried += 1;
        // COUNT WHAT THE RELAY SAID, NOT THAT IT SPOKE. post_json succeeds on any HTTP reply, and a
        // refusal is a perfectly good reply — {"ok": false, "reason": ...}. Counting those as accepted
        // would print "left on 6 of 6 relays, so any wallet can find it" over a proof that no relay
        // kept, which is the exact class of false success line this program has already burned an owner
        // with once.
        if let Ok(reply) = r.post_json("/tpm_proof_drop", &body) {
            if reply.contains("\"ok\": true") || reply.contains("\"ok\":true") {
                accepted += 1;
            }
        }
    }
    if accepted == 0 {
        // NOBODY KEPT IT. Try the relay this run used one more time and report what it actually says —
        // a proof no relay holds is a failed hand-back, and saying so is the whole point of counting.
        let reply = relay.post_json("/tpm_proof_drop", &body)?;
        if !(reply.contains("\"ok\": true") || reply.contains("\"ok\":true")) {
            println!("  {} {}", bad("!!"), format!("no relay kept the proof: {}", reply.trim()));
            return Err(format!("no relay accepted the device proof: {}", reply.trim()));
        }
        accepted = 1;
    }
    println!("  {} {}", ok(".."),
             dim(&format!("proof left on {accepted} of {tried} relays, so any wallet can find it")));
    println!();
    println!("  {} {}", ok("This PC's chip has vouched for"), crate::colour::id(address));
    // SAY WHETHER THERE IS ANYTHING TO CONFIRM. A wallet only collects a proof when it actually needs to
    // register — first registration, an expired lease, or a presence mismatch. An address that is ALREADY
    // registered and present has nothing to do, so telling its owner to "open your wallet and confirm"
    // sends them looking for a control that will never appear, which is exactly what happened to the first
    // owner to complete this flow: they registered successfully, ran the helper again, and were told to
    // confirm something the wallet had no reason to show.
    let live = relay.get(&format!("/mining_status?address={address}"))
        .ok()
        .and_then(|t| serde_json::from_str::<Value>(&t).ok())
        .and_then(|v| v.get("registered_present").and_then(|x| x.as_bool()))
        .unwrap_or(false);
    if live {
        println!("  That address is ALREADY registered with a device and mining, so there is nothing to");
        println!("  confirm right now. The proof has been left on the relay anyway: your wallet will pick");
        println!("  it up by itself if the registration ever lapses and needs renewing.");
        return Ok(());
    }
    // SOME WALLETS SIGN IT THEMSELVES (operator 2026-09-13). A wallet that is open and set to sign
    // automatically collects this proof and registers within a block or two — so sending its owner off to
    // "open your wallet and confirm" is an instruction that was already carried out, for a control that
    // will have disappeared by the time they look. Watch the chain for a short while first and let it
    // answer the question; only ask the person to act if nobody did.
    println!("  The proof is on the relay. Watching for your wallet to pick it up…");
    let started = Instant::now();
    let mut registered = false;
    while started.elapsed() < WALLET_PICKUP_WAIT {
        sleep(POLL);
        let now_live = relay.get(&format!("/mining_status?address={address}"))
            .ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok())
            .and_then(|v| v.get("registered_present").and_then(|x| x.as_bool()))
            .unwrap_or(false);
        if now_live {
            registered = true;
            break;
        }
        println!("  {} {}", dim(".."), dim(&format!("waiting ({}s)", started.elapsed().as_secs())));
    }
    if registered {
        println!();
        println!("  {} {}", ok("Your wallet signed it and the registration is on chain."),
                 dim("Nothing further to do."));
    } else {
        println!();
        println!("  Open your wallet and confirm the registration — it must sign that itself, because a");
        println!("  registration is signed by the identity it registers. The proof is waiting for it.");
    }
    Ok(())
}

/// Watch the chain until `txid` is in a block, or until `max_block` passes and it never can be.
///
/// Reports rather than fails: by the time this runs the transaction is signed and accepted, and the
/// caller's next step is usually to keep waiting anyway. What it removes is the SILENCE — an owner who
/// is told "submitted" and then watches nothing happen has no way to tell a slow chain from a dead
/// relay, and neither did this program.
fn await_inclusion(relay: &Relay, txid: &str, max_block: i64) -> bool {
    let started = Instant::now();
    loop {
        if let Ok(text) = relay.get(&format!("/get_transaction?txid={txid}")) {
            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                // EXISTENCE IS THE CONFIRMATION. /get_transaction reads the MINED-tx index, so a hit
                // means a block carried it; there is no block_number in the reply to test (checked
                // against the live node — the keys are the transaction's own fields). A miss answers
                // {"txid": "Not found"}, so the discriminator is whether `sender` came back, not
                // whether the request succeeded.
                let landed = v.get("sender").and_then(|x| x.as_str()).is_some()
                    && v.get("txid").and_then(|x| x.as_str()) == Some(txid);
                if landed {
                    println!("  {} {}", ok(".."), dim("confirmed on chain"));
                    return true;
                }
            }
        }
        let tip = relay.get("/status").ok()
            .and_then(|t| serde_json::from_str::<Value>(&t).ok())
            .and_then(|v| v.get("latest_block_height").and_then(|x| x.as_i64()))
            .unwrap_or(0);
        if tip > max_block {
            // PAST ITS DEADLINE AND NOT IN A BLOCK. `register` lands exactly at max_block, so once the
            // tip is beyond it the transaction can never be included by anyone. Say so plainly; the
            // alternative is an owner waiting on something the chain has already discarded.
            println!("  {} {}", bad("!!"),
                     format!("the transaction was accepted by the relay but never reached a block \
                              (deadline {max_block}, chain is at {tip})"));
            return false;
        }
        if started.elapsed() > AWAIT_INCLUSION {
            println!("  {} {}", warn(".."),
                     dim(&format!("not in a block yet after {}s (deadline {max_block}, chain at {tip}) \
                                   — still waiting", started.elapsed().as_secs())));
            return false;
        }
        sleep(POLL);
    }
}

fn chain_id(relay: &Relay) -> Result<String, String> {
    let text = relay.get("/status")?;
    let v: Value = serde_json::from_str(&text).map_err(|e| format!("bad relay reply: {e}"))?;
    crate::tx::set_address_format(&v);
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
    run_auto(&pick_relay(), None)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rec(v: Value) -> Map<String, Value> {
        v.as_object().cloned().unwrap()
    }

    #[test]
    fn a_failed_enrolment_says_nothing_was_registered_and_never_claims_success() {
        let lines = failed_lines(&rec(json!({"state": "failed", "expires_at": 132500, "tip": 132400})));
        let all = lines.join("\n");
        assert!(all.contains("did NOT complete"));
        assert!(all.contains("Nothing was registered"));
        assert!(all.contains("no earlier than\n     block 132500"));
        assert!(all.contains("run this program again"));
        assert!(!all.contains("DONE"), "a failed enrolment must never print a success line");
    }

    #[test]
    fn a_failed_enrolment_quotes_the_relays_exact_retry_block() {
        let all = failed_lines(&rec(json!({"state": "failed", "expires_at": 132500, "retry_ready_at": 133100,
                                           "tip": 132400}))).join("\n");
        assert!(all.contains("from block 133100"), "{all}");
        assert!(!all.contains("no earlier than"), "an exact block is not a lower bound: {all}");
        assert!(!all.contains("DONE"));
    }

    #[test]
    fn a_failed_enrolment_without_an_expiry_gives_no_invented_block() {
        let all = failed_lines(&rec(json!({"state": "failed"}))).join("\n");
        assert!(all.contains("after a waiting period"));
        assert!(!all.contains("block 0"));
    }

    #[test]
    fn the_retry_block_is_read_from_the_relays_refusal_as_it_arrives() {
        // as main() sees it: post_json's HTTP-403 error, with the dash JSON-escaped by aiohttp
        let e = "relay returned HTTP 403: {\"result\": false, \"message\": \"this chip's last enrolment was not \
                 completed by its client \\u2014 it can enrol again from block 133100\"}";
        assert_eq!(retry_block(e), Some(133100));
        assert_eq!(retry_block("it can enrol again from block 42"), Some(42));
        assert_eq!(retry_block("this chip already has an enrolment in progress"), None);
        assert_eq!(retry_block("can enrol again from block x"), None);
    }

    #[test]
    fn the_retry_refusal_names_the_block_and_a_rough_wait() {
        let all = retry_lines(133100, Some(132800)).join("\n");
        assert!(all.contains("from block 133100"));
        assert!(all.contains("300 blocks to go, about 33 minutes"));
        assert!(!retry_lines(133100, None).join("\n").contains("to go"));
    }

    #[test]
    fn rough_waits_read_naturally() {
        assert_eq!(approx_wait(0), "now");
        assert_eq!(approx_wait(5), "about a minute");
        assert_eq!(approx_wait(300), "about 33 minutes");
        assert_eq!(approx_wait(76800), "about 6 days");
    }
}
