"""Quote Eurobet incollate: i 3 esempi reali in tests/fixtures/eurobet danno i valori attesi."""

from pathlib import Path

import pytest

import engine
import eurobet
from market_catalog import event_keys, normalize_market_label
from parser import parse_match_input


FIXTURES = Path(__file__).parent / "tests" / "fixtures" / "eurobet"
MAIN = (FIXTURES / "eurobet_principali_cartellini.txt").read_text(encoding="utf-8")
MULTIGOL = (FIXTURES / "eurobet_multigol.txt").read_text(encoding="utf-8")
CORNER = (FIXTURES / "eurobet_corner.txt").read_text(encoding="utf-8")


def find(paste, section, selection, line=None):
    matches = [quote for quote in paste.quotes if quote.section == section and quote.selection.lower() == selection.lower()
               and (line is None or quote.line == line)]
    assert len(matches) == 1, (section, selection, line, matches)
    return matches[0]


@pytest.fixture(scope="module")
def main():
    return eurobet.parse_eurobet(MAIN)


def test_main_page_goal_lines_and_suspended_selections(main):
    odds = main.odds()
    assert (odds["Over 2.5 gol"], odds["Under 2.5 gol"]) == (2.15, 1.62)
    assert (odds["1"], odds["X"], odds["2"]) == (2.90, 2.90, 2.70)
    assert (odds["Goal"], odds["No Goal"], odds["1X"]) == (1.80, 1.92, 1.43)
    under, over = find(main, "U/O GOAL", "UNDER", "5.5"), find(main, "U/O GOAL", "OVER", "5.5")
    assert under.price is None and under.status == eurobet.SUSPENDED
    assert over.price == 16.50 and over.status == eurobet.NOT_SIMULATED  # nessun campo Over 5.5 gol
    assert find(main, "U/O GOAL", "OVER", "6.5").price == 30.00          # nessuno slittamento della quota
    assert "Over 5.5 gol" not in odds and "Under 4.5 gol" in odds


def test_first_half_combos_and_duplicates(main):
    odds = main.odds()
    assert (odds["1 1T"], odds["X 1T"], odds["Over 1.5 gol 1T"], odds["Goal 1T"]) == (3.45, 1.97, 3.05, 4.90)
    assert (odds["1 + Over 2.5"], odds["X2 + Under 3.5"]) == (4.90, 1.75)
    # Lo stesso mercato in un'altra sezione (SCOMMESSE TOP e U/O GOAL) è un doppione: vale la prima quota.
    assert find(main, "U/O GOAL", "OVER", "2.5").status == eurobet.DUPLICATE
    assert find(main, "X2 + U/O", "1 + OVER", "1.5").status == eurobet.DUPLICATE
    assert find(main, "GG/NG + U/O", "GG + OVER", "2.5").status == eurobet.NOT_SIMULATED


def test_handicap_quote_glued_to_the_next_title(main):
    assert find(main, "1X2 HANDICAP", "2", "0:2").price == 1.11
    assert find(main, "1X2 HANDICAP", "2", "0:2").status == eurobet.NOT_SIMULATED
    assert main.combo_sections["U/O CARTELLINI"] is True
    assert find(main, "U/O CARTELLINI", "Under", "3.5").price == 1.82


def test_cards_markets_and_team_lines(main):
    odds = main.odds()
    assert (odds["Under 3.5 cartellini"], odds["Over 3.5 cartellini"]) == (1.82, 1.75)
    assert (odds["1 cartellini"], odds["X cartellini"], odds["2 cartellini"]) == (2.25, 4.20, 2.20)
    assert odds["Casa Over 1.5 cartellini"] == 1.63 and odds["Ospite Under 2.5 cartellini"] == 1.28
    assert find(main, "U/O CARTELLINI SQ.", "OVER", "sq.1 - 0.5").status == eurobet.NOT_SIMULATED  # linea 0.5 fuori catalogo
    assert find(main, "TOT. CARTELLINI", ">11").price == 65.00
    assert find(main, "U/O CARTELLINI TEMPO", "OVER", "2t - 3.5").price == 3.85
    assert find(main, "ENTRAMBE ALMENO X CARTELLINI", "NO", "3").price is None


def test_section_decides_the_meaning_of_one_two(main):
    multigol = eurobet.parse_eurobet(MULTIGOL)
    assert find(multigol, "MULTIGOL", "Si", "1-2").market == "Multigol 1-2"
    assert find(main, "RISULTATO ESATTO XL", "1-2").market == "1-2" and main.exact()["1-2"] == 10.00
    half_full = find(main, "1T/FINALE", "1-2")
    assert half_full.price == 30.00 and half_full.status == eurobet.NOT_SIMULATED
    groups = main.exact()
    assert groups["1-0/2-0/3-0"] == 5.40 and groups["1-5/2-3/2-4/3-4"] == 24.00  # gruppo nel formato del registro
    assert find(main, "RIS. ESATTO A GRUPPI", "SQ.1 ALTRO").status == eurobet.NOT_SIMULATED


