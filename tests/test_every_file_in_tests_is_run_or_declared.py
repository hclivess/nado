"""EVERY FILE IN tests/ IS A TEST THE RUNNER RUNS, OR IS DECLARED HERE AS SOMETHING ELSE — so a test can never again
silently fall out of the run.

Found 2026-10-10: 24 test files — eleven contract tests, eleven engine/wallet .mjs tests, a PoSW cross-check, an OTC
order-book test — were named *_test.* or *_crosscheck.*, so scripts/run_tests.sh's test_* glob never ran them, and the
three CommonJS wallet tests (test_*.js) matched no glob at all. Two of them had gone red unnoticed (a stale source pin
in test_zbill_delivery.js; a sovereign engine test that predated the game's own bank cap). A test that is not run is
not a test: it reads as coverage while covering nothing.

So, for every entry in tests/:
  - a file named test_*.py / test_*.mjs / test_*.js is a test, and the runner's default pattern takes all three;
  - anything else must be in DECLARED below as one of
        library  — driven by a test (the test that drives it must name it, checked here),
        suite    — a test the runner runs BY NAME (kept under its name because CI / the hook / docs call it by it),
        tool     — run by hand or by a script: a simulator, a bot, a verifier CLI, a page driven over CDP that needs
                   a browser and a served page, or a LIVE end-to-end against the running node,
        data     — fixtures, vectors, lists;
  - a declared file must exist, and say why (no dead line that hides nothing);
  - a test_* file of any other kind (test_x.sh, test_x.ts) is refused: nothing would run it.

Run: python3 tests/test_every_file_in_tests_is_run_or_declared.py
"""
import os, re, sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
RUN = re.compile(r"^test_[A-Za-z0-9_]+\.(py|mjs|js)$")

