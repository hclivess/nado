// autogame-rules.js — GENERATED from execnode/games/autogame.py. Do not edit by hand.
//   regenerate:  python3 -m execnode.games.autogame --emit-js
//
// The contract is the authority on every number in this game. The browser cannot import Python, so
// this file is emitted from it rather than transcribed — the engine, the contract and the Python
// reference model then all trace back to one definition, and tests/autogame_contract_test.py fails
// the moment this file stops matching its source.

export const LEG = 16;
export const MAX_LEGS_PER_CALL = 1;
export const CHAPTER = 512;
export const START_GAP = 2;
export const HP0 = 100;
export const STAM_MAX = 12;
export const AGG_MAX = 16;
export const REGEN_DIV = 20;
export const REGEN_CAP_DIV = 8;
export const BOSS_EVERY = 128;
export const TIER_EVERY = 32;
export const NIGHT_EVERY = 64;
export const LEVEL_CAP = 8;
export const LIFESTEAL_DIV = 4;
export const HORDE_DIV = 4;
export const STREAK_DIV = 4;
export const DEATH_KEEP = 25;
export const COMPLETE_BONUS = 200000;
export const POTIONS0 = 3;
export const POTION_CAP = 5;
export const POTION_PRICE = 10;
export const HEAL_BASE = 20;
export const SHRINE_BASE = 10;
export const RALLY_BASE = 4;
export const NSLOT = 6;
export const TILE_CUTS = [18, 36, 43, 50, 55, 57, 62, 64, 65, 68, 70, 74, 77, 79, 81, 83, 86, 88, 90, 92, 94, 97, 99];
export const NTILE = 25;
export const ROAD = 0;
export const MONSTER = 1;
export const HORDE = 2;
export const ELITE = 3;
export const AMBUSH = 4;
export const MIMIC = 5;
export const HAZARD = 6;
export const SNARE = 7;
export const QUAG = 8;
export const GALE = 9;
export const TOLLGATE = 10;
export const CACHE = 11;
export const BARROW = 12;
export const ARMORY = 13;
export const VEIN = 14;
export const GROVE = 15;
export const SHRINE = 16;
export const WELL = 17;
export const CAMP = 18;
export const IDOL = 19;
export const PYRE = 20;
export const FORGE = 21;
export const FORK = 22;
export const RELIC = 23;
export const BOSS = 24;
export const A_DEFAULT = 0;
export const A_STRIKE = 1;
export const A_GUARD = 2;
export const A_DODGE = 3;
export const A_POTION = 4;
export const A_SPRINT = 5;
export const A_REST = 6;
export const A_RIGHT = 7;
export const A_RALLY = 7;
export const COST = [0, 2, 2, 2, 0, 3, 0, 3];
export const ST_BALANCED = 0;
export const ST_AGGRESSIVE = 1;
export const ST_GUARDED = 2;
export const ST_EVASIVE = 3;
export const STANCES = [[4, 4, 1, 12], [5, 6, 2, 20], [3, 4, 0, 0], [4, 4, 1, 16]];
export const FAM_ATK = [[1, 1], [3, 3], [2, 2]];
export const FAM_XP = [[0, 1], [0, 3], [0, 5]];
export const SHARPEN_COST = [2, 0, 1];
export const REINFORCE_COST = [1, 2, 0];
export const DEF_DIV = [1, 4, 2, 3, 4, 4];
export const G_WEAPON = 0;
export const G_HELM = 1;
export const G_BODY = 2;
export const G_SHIELD = 3;
export const G_BOOTS = 4;
export const G_CLOAK = 5;
export const AF_NONE = 0;
export const AF_KEEN = 1;
export const AF_HEAVY = 2;
export const AF_WARD = 3;
export const AF_SWIFT = 4;
export const AF_VAMP = 5;
export const AF_BLAZE = 6;
export const AF_HALLOW = 7;
export const AFFIX_NAMES = ["none", "keen", "heavy", "warding", "swift", "vampiric", "blazing", "hallowed"];
export const KEEN_BONUS = 6;
export const SWIFT_BONUS = 2;
export const JACKPOT_EVERY = 32;
export const W_SWORD = 0;
export const W_AXE = 1;
export const W_MAUL = 2;
export const W_SPEAR = 3;
export const NWKIND = 4;
export const WKIND_NAMES = ["sword", "axe", "maul", "spear"];

// tile class -> display name, in the order the class ordinal is derived (see TILE_CUTS)
export const TILE_NAMES = ["road", "monster", "horde", "elite", "ambush", "mimic", "hazard", "snare", "quag", "gale", "tollgate", "cache", "barrow", "armory", "vein", "grove", "shrine", "well", "camp", "idol", "pyre", "forge", "fork", "relic", "boss"];
export const RANKS = [[60, "peasant"], [300, "commoner"], [1000, "porter"], [3000, "apprentice"], [8000, "journeyman"], [20000, "sellsword"], [45000, "freerider"], [80000, "veteran"], [130000, "knight"], [190000, "banneret"], [260000, "champion"], [330000, "warlord"], [400000, "baron"], [480000, "margrave"], [560000, "duke"], [650000, "prince"], [780000, "king"], [900000, "emperor"], [1050000, "demigod"], [1099511627776, "creator"]];

// which actions actually change the outcome on each tile class — DERIVED by
// tests/autogame_action_matrix.py from the rules themselves, never hand-written
export const ACTS_FOR = {[0]: [0, 4, 6, 7], [1]: [0, 1, 2, 3, 4, 6, 7], [2]: [0, 1, 2, 3, 4, 5, 6, 7], [3]: [0, 1, 2, 3, 4, 6, 7], [4]: [0, 1, 2, 3, 4, 5, 6, 7], [5]: [0, 1, 2, 3, 4, 6, 7], [6]: [0, 3, 4, 6, 7], [7]: [0, 1, 2, 3, 4, 6, 7], [8]: [0, 1, 2, 3, 4, 6, 7], [9]: [0, 4, 6, 7], [10]: [0, 1, 3, 4, 6, 7], [11]: [0, 3, 4, 6, 7], [12]: [0, 2, 3, 4, 6, 7], [13]: [0, 3, 4, 6, 7], [14]: [0, 1, 4, 6, 7], [15]: [0, 4, 6, 7], [16]: [0, 3, 4, 6, 7], [17]: [0, 4, 6, 7], [18]: [0, 4, 6, 7], [19]: [0, 1, 4, 6, 7], [20]: [0, 1, 4, 6, 7], [21]: [0, 3, 4, 6, 7], [22]: [0, 7], [23]: [0, 3, 4, 6, 7], [24]: [0, 1, 2, 3, 4, 6, 7]};
