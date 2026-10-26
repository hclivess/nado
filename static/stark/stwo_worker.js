/* One Stwo proof, off the main thread (static/stark/stwo_js.js proveSpend starts one of these per proof and terminates
 * it after the answer). Message in: {witness: Uint8Array (prover.rs wallet_witness), dest: string, cfg: node config id
 * (stwo_js.js CFG_*)}. Out: {ok, out} with
 * the output record, or {ok: false, error}. The seed is 32 bytes of crypto.getRandomValues taken HERE, per proof — the
 * proof's zero-knowledge is that seed, so it never crosses a message and is never reused (the WASM refuses a repeat). */
import { StwoCore, proveWith, errDownload } from "./stwo_js.js";

let _core = null;
async function core() {
  if (!_core) {
    // "/static/vendor/stwo_js.wasm" is stamped with the file's content version by the server (ops/static_versions.py)
    const r = await fetch("/static/vendor/stwo_js.wasm");
    if (!r.ok) throw errDownload(r.status);
    _core = await StwoCore.instantiate(await r.arrayBuffer());
  }
  return _core;
}

self.onmessage = async (ev) => {
  try {
    const { witness, dest, cfg } = ev.data || {};
    const out = await proveWith(await core(), new Uint8Array(witness), dest || "",
      (n) => crypto.getRandomValues(new Uint8Array(n)), cfg);
    self.postMessage({ ok: true, out }, [out.buffer]);
  } catch (e) {
    _core = null;          // a trap leaves the instance unusable; the page terminates this worker anyway
    // the key travels with the English text, so the page re-raises it in the user's language (stwo_js.js errFromWorker)
    self.postMessage({ ok: false, error: String((e && e.message) || e), key: (e && e.i18nKey) || null,
                       fallback: (e && e.i18nDefault) || null, vars: (e && e.i18nVars) || null });
  }
};