DRIVEN_BY_ROOT_SCRIPT = "a verifier/bot CLI called by the root-level e2e and faucet scripts (_faucet_rewards.py, _*_e2e.py)"
DECLARED = {
    # ---- libraries: imported or spawned by a test
    "__init__.py": ("library", "package marker: lets tests import each other's helpers"),
    "_attest_fixtures.py": ("library", "device-attestation fixtures for the test_device_attest_* tests"),
    "autogame_action_matrix.py": ("library", "the action matrix test_autogame_contract_matches_the_reference_model drives"),
    "autogame_engine_verify.mjs": ("library", "the browser-engine leg of test_autogame_contract_matches_the_reference_model"),
    "autogame_model.py": ("library", "the readable reference model the autogame contract is diffed against"),
    "bankedgame_scoreboard_test.mjs": ("library", "the JS leg of test_game_clients_compute_what_the_contracts_pay"),
    "beacon_client_cache.mjs": ("library", "the JS leg of test_exec_beacon_reaches_the_game_client"),
    "farkle_client_rolls_the_contracts_dice.mjs": ("library", "the JS leg of test_farkle_client_rolls_the_contracts_dice"),
    "joinsplit2_js_crosscheck.mjs": ("library", "the JS prover leg of test_joinsplit2_js_proof_verifies_in_python"),
    "joinsplit3_js_crosscheck.mjs": ("library", "the JS prover leg of test_joinsplit3_js_proof_verifies_in_python"),
    "protocol_hook.mjs": ("library", "Node resolve hook mapping /protocol.js to the rendered module for the .mjs tests"),
    "joinsplit2_js_crosscheck.sh": ("library", "driven by test_joinsplit2_js_proof_verifies_in_python"),
    "joinsplit3_js_crosscheck.sh": ("library", "driven by test_joinsplit3_js_proof_verifies_in_python"),
    "starkjs_crosscheck.sh": ("library", "driven by test_stark_js_prover_matches_python"),
    "mutation_check.py": ("library", "the mutation harness test_tests_can_fail drives"),
    "opcode_programs.py": ("library", "one program per zkVM opcode, for test_every_opcode_is_provable / _settles_natively"),
    "pets_js_crosscheck.mjs": ("library", "the JS leg of test_game_clients_compute_what_the_contracts_pay"),
    "pets_js_crosscheck_gen.py": ("library", "vector generator for test_game_clients_compute_what_the_contracts_pay"),
    "pets_ref.py": ("library", "the pets reference model pets_js_crosscheck_gen.py builds vectors from"),
    "posw_xlang.mjs": ("library", "the browser leg of test_posw_js_and_python_agree"),
    "roulette_and_dice_previews_equal_the_paid_result.mjs": ("library", "the JS leg of test_roulette_and_dice_previews_equal_the_paid_result"),
    "scrapline_sim_lab.mjs": ("library", "the combat sim test_scrapline_engine_referee imports"),
    "shielded_js_crosscheck.mjs": ("library", "the JS leg of test_shielded_js_matches_the_pool"),
    "shielded_js_crosscheck_gen.py": ("library", "vector generator for test_shielded_js_matches_the_pool"),
    "stormhold_bot.mjs": ("library", "the move generator the stormhold engine tests play with"),
    # ---- suite: run by scripts/run_tests.sh by name
    "i18n_coverage.mjs": ("suite", "every wallet key in all 16 languages; CLAUDE.md, the pre-push hook, CI and the wallet skill call it by name"),
    "selftest_vectors_crosscheck.mjs": ("suite", "Python <-> JS parity over the wallet's self-test vectors; CI calls it by name"),
    # ---- tools: by hand, by a script, or against something live
    "assets_ui_e2e.mjs": ("tool", "drives the wallet's Assets tab over CDP: needs chromium and a node serving /static"),
    "pool_ui_e2e.mjs": ("tool", "drives the Pool page over CDP: needs chromium and a served page"),
    "stormhold_ui_e2e.mjs": ("tool", "drives the live Stormhold page over CDP: needs chromium and the live site"),
    "autogame_ui_test.py": ("tool", "real clicks in a headless browser against a running page (default: the public site)"),
    "msg_ratchet_e2e.mjs": ("tool", "LIVE: posts real envelopes through the running node's message pool with dedicated test accounts"),
    "autogame_art_render.mjs": ("tool", "renders the art module to PNG contact sheets for a human to look at"),
    "autogame_balance.py": ("tool", "the autogame economy simulator, kept for retuning (prints a report, asserts nothing)"),
    "pets_balance_sim.py": ("tool", "the Monte-Carlo tuner that froze the pets battle constants (prints a report)"),
    "pets_economy_sim.py": ("tool", "the pets economy simulation: which stocks run away (prints a report)"),
    "autogame_daily_play.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "autogame_daily_verify.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "battleship_daily_verify.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "board_daily_verify.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "hamster_daily_verify.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "hexholm_daily_play.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "hexholm_daily_verify.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "hexholm_next_move.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "pool_next_move.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "scrapline_next_move.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    "stormhold_next_move.mjs": ("tool", DRIVEN_BY_ROOT_SCRIPT),
    # ---- data
    "ci_exclude.txt": ("data", "the tests CI's per-push job moves to the native job, each with its reason"),
    "fixtures": ("data", "attestation and certificate fixtures"),
    "vectors": ("data", "cross-language test vectors"),
}
KINDS = {"library", "suite", "tool", "data"}
IGNORED = {"__pycache__"}            # interpreter cache, never tracked


def entries(d=TESTS):
    # INVARIANT: an EMPTY directory is skipped, because git cannot track one — it is a leftover in one checkout (the live
    # node's tests/helpers, empty since 2026-09-10, refused the rel4 push), never something a push carries.
    return sorted(n for n in os.listdir(d) if n not in IGNORED and not n.startswith(".")
                  and not (os.path.isdir(os.path.join(d, n)) and not os.listdir(os.path.join(d, n))))


