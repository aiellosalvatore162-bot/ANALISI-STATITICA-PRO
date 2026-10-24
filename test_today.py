"""Pagina Oggi e costruttore di multiple (fase S): solo logica, nessuna rete."""

from datetime import date, datetime, timezone
import math

import numpy as np
import pandas as pd
import pytest

import multiples
import today
from claude_bridge import ResponseError
from datasources.builder import MatchSheet, TEAM_FIELDS
from datasources.stats import FieldValue, missing
from performance import fill_from_results, settle_multiples


DAY = date(2026, 10, 25)
SETTINGS = multiples.load_settings()
TEAMS = [("Napoli", "Roma"), ("Inter", "Milan"), ("Lazio", "Torino"), ("Atalanta", "Bologna"), ("Juventus", "Genoa"),
         ("Fiorentina", "Lecce"), ("Udinese", "Cagliari"), ("Parma", "Como"), ("Verona", "Empoli"), ("Monza", "Sassuolo"),
         ("Arsenal", "Chelsea"), ("Liverpool", "Everton"), ("Real Madrid", "Getafe"), ("Bayern", "Mainz")]


def field(value):
    return FieldValue(value, "fixture", datetime(2026, 10, 24, tzinfo=timezone.utc))


def fake_build(values=None, *, drop=None):
    """Sostituto di DataProvider.build: scheda completa, oppure con un campo mancante."""
    def build(home, away, *, match_date=None, competition=None):
        team = {"attack": 1.2, "defense": 1.1, "elo": 1820, "form": "W-D-W-L-W", "xg_for": 1.6, "xg_against": 1.1,
                "corners": "5.4/4.6", "cards_for": 2.0, **(values or {})}
        home_fields = {key: field(team[key]) for key, _ in TEAM_FIELDS}
        away_fields = {key: field({**team, "elo": 1760}[key]) for key, _ in TEAM_FIELDS}
        if drop:
            home_fields[drop] = missing("non trovato")
        return MatchSheet(home, away, match_date, competition, home_fields, away_fields,
                          {"yellow": field(4.3), "fouls": field(24.0)})
    return build


def odds_fields(odds):
    return {key: field(value) for key, value in odds.items()}


MAIN_ODDS = {"1": 2.05, "X": 3.40, "2": 3.70, "Over 2.5 gol": 1.90, "Under 2.5 gol": 1.92, "Over 1.5 gol": 1.28,
             "Goal": 1.75, "No Goal": 2.05, "Over 8.5 corner": 1.62, "Under 10.5 corner": 1.35, "Over 3.5 cartellini": 1.55,
             "Under 5.5 cartellini": 1.40, "1X": 1.30, "Multigol 2-4": 1.85}


def match(index, home="Napoli", away="Roma"):
    return today.TodayMatch(f"ev{index}", "soccer_italy_serie_a", "Serie A",
                            datetime(2026, 10, 25, 18, 0, tzinfo=timezone.utc), home, away)


@pytest.fixture(scope="module")
def analyses():
    result = []
    for index, (home, away) in enumerate(TEAMS):
        odds = {key: round(value * (1 + 0.01 * (index % 4)), 2) for key, value in MAIN_ODDS.items()}
        result.append(today.analyze(match(index, home, away), fake_build(), odds_fields(odds), simulations=4_000,
                                    competition="Serie A", settings=SETTINGS))
    return result


def test_analyze_simulates_and_skips_missing_data_without_inventing(analyses):
    assert all(analysis.ok for analysis in analyses) and analyses[0].odds["1"] == 2.05
    assert analyses[0].block.startswith("CASA: Napoli") or "CASA: Napoli" in analyses[0].block
    skipped = today.analyze(match(99), fake_build(drop="xg_for"), odds_fields(MAIN_ODDS), simulations=2_000)
    assert not skipped.ok and skipped.skipped.startswith("dati mancanti") and "xG Fatti" in skipped.skipped
    def broken(*args, **kwargs):
        raise ConnectionError("rete assente")
    failed = today.analyze(match(98), broken, odds_fields(MAIN_ODDS), simulations=2_000)
    assert not failed.ok and "rete assente" in failed.skipped


