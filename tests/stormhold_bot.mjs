/*
 * stormhold_bot.mjs — test-side wrapper: loads the crypto bundle, then re-exports the SHARED bot that
 * also powers the browser practice mode (static/stormhold-bot.js).
 */
import { loadCrypto } from "../static/nadotx.js";
await loadCrypto(".");
export { prng, randomMove } from "../static/stormhold-bot.js";