def classify(names, declared):
    """-> list of problems for this directory listing against the declarations."""
    bad = []
    for n in names:
        if RUN.match(n):
            continue
        if n.startswith("test_"):
            bad.append(f"{n}: named test_* but nothing runs a .{n.rsplit('.', 1)[-1]} test (the runner takes .py, .mjs, .js)")
        elif n not in declared:
            bad.append(f"{n}: neither a test_* file the runner picks up nor declared — rename it test_<property>.* "
                       f"if it is a test, or declare it here as library / suite / tool / data")
    for n, (kind, why) in declared.items():
        if n not in names:
            bad.append(f"{n}: declared but does not exist (a dead line hides nothing — remove it)")
        if kind not in KINDS or len(why.strip()) < 15:
            bad.append(f"{n}: declared without a kind in {sorted(KINDS)} and a reason")
    return bad


def drivers_name_their_libraries(declared):
    """A library is only a library if a test (or a library a test drives) names it — by file name, or by module name
    in a Python import — otherwise it is an orphaned test in disguise."""
    texts = {n: open(os.path.join(TESTS, n), encoding="utf-8", errors="replace").read()
             for n in os.listdir(TESTS) if (RUN.match(n) or declared.get(n, ("",))[0] == "library")
             and n != os.path.basename(__file__)}               # this file names every library: it proves nothing
    bad = []
    for n, (kind, _) in declared.items():
        if kind != "library" or n == "__init__.py":
            continue
        stem = n.rsplit(".", 1)[0]
        needles = [n] + ([f"import {stem}", f"from {stem} import", f"tests.{stem} import"] if n.endswith(".py") else [])
        # a same-stem sibling does not count (joinsplit2_js_crosscheck.mjs and .sh name each other; neither ran)
        if not any(nd in src for m, src in texts.items() if m.rsplit(".", 1)[0] != stem for nd in needles):
            bad.append(f"{n}: declared a library, but no test (or library a test drives) names it")
    return bad


def runner_runs_the_suite_entries(declared):
    src = open(os.path.join(ROOT, "scripts", "run_tests.sh")).read()
    pat = re.search(r"^PAT=\$\{1:-'([^']*)'\}", src, re.M)
    pat = pat.group(1).split() if pat else []
    bad = [f"scripts/run_tests.sh's default pattern does not take tests/test_*.{x}" for x in ("py", "mjs", "js")
           if f"tests/test_*.{x}" not in pat]
    bad += [f"{n}: declared suite, but scripts/run_tests.sh's default pattern does not name it"
            for n, (kind, _) in declared.items() if kind == "suite" and f"tests/{n}" not in pat]
    return bad


def self_check():
    """The detectors must fire on what they exist to catch, or a green run means nothing."""
    assert RUN.match("test_a.py") and RUN.match("test_b.mjs") and RUN.match("test_c.js")
    assert not RUN.match("foo_test.py") and not RUN.match("test_x.sh")
    names = ["test_ok.py", "foo_test.py", "test_bad.sh", "lib.py"]
    got = classify(names, {"lib.py": ("library", "a helper some test imports"), "gone.mjs": ("tool", "a tool that was deleted")})
    assert any(g.startswith("foo_test.py") for g in got), got          # an orphaned test
    assert any(g.startswith("test_bad.sh") for g in got), got          # a test of a kind nothing runs
    assert any(g.startswith("gone.mjs") for g in got), got             # a dead declaration
    assert not any(g.startswith(("test_ok.py", "lib.py")) for g in got), got
    assert classify(["x.py"], {"x.py": ("library", "")}), "a declaration without a reason must fail"


if __name__ == "__main__":
    self_check()
    import tempfile as _tf
    _d = _tf.mkdtemp(prefix="nado-test-entries-")
    os.makedirs(os.path.join(_d, "leftover")); os.makedirs(os.path.join(_d, "full")); open(os.path.join(_d, "full", "x"), "w").close()
    _e = entries(_d)
    assert _e == ["full"], f"an empty leftover directory is not an entry; a non-empty one is: {_e}"
    bad = classify(entries(), DECLARED) + drivers_name_their_libraries(DECLARED) + runner_runs_the_suite_entries(DECLARED)
    for b in bad:
        print("FAIL  " + b)
    print("ALL PASS — every file in tests/ is run, or declared as a library, suite entry, tool or data" if not bad
          else f"{len(bad)} FAILURES")
    sys.exit(1 if bad else 0)
