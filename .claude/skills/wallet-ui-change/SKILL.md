---
name: wallet-ui-change
description: Change the wallet interface (static/interface.html, .js, .css). Use for any user-facing wallet edit - it must be translated into 16 languages and looked at on a phone before it is done.
---

# Changing the wallet

Two things are not optional, and both have been skipped in this repo with real consequences: the
translations, and **looking at it**.

## 1. Sixteen languages

`static/i18n.js` carries 16 tables — en, cs, es, pt, fr, de, it, ru, zh, ja, ko, ar, hi, tr, id, vi. A
string added in English only is half-finished: the default is a fallback for a *missing* translation, not
a substitute for one.

Every `i18("key", "English default")` needs its key in all sixteen. Insert by locating a neighbouring key
in each table rather than hand-editing a 7 MB file:

```python
markers = [(m.start(), m.group(1)) for m in re.finditer(r'"([a-z]{2})"\s*:\s*\{', s)]
occ     = [m.start() for m in re.finditer(r'"some\.neighbour\.key"\s*:', s)]
# map each occurrence to the nearest preceding language marker, insert the new keys before it
```

```bash
node --check static/i18n.js
node tests/i18n_coverage.mjs        # every referenced key defined in every language
```

`ar` is right-to-left, and a dropped `{a}` / `{n}` placeholder is a broken sentence rather than a cosmetic
defect.

## 2. Look at it, at 412 and 360

Reading the diff is not looking at it. Two defects in one pass were invisible in the source and obvious in
a screenshot: a link marked `primary` rendered grey because the style was scoped to `button.primary`, and
a status line enumerated five device types directly above a button that made the enumeration pointless.

```bash
python3 /tmp/shot2.py 412 /tmp/ui-412.png     # selenium + /usr/bin/chromium-browser
python3 /tmp/shot2.py 360 /tmp/ui-360.png
```

The wallet needs an identity before most of it renders: click `#btnGenerate`, then tick `#ackSave`
(the backup acknowledgement gates the rest), then `button[data-tabbtn='mine']`.

Screenshot the **collapsed** state — that is the first impression. Forcing `details` open shows you a page
no user sees.

## 3. Design rules that already cost something here

- **One primary action.** The remedy goes *above* the explanation, as a button, not inside a disclosure
  called "why this failed" four paragraphs down.
- **One sentence when there is a button.** A list of every alternative is guidance for someone with no way
  forward, and noise above a control that is the way forward.
- **Name the platform in front of the user.** Offer the other one small, one line below.
- **Never offer an action that cannot work here** — the helper on a phone or a Mac is the same mistake
  pointing the other way.
- **No self-deleting success.** A banner on a timer tells the user their success was provisional. Retract
  banners with `clearRegBanner(tag)` when something contradicts them, and not before.
- **The chain overrules stored state**, in both directions. A `localStorage` verdict is a memory of one
  attempt on one device, not a fact about the identity.

## 4. Deploy and prove the asset changed

Pushing restarts production and serves `static/`. The page stamps assets `?v=<mtime>`; after deploying,
confirm the **served HTML asks for a new stamp** and the served JS contains your change — a stale stamp
means browsers keep the old file:

```bash
curl -s -A "$UA" https://get.nadochain.com/ | grep -oE 'interface\.js\?v=[0-9]+'
curl -s -A "$UA" https://get.nadochain.com/static/interface.js | grep -c "yourNewFunction"
```
