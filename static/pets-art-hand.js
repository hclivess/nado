// pets-art-hand.js — barrel that merges every hand-drawn per-animal art batch (static/pets-art/*.js) into
// one map keyed by animal name-slug. pets.js does `Object.assign(ART, HAND_ART)`, so drawOf() prefers a
// bespoke drawing over the legacy shared archetype. Add each new batch's import + spread as it lands.
//
// Batch module contract: `export const ART_<THEME> = { slug: (c,v) => "<svg inner markup>" }` (+ a matching
// `ROSTER_<THEME>`). slug = animal name lowercased with everything but [a-z0-9] stripped (pets.js petSlug).
// See the authoring spec in the session scratchpad (pet_art_spec.md).
import { ART_FARM } from "./pets-art/farm.js";
import { ART_WOODLAND } from "./pets-art/woodland.js";
import { ART_SAVANNA } from "./pets-art/savanna.js";
import { ART_SEA } from "./pets-art/sea.js";
import { ART_BIRDS } from "./pets-art/birds.js";
import { ART_MYTHICAL } from "./pets-art/mythical.js";

export const HAND_ART = {
  ...ART_FARM,
  ...ART_WOODLAND,
  ...ART_SAVANNA,
  ...ART_SEA,
  ...ART_BIRDS,
  ...ART_MYTHICAL,
};
