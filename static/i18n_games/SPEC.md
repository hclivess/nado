# Game i18n spec (follow EXACTLY)

You internationalize ONE NADO game: its `static/<game>.html` and `static/<game>.js` (and any
`static/<game>-engine.js` you were told about). The shared runtime is `static/i18n.js` — read its
top comment. It self-initializes on DOMContentLoaded: builds a language picker, localizes every
`[data-i18n*]` element, and exposes `window.t(key, fallback, vars)`. You DO NOT edit `i18n.js`.

## Steps

1. **Load the runtime.** In `<head>`, after the `<title>`/meta lines and BEFORE any game `<script>`,
   add exactly:  `<script src="/static/i18n.js"></script>`
   (It is a classic script — `window.t` is available synchronously for the game module at end of body.)

2. **Tag every user-facing STATIC string** in the HTML with a game-namespaced key `"<game>.<slug>"`:
   - visible text of an element → `data-i18n="<game>.slug"` (localizes the element's leading text node,
     preserving child `<span>`/icons — so put it on the element whose FIRST text node is the label)
   - element whose whole innerHTML is prose (may contain `<b>`, `<span>`…) → `data-i18n-html="<game>.slug"`
   - `placeholder="…"` → add `data-i18n-ph="<game>.slug"`
   - `title="…"` → add `data-i18n-title="<game>.slug"`
   Leave the existing English text in place (it is the fallback). Tag headings, buttons, labels,
   help paragraphs, table headers, option labels, footer — ALL visible copy. Do NOT tag: ids, code,
   numbers-only, the address-bar/mono value spans that hold live data.

3. **Wrap dynamic JS strings** the user sees (status messages, alerts, button labels set in JS,
   toast/error text) in `window.t("<game>.key", "<exact English>", {var: value})`:
   - Preserve `{placeholders}` and interpolation. If the code does `"You won " + x + " NADO"`, convert
     to `window.t("<game>.won", "You won {x} NADO", {x})`.
   - DO NOT wrap or alter: protocol/contract strings (method names, op names, cids, storage-map keys,
     recipient names), URLs, `console.log`/debug-only text, non-user-facing internal strings, or ANY
     game logic. When unsure, leave it. Never change control flow.
   - Use `window.t` (not bare `t`) since these are non-module or module scripts loading after i18n.js.

4. **Write translations** to `static/i18n_games/<game>.json` — a JSON object
   `{"en": {key: text}, "cs": {...}, "es": {...}, "pt": {...}, "fr": {...}, "de": {...}, "it": {...},
   "ru": {...}, "zh": {...}, "ja": {...}, "ko": {...}, "ar": {...}, "hi": {...}, "tr": {...},
   "id": {...}, "vi": {...}}` containing EVERY key you introduced (in html + js), with:
   - `en` = the exact English source string (must match the fallback you passed).
   - all 15 other languages = natural, concise, native UI translations (not word-for-word).
   Terminology: keep "NADO"; a game "table"/"pot"/"bankroll"/"bet"/"roll"/"spin" reads naturally per
   language; "escrow"/"stake"/"exec/execution layer"/"L1" as in a crypto app. Preserve `{placeholders}`
   EXACTLY, and any emoji.

## Rules
- Keys are namespaced `<game>.` so games never collide.
- Every key in the html/js MUST be in the JSON's `en` (and thus all langs). No orphan keys, no unused keys.
- After editing, the game JS must still be syntactically valid (`node --check static/<game>.js`) and the
  HTML well-formed. Verify before finishing.
- 16 languages, all present in the JSON. RTL (ar) text is fine as-is; i18n.js flips `dir` automatically.