def test_observer_flags_are_small_bounded_and_noted(analyses):
    factors = today.observer_adjustment(["partita aperta"], SETTINGS)
    assert factors["gol_casa"] == 1.04 and factors["corner"] == 1.03
    stacked = today.observer_adjustment(["partita aperta", "turnover ospite", "turnover ospite"], SETTINGS)
    assert stacked["gol_casa"] == 1.07 and stacked["gol_ospite"] == pytest.approx(1.04 * 0.95 * 0.95)  # limite 0.93-1.07
    analysis = today.Analysis(analyses[0].match, analyses[0].block, dict(analyses[0].odds), analyses[0].config)
    before = today.simulate(analysis, settings=SETTINGS).result["model"]["lambda"]
    after = today.simulate(analysis, flags=["turnover casa"], settings=SETTINGS).result["model"]["lambda"]
    assert after == pytest.approx(before * 0.95, rel=1e-6)
    assert analysis.note() == "segnalazione: turnover casa"
    with pytest.raises(ValueError, match="non prevista"):
        today.observer_adjustment(["pioggia"], SETTINGS)


def test_value_picks_respect_the_market_threshold_and_explain_why(analyses):
    picks = today.value_picks(analyses, SETTINGS)
    assert picks == sorted(picks, key=lambda pick: pick.ev, reverse=True)
    for pick in picks:
        assert pick.ev >= today.ev_threshold(pick.selection, SETTINGS)
        assert pick.reason.startswith("Il simulatore dà") and f"{pick.odds:.2f}" in pick.reason
    strict = {**SETTINGS, "soglie_ev": {key: 1000.0 for key in SETTINGS["soglie_ev"]}}
    assert today.value_picks(analyses, strict) == []


def test_one_claude_text_for_all_matches_and_blocks_by_id(analyses):
    ids = today.match_ids(analyses[:3])
    prompt = today.multi_analysis_prompt(analyses[:3], [0, 2], day=DAY)
    assert "=== P1 · Napoli - Roma" in prompt and "=== P3 · Lazio - Torino" in prompt and "P2 ·" not in prompt
    answer = ("Napoli senza il portiere.\nCORREZIONI_CLAUDE: P1\ngol_casa: 0.85 | motivo: assenze | fonte: https://esempio.it/a\n"
              "corner: 1.05 | motivo: pioggia\nconfidenza: media\n"
              "CORREZIONI_CLAUDE: P3\ngol_ospite: 1.04 | motivo: rientri | fonte: https://esempio.it/b\n"
              "CORREZIONI_CLAUDE: P9\ngol_casa: 1.1 | fonte: https://x.it\n")
    responses, warnings = today.parse_multi_response(answer, ids)
    assert set(responses) == {0, 2}
    assert responses[0].corrections["gol_casa"].applied == 0.90           # limite della fase G
    assert not responses[0].corrections["corner"].accepted                # senza fonte: ignorata
    assert responses[2].adjustment().goals_away == 1.04
    assert any("P9" in warning for warning in warnings) and any("P2" in warning for warning in warnings)
    with pytest.raises(ResponseError):
        today.parse_multi_response("nessun blocco", ids)


def test_candidate_legs_use_joint_probability_not_the_product(analyses):
    analysis = analyses[0]
    legs = multiples.candidate_legs("m0", analysis.match.label, analysis.result, analysis.odds)
    combo = next(leg for leg in legs if leg.selections == ("Over 2.5 gol", "Over 8.5 corner"))
    final = analysis.result["components"]["finale"]
    assert combo.probability == pytest.approx(analysis.result["joint_pairs"]["Over 2.5 gol & Over 8.5 corner"] / 100)
    assert combo.probability <= min(final["Over 2.5 gol"], final["Over 8.5 corner"]) / 100
    assert combo.estimated_odds and combo.odds == pytest.approx(analysis.odds["Over 2.5 gol"] * analysis.odds["Over 8.5 corner"], abs=1e-3)
    assert all(multiples._family(a) != multiples._family(b) for leg in legs if leg.kind == "combo builder"
               for a, b in [leg.selections])
    only = multiples.candidate_legs("m0", analysis.match.label, analysis.result, analysis.odds,
                                    combinable={"Over 2.5 gol", "Over 8.5 corner", "1"})
    assert {leg.selections for leg in only if leg.kind == "combo builder"} == {("Over 2.5 gol", "Over 8.5 corner")}


