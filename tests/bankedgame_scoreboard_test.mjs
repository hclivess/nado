/*
 * BankedGame.scoreboard — the profit board every peer-banked game shows.
 *
 * Dice, roulette, mines and blackjack each carried a byte-identical copy of this walk and differed in one
 * line: how their payout rule turns a stake into a net. The walk now lives in bankedgame.js with the rule
 * as an argument, so these checks pin the part that was duplicated — especially the self-play rule, which
 * is the subtle one: a table's bank is credited the mirror of every player's net EXCEPT when the player IS
 * the bank, or testing your own table cancels your win against yourself to a bogus zero and the board
 * quietly under-reports you.
 *
 * Run:  node tests/bankedgame_scoreboard_test.mjs
 */
import { BankedGame } from "../static/bankedgame.js";

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL:", m); } };

// a minimal dapp — scoreboard() touches none of it, which is itself worth asserting
const bg = new BankedGame({ app: "Test", me: null }, { icon: "🎲" });

/** storage in the shape every banked contract exposes: gd settled · gg table · ga player · gs stake · ta bank */
const sto = (games) => {
  const gd = {}, gg = {}, ga = {}, gs = {}, ta = { T1: "alice", T2: "bob" };
  games.forEach((g, i) => {
    const id = "g" + i;
    gd[id] = g.settled ? 1 : 0; gg[id] = g.table; ga[id] = g.player; gs[id] = g.stake;
  });
  return { gd, gg, ga, gs, ta };
};
const byAddr = (board) => Object.fromEntries(board.map((r) => [r.addr, r.net]));

// --- a plain win: the player gains, the bank loses exactly the mirror -------------------------------
{
  const b = byAddr(bg.scoreboard(sto([{ settled: 1, table: "T1", player: "carol", stake: 100 }]),
                                 () => 250));
  ok(b.carol === 250, "the player is credited their net");
  ok(b.alice === -250, "the table's bank is debited the mirror");
}

// --- a loss: signs flip, and the bank is up ---------------------------------------------------------
{
  const b = byAddr(bg.scoreboard(sto([{ settled: 1, table: "T1", player: "carol", stake: 100 }]),
                                 (_g, stake) => -stake));
  ok(b.carol === -100, "a losing player is debited their stake");
  ok(b.alice === 100, "and the bank keeps it");
}

// --- SELF-PLAY: banking your own table and playing it must not cancel to zero -----------------------
{
  const b = byAddr(bg.scoreboard(sto([{ settled: 1, table: "T1", player: "alice", stake: 100 }]),
                                 () => 250));
  ok(b.alice === 250, "playing your own table records the win once, not win-plus-mirror = 0");
  ok(Object.keys(b).length === 1, "and does not invent a second entry for the same address");
}

// --- unsettled games contribute nothing -------------------------------------------------------------
{
  const board = bg.scoreboard(sto([{ settled: 0, table: "T1", player: "carol", stake: 100 }]), () => 999);
  ok(board.length === 0, "an unsettled game is not on the board at all");
}

// --- a game on a table with no bank is skipped rather than crashing ----------------------------------
{
  const board = bg.scoreboard(sto([{ settled: 1, table: "GONE", player: "carol", stake: 100 }]), () => 5);
  ok(board.length === 0, "a game whose table has no bank is skipped");
}

// --- the stake reaches the rule, and results accumulate across games ---------------------------------
{
  const seen = [];
  const b = byAddr(bg.scoreboard(sto([
    { settled: 1, table: "T1", player: "carol", stake: 10 },
    { settled: 1, table: "T1", player: "carol", stake: 40 },
    { settled: 1, table: "T2", player: "carol", stake: 25 },
  ]), (_g, stake) => { seen.push(stake); return stake; }));
  ok(JSON.stringify(seen) === "[10,40,25]", "each game's own stake is handed to the payout rule");
  ok(b.carol === 75, "a player's nets accumulate across tables");
  ok(b.alice === -50 && b.bob === -25, "each table's bank is debited only for its own games");
}

// --- the board is sorted best-first, which is what the UI relies on ----------------------------------
{
  const board = bg.scoreboard(sto([
    { settled: 1, table: "T1", player: "small", stake: 1 },
    { settled: 1, table: "T2", player: "big", stake: 100 },
  ]), (_g, stake) => stake);
  ok(board[0].addr === "big", "highest net first");
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
