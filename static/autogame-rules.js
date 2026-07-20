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
export const TILE_CUTS = [30, 58, 66, 74, 82, 87, 92, 99];
export const ROAD = 0;
export const MONSTER = 1;
export const ELITE = 2;
export const HAZARD = 3;
export const CACHE = 4;
export const SHRINE = 5;
export const FORGE = 6;
export const FORK = 7;
export const RELIC = 8;
export const BOSS = 9;
export const A_DEFAULT = 0;
export const A_STRIKE = 1;
export const A_GUARD = 2;
export const A_DODGE = 3;
export const A_POTION = 4;
export const A_SPRINT = 5;
export const A_REST = 6;
export const A_RIGHT = 7;
export const A_RALLY = 7;
export const COST = [0, 2, 1, 2, 0, 3, 0, 3];
export const ST_BALANCED = 0;
export const ST_AGGRESSIVE = 1;
export const ST_GUARDED = 2;
export const ST_EVASIVE = 3;
export const STANCES = [[4, 4, 1, 12], [5, 6, 2, 20], [3, 4, 0, 0], [4, 3, 1, 8]];
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

// tile class -> display name, in the order the class ordinal is derived (see TILE_CUTS)
export const TILE_NAMES = ["road", "monster", "elite", "hazard", "cache", "shrine", "forge", "fork", "relic", "boss"];
export const RANKS = [[60, "commoner"], [180, "apprentice"], [450, "journeyman"], [1100, "knight"], [2600, "banneret"], [6000, "lord"], [14000, "baron"], [32000, "duke"], [75000, "king"], [170000, "emperor"], [400000, "demigod"], [1099511627776, "creator"]];