def pool(analyses, combinable=None):
    return [leg for index, analysis in enumerate(analyses)
            for leg in multiples.candidate_legs(f"m{index}", analysis.match.label, analysis.result, analysis.odds, combinable)]


def test_traps_are_excluded_and_reported(analyses):
    legs = pool(analyses)
    filtered = multiples.filter_legs(legs, trap_ev=-5.0, min_odds=1.20)
    assert all(leg.ev * 100 >= -5.0 for leg in filtered.kept) and all(leg.ev * 100 < -5.0 for leg in filtered.traps)
    assert all(leg.odds >= 1.20 for leg in filtered.kept) and len(filtered.kept) + len(filtered.traps) + len(filtered.below_min) == len(legs)


def test_long_multiple_has_five_combos_on_distinct_matches(analyses):
    legs = multiples.filter_legs(pool(analyses), trap_ev=-5.0, min_odds=1.20).kept
    long = multiples.build_long(legs, total=12, combos=5, objective="probabilità", bonus_pct=10.0)
    assert len(long.legs) == 12 and sum(leg.kind == "combo builder" for leg in long.legs) == 5
    assert len({leg.match_id for leg in long.legs}) == 12
    assert long.probability == pytest.approx(math.prod(leg.probability for leg in long.legs))
    assert long.odds == pytest.approx(long.base_odds * 1.10) and long.ev == pytest.approx(long.probability * long.odds - 1)
    assert long.sentence() == f"passa circa 1 volta su {round(1 / long.probability)}"
    value = multiples.build_long(legs, total=12, combos=5, objective="valore", bonus_pct=10.0)
    assert value.ev >= long.ev and long.probability >= value.probability
    # Scelta esatta: nessuna sostituzione singola migliora la probabilità.
    for index, leg in enumerate(long.legs):
        alternatives = [other for other in legs if other.match_id == leg.match_id and other.kind == leg.kind]
        assert leg.probability == pytest.approx(max(other.probability for other in alternatives))
    few = multiples.build_long(legs[:40], total=12, combos=5)
    assert few.warnings and len({leg.match_id for leg in few.legs}) == len(few.legs)


def test_short_singles_doubles_and_manual_replacement(analyses):
    legs = multiples.filter_legs(pool(analyses), trap_ev=-5.0, min_odds=1.20).kept
    short = multiples.build_short(legs, 4)
    assert len(short.legs) == 4 and all(leg.kind == "singola" for leg in short.legs)
    assert len({leg.match_id for leg in short.legs}) == 4
    doubles = multiples.build_doubles(legs)
    assert len(doubles) == 3 and all(len({leg.match_id for leg in double.legs}) == 2 for double in doubles)
    other = next(leg for leg in legs if leg.match_id == short.legs[0].match_id and leg != short.legs[0])
    replaced = short.with_leg(0, other)
    assert replaced.legs[0] == other and replaced.probability == pytest.approx(math.prod(l.probability for l in replaced.legs))
    with pytest.raises(ValueError, match="già in un'altra gamba"):
        short.with_leg(0, next(leg for leg in legs if leg.match_id == short.legs[1].match_id))
    negative = multiples.Multiple("x", [multiples.Leg("a", "A - B", ("1",), 0.5, 1.8)])
    assert any("negativo" in warning for warning in negative.leg_warnings())


def registry_frame(rows):
    frame = pd.DataFrame(rows)
    frame["Data"] = DAY
    frame["Note"] = frame["Note"].fillna("")
    frame["_riga"] = range(2, 2 + len(frame))
    frame["Esito"] = frame["Esito"].astype(float)
    return frame


