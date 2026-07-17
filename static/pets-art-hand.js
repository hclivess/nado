// pets-art-hand.js — barrel that merges every hand-drawn per-animal art batch (static/pets-art/*.js) into
// one map keyed by animal name-slug. pets.js does `Object.assign(ART, HAND_ART)`, so drawOf() prefers a
// bespoke drawing over the legacy shared archetype. Add each new batch's import + spread as it lands.
//
// Batch module contract: `export const ART_<THEME> = { slug: (c,v) => "<svg inner markup>" }` (+ a matching
// `ROSTER_<THEME>`). slug = animal name lowercased with everything but [a-z0-9] stripped (pets.js petSlug).
// See the authoring spec in the session scratchpad (pet_art_spec.md / METHOD.md).
import { ART_FARM } from "./pets-art/farm.js";
import { ART_WOODLAND } from "./pets-art/woodland.js";
import { ART_SAVANNA } from "./pets-art/savanna.js";
import { ART_SEA } from "./pets-art/sea.js";
import { ART_BIRDS } from "./pets-art/birds.js";
import { ART_MYTHICAL } from "./pets-art/mythical.js";
import { ART_REPTILES } from "./pets-art/reptiles.js";
import { ART_BUGS } from "./pets-art/bugs.js";
import { ART_DINOS } from "./pets-art/dinos.js";
import { ART_PRIMATES } from "./pets-art/primates.js";
import { ART_WILDCATS } from "./pets-art/wildcats.js";
import { ART_HOOFED } from "./pets-art/hoofed.js";
import { ART_REEF } from "./pets-art/reef.js";
import { ART_EXOTICBIRDS } from "./pets-art/exoticbirds.js";
import { ART_RODENTS } from "./pets-art/rodents.js";
import { ART_POLAR } from "./pets-art/polar.js";
import { ART_ODDBALLS } from "./pets-art/oddballs.js";
import { ART_DOGBREEDS } from "./pets-art/dogbreeds.js";
import { ART_CATBREEDS } from "./pets-art/catbreeds.js";
import { ART_UNDEAD } from "./pets-art/undead.js";
import { ART_ELEMENTALS } from "./pets-art/elementals.js";
import { ART_CRYPTIDS } from "./pets-art/cryptids.js";
import { ART_ROBOTS } from "./pets-art/robots.js";
import { ART_FANTASYBEASTS } from "./pets-art/fantasybeasts.js";
import { ART_SEAMONSTERS } from "./pets-art/seamonsters.js";

export const HAND_ART = {
  ...ART_FARM,
  ...ART_WOODLAND,
  ...ART_SAVANNA,
  ...ART_SEA,
  ...ART_BIRDS,
  ...ART_MYTHICAL,
  ...ART_REPTILES,
  ...ART_BUGS,
  ...ART_DINOS,
  ...ART_PRIMATES,
  ...ART_WILDCATS,
  ...ART_HOOFED,
  ...ART_REEF,
  ...ART_EXOTICBIRDS,
  ...ART_RODENTS,
  ...ART_POLAR,
  ...ART_ODDBALLS,
  ...ART_DOGBREEDS,
  ...ART_CATBREEDS,
  ...ART_UNDEAD,
  ...ART_ELEMENTALS,
  ...ART_CRYPTIDS,
  ...ART_ROBOTS,
  ...ART_FANTASYBEASTS,
  ...ART_SEAMONSTERS,
};