def test_multigol_page():
    paste = eurobet.parse_eurobet(MULTIGOL)
    odds = paste.odds()
    assert odds["Multigol Casa 2-3"] == 3.00 and odds["Multigol Ospite 3-5"] == 6.80 and odds["Multigol 3-6"] == 2.15
    zero = find(paste, "MULTIGOL", "Si", "0-0")
    assert zero.price == 7.80 and zero.status == eurobet.NOT_SIMULATED
    assert find(paste, "MULTIGOL", "No", "0-0").price is None
    # «0-3 / Si / No / 13.50»: il Sì è sospeso, la quota resta al No.
    assert find(paste, "MULTIGOL 2T", "Si", "0-3").price is None and find(paste, "MULTIGOL 2T", "No", "0-3").price == 13.50
    assert find(paste, "MULTIGOL CASA + OSPITE", "SI", "0-3 + 0-3").price is None
    assert (odds["2 + Multigol 1-2"], odds["1 + Multigol 2-4"]) == (5.20, 4.50)
    assert find(paste, "1X + MULTIGOL", "1X + MULTIGOL", "1-2").status == eurobet.NOT_SIMULATED
    assert {"MULTIGOL", "MULTIGOL CASA", "MULTIGOL OSPITE"} == {s for s, flag in paste.combo_sections.items() if flag}


def test_corner_page_and_full_ladder_for_anchoring():
    paste = eurobet.parse_eurobet(CORNER)
    odds = paste.odds()
    assert (odds["Under 9.5 corner"], odds["Over 9.5 corner"]) == (1.58, 2.10)
    assert (odds["1 corner"], odds["Casa Over 4.5 corner"]) == (2.10, 1.98)
    assert paste.combo_sections["U/O CORNER"] is True and paste.combo_sections["TOTALE CORNER"] is False
    ladder = paste.count_lines("corner")
    assert sorted({float(key.split()[1]) for key in ladder}) == [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]
    assert "Over 5.5 corner" not in odds and ladder["Over 5.5 corner"] == 1.08
    assert find(paste, "TOT. CORNER", "12+").price == 3.75 and not paste.unknown_sections
    assert find(paste, "CORNER MINUTO", "SI", "0:00 - 29:59").price is None
    assert eurobet.format_margin(paste.margins()["U/O CORNER"]) == "10,5%"


def test_pages_in_any_order_commas_and_case():
    together = eurobet.parse_eurobet("\n".join([CORNER, MULTIGOL, MAIN]))
    reverse = eurobet.parse_eurobet("\n".join([MAIN, MULTIGOL, CORNER]))
    assert together.odds() == reverse.odds()
    assert set(eurobet.parse_eurobet(CORNER).odds()) <= set(together.odds())
    text = "u/o goal\ncombo builder\n2,5\nunder\n1,62\nover\n2,15\nMULTIGOL CASA\n1-2\nsi\n1,55\nNO\n2,15"
    paste = eurobet.parse_eurobet(text)
    assert paste.odds() == {"Under 2.5 gol": 1.62, "Over 2.5 gol": 2.15, "Multigol Casa 1-2": 1.55}
    assert paste.combo_sections["u/o goal"] is True


def test_unknown_sections_are_listed_never_invented():
    paste = eurobet.parse_eurobet("SEZIONE NUOVA\nSI\n2.00\nNO\n1.70\nU/O GOAL\n2.5\nUNDER\n1.62\nOVER\n2.15\n"
                                  "ALTRA SEZIONE STRANA\nQUALCOSA\n3.10")
    assert paste.unknown_sections == ["SEZIONE NUOVA", "ALTRA SEZIONE STRANA"]
    assert paste.odds() == {"Under 2.5 gol": 1.62, "Over 2.5 gol": 2.15}
    orphan = eurobet.parse_eurobet("U/O GOAL\n2.5\n1.62\nOVER\n2.15")
    assert orphan.odds() == {"Over 2.5 gol": 2.15} and orphan.unrecognized_lines
    rows = eurobet.table_rows(orphan)
    assert rows[-1]["Stato"] == eurobet.UNRECOGNIZED


def test_only_existing_fields_and_parser_block_still_valid(main):
    odds = main.odds()
    assert set(odds) <= event_keys()
    teams = ("CASA: Napoli\nAttacco: 1.2 | Difesa: 1.1 | Elo: 1850 | Forma: W-W-D-W-L | xG Fatti: 1.8 | xG Subiti: 1.0 | "
             "Corner pro/sub: 5.5/4.0 | Cartellini pro: 2.0\nOSPITE: Roma\nAttacco: 1.1 | Difesa: 1.2 | Elo: 1800 | "
             "Forma: W-D-W-W-L | xG Fatti: 1.5 | xG Subiti: 1.1 | Corner pro/sub: 5.0/4.5 | Cartellini pro: 2.2\n"
             "ARBITRO: Gialli medi 4.2 | Falli medi 24\nQUOTE_MERCATI_PRINCIPALI\n")
    block = teams + "\n".join(f"Quota {key}: {price}" for key, price in odds.items())
    assert parse_match_input(block).odds == {normalize_market_label(key): price for key, price in odds.items()}