def test_multiple_row_and_automatic_outcome_from_the_legs():
    legs = [multiples.Leg("a", "Napoli - Roma", ("1",), 0.5, 2.0),
            multiples.Leg("b", "Inter - Milan", ("Over 2.5 gol", "Over 9.5 corner"), 0.3, 3.5, estimated_odds=True)]
    multiple = multiples.Multiple("Doppia", legs, bonus_pct=5.0)
    row = multiples.multiple_row(multiple, day=DAY, time="20:45", competition="", kind="A carta", version="test")
    assert row["Mercato"] == "Multipla" and row["Selezione"] == "Napoli - Roma: 1 | Inter - Milan: Over 2.5 gol & Over 9.5 corner"
    assert row["Prob_finale"] == 0.15 and row["Quota_presa"] == pytest.approx(7.35) and "bonus 5%" in row["Note"]
    assert multiples.parse_selection(row["Selezione"]) == [("Napoli - Roma", ["1"]), ("Inter - Milan", ["Over 2.5 gol", "Over 9.5 corner"])]
    singles = [{"ID": f"s{i}", "Partita": match, "Selezione": selection, "Mercato": "x", "Esito": outcome, "Note": ""}
               for i, (match, selection, outcome) in enumerate([("Napoli - Roma", "1", 1.0), ("Inter - Milan", "Over 2.5 gol", 1.0),
                                                                ("Inter - Milan", "Over 9.5 corner", np.nan)])]
    frame = registry_frame([*singles, {**row, "Esito": np.nan}])
    assert pd.isna(settle_multiples(frame).frame.iloc[-1]["Esito"])        # una gamba senza esito
    frame.loc[2, "Esito"] = 1.0
    report = settle_multiples(frame)
    assert report.frame.iloc[-1]["Esito"] == 1.0 and "esito multipla" in report.frame.iloc[-1]["Note"]
    frame.loc[0, "Esito"] = 0.0
    assert settle_multiples(frame).frame.iloc[-1]["Esito"] == 0.0
    assert fill_from_results(frame, pd.DataFrame(columns=["date", "home_team", "away_team"])).not_found == []


def test_claude_outcome_check_fills_cup_corners_and_cards_with_source():
    rows = [{"ID": "c1", "Partita": "Napoli - Bodø/Glimt", "Selezione": "Over 9.5 corner", "Mercato": "Corner",
             "Competizione": "Champions League", "Esito": np.nan, "Note": "", "Quota_chiusura": np.nan},
            {"ID": "c2", "Partita": "Napoli - Bodø/Glimt", "Selezione": "Over 4.5 cartellini", "Mercato": "Cartellini",
             "Competizione": "Champions League", "Esito": np.nan, "Note": "", "Quota_chiusura": np.nan},
            {"ID": "c3", "Partita": "Inter - Shakhtar", "Selezione": "Under 9.5 corner", "Mercato": "Corner",
             "Competizione": "Champions League", "Esito": np.nan, "Note": "", "Quota_chiusura": np.nan},
            {"ID": "g1", "Partita": "Inter - Shakhtar", "Selezione": "Goal", "Mercato": "Goal/NoGoal",
             "Competizione": "Champions League", "Esito": np.nan, "Note": "", "Quota_chiusura": np.nan}]
    frame = registry_frame(rows)
    targets = today.outcome_targets(frame)
    assert [target["match"] for target in targets] == ["Inter - Shakhtar", "Napoli - Bodø/Glimt"]
    prompt = today.outcome_prompt(targets)
    assert "E1 · Inter - Shakhtar" in prompt and "ESITI_CLAUDE: E1" in prompt
    answer = ("ESITI_CLAUDE: E2\nrisultato: 4-1\ncorner: 7-4\ngialli: 2-2\nrossi: 0-1\nfonte: https://www.uefa.com/match\n"
              "ESITI_CLAUDE: E1\nrisultato: 1-1\ncorner: 5-3\n")
    results, warnings = today.parse_outcomes(answer, targets)
    assert len(results) == 1 and any("senza fonte" in warning for warning in warnings)
    filled = frame
    for result in results:
        filled = fill_from_results(filled, pd.DataFrame([result]), source=f"Claude ({result['source']})",
                                   today=DAY).frame
    by_id = filled.set_index("ID")
    assert by_id.loc["c1", "Esito"] == 1.0 and by_id.loc["c2", "Esito"] == 1.0   # 11 corner; 4 gialli + 1 rosso = 6 punti
    assert "https://www.uefa.com/match" in by_id.loc["c1", "Note"]
    assert pd.isna(by_id.loc["c3", "Esito"])                                        # E1 senza fonte: ignorato
