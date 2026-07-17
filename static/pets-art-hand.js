// pets-art-hand.js — BESPOKE, hand-drawn per-animal SVG art, keyed by animal name-slug (lowercased, only
// [a-z0-9]). Each themed batch file under this folder exports a partial map; this barrel merges them all.
// pets.js drawOf() prefers this per-animal art over the legacy shared archetypes (which remain only as a
// fallback while the 1000-animal roster is drawn out).
//
// Each entry: slug -> (c, v) => "<svg inner markup string>"
//   · viewBox is 0 0 120 120; keep the animal roughly within x,y ∈ [8,112], centered ~ (60, 62).
//   · COAT: use c.body (fill), c.shade (darker accent), c.line (outline). Eyes: eyes2(x1,x2,y,r) / eye1;
//     eye colour via eyeCol(c). Mouth: smilew(x,y,w2). Pom tufts: pom(cx,cy,r,fill,line). Sausage limbs/
//     tails: tube(d,fill,line,w). INK = dark ink. All these helpers exist in pets.js scope at call time.
//   · ANIMATE for life: wrap the torso in <g class="breathe">…</g>, eyes in the eyes2 (auto-blinks), the
//     head in <g class="head-tilt">…</g>, tails/wings in <g class="tail-wag">…</g>. Aquatic/flying animals
//     set float:true in their roster entry so the frame drifts.
//   · v (variant params) is passed through but bespoke art may ignore it — each drawing is specific to ONE
//     animal, so it should look on-spot without needing params.
export const HAND_ART = {};