def test_apply_plan_asks_before_replacing_existing_quotes(main):
    plan = eurobet.apply_plan(main, {"1": 2.80, "X": 2.90, "Over 2.5 gol": 0.0})
    assert plan["conflicts"] == {"1": 2.90}
    assert plan["fill"]["X"] == 2.90 and plan["fill"]["Over 2.5 gol"] == 2.15 and "1" not in plan["fill"]


def test_combo_builder_flag_limits_combined_bets(main):
    combinable = main.combinable()
    assert {"Over 2.5 gol", "Goal", "1X", "Over 3.5 cartellini", "1 cartellini"} <= combinable
    assert "1 + Over 2.5" not in combinable and "1 1T" not in combinable  # sezioni senza «Combo Builder»
    assert eurobet.combo_allowed(["1X", "Over 3.5 cartellini"], combinable)
    assert not eurobet.combo_allowed(["1X", "Casa Over 1.5 cartellini"], combinable) and not eurobet.combo_allowed([], combinable)


def test_anchor_sources_sharp_for_goals_eurobet_ladder_for_counts(main):
    corner = eurobet.parse_eurobet(CORNER + "\n" + MAIN)
    odds = corner.odds()
    sharp = {"1": 2.75, "X": 3.10, "2": 2.80, "Over 2.5 gol": 2.05, "Under 2.5 gol": 1.80}
    anchor, sources = eurobet.anchor_odds(odds, sharp, corner)
    assert anchor["1"] == 2.75 and anchor["Over 2.5 gol"] == 2.05 and sources["gol"].startswith("quota sharp")
    assert anchor["Over 5.5 corner"] == 1.08 and anchor["Under 4.5 cartellini"] == 1.33
    assert sources["corner"] == "scala Eurobet (7 linee)" and sources["cartellini"] == "scala Eurobet (3 linee)"
    no_sharp, sources = eurobet.anchor_odds(odds, None, corner)
    assert no_sharp["1"] == 2.90 and sources["gol"] == "Eurobet senza margine"
    plain, sources = eurobet.anchor_odds({"1": 2.0, "X": 3.0, "2": 4.0, "Over 8.5 corner": 1.9, "Under 8.5 corner": 1.9})
    assert plain == {"1": 2.0, "X": 3.0, "2": 4.0, "Over 8.5 corner": 1.9, "Under 8.5 corner": 1.9}
    assert sources["corner"] == "quote dei campi"


def test_engine_ev_on_eurobet_anchor_on_sharp_and_full_ladder():
    paste = eurobet.parse_eurobet(CORNER + "\n" + MAIN)
    odds = paste.odds()
    sharp = {"1": 2.60, "X": 3.20, "2": 2.95}
    anchor, _ = eurobet.anchor_odds(odds, sharp, paste)
    team = lambda name, elo: engine.TeamParams(name, 1.1, 1.0, elo, "W-D-W-L-W", 1.5, 1.2, 5.5, 4.5, 2.0)
    base = engine.MatchConfig(team("Napoli", 1850), team("Roma", 1800), 4.4, 24.0, odds=odds, simulations=20_000)
    config = engine.MatchConfig(**{**base.__dict__, "anchor_odds": anchor})
    assert engine.final_goal_rates(config)[2]["anchoring"]["market"] == engine.market_goal_rates(
        sharp, config.market_anchor.devig_method, config.dixon_coles_rho)
    corner = engine.count_anchoring(config)["corner"]
    assert corner["active"] and [line["linea"] for line in corner["lines"]] == [5.5, 6.5, 7.5, 8.5, 9.5, 10.5, 11.5]
    assert len(engine.count_anchoring(base)["corner"]["lines"]) == 5  # senza anchor_odds: solo i campi (7.5-11.5)
    result = engine.simulate_match(config)
    financial = {row["market"]: row for row in result["financial"]["markets"]}
    assert financial["1"]["odds"] == 2.90 and financial["Over 9.5 corner"]["odds"] == 2.10  # EV sulla quota Eurobet
    # Senza anchor_odds il motore resta quello di prima.
    assert engine.final_goal_rates(base)[:2] == engine.final_goal_rates(engine.MatchConfig(**{**base.__dict__, "anchor_odds": None}))[:2]


def test_api_event_markets_skip_corners_and_cards_already_pasted(main):
    markets = ["alternate_totals_corners", "alternate_totals_cards", "btts"]
    assert eurobet.skip_event_markets(main, markets) == ["alternate_totals_corners", "btts"]
    both = eurobet.parse_eurobet(CORNER + "\n" + MAIN)
    assert eurobet.skip_event_markets(both, markets[:2]) == []
    assert eurobet.skip_event_markets(None, markets) == markets


def test_same_section_from_two_pages_keeps_its_margin():
    single = eurobet.parse_eurobet(CORNER).margins()["1X2 CORNER + 1X2 CARTELLINI"]
    both = eurobet.parse_eurobet(CORNER + "\n" + MAIN).margins()["1X2 CORNER + 1X2 CARTELLINI"]
    assert both == pytest.approx(single) and eurobet.format_margin(single) == "25,1%"
