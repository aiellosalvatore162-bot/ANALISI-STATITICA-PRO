"""Fase Q: schede tattiche, incroci di stile, cambio allenatore, reazioni, nuovi mercati e goleade (senza rete)."""

from dataclasses import replace
from datetime import date

import numpy as np
import pandas as pd
import pytest

import dashboard
import engine
import tactical_sheets
import timeline
from datasources.stats import CoachChange, team_match_rows, team_profile
from engine import config_from_input, simulate_match
from parser import parse_match_input
from prediction_log import SaveInfo, prediction_rows
from tactical_sheets import (
    TacticalSheet, contrasts, crossing_adjustment, data_hints, match_effects, matchup_text, parse_profiles, profile_prompt,
    prompt_lines, reaction_factors, upsert,
)
from test_engine import VALID
from today import combined_adjustment

ANSWER = """Ecco i profili.

PROFILO_TATTICO: Napoli
allenatore: Antonio Conte | dal: 05/06/2024 | precedente: Francesco Calzona
modulo: 4-3-3 | alternativo: 3-5-2
transizione: 4 | gestione_blocco_basso: buona
non_possesso: zona | blocco: alto | pressing: alto
fasce_cross: medio
adattabilita: media
contro_forti: aspetta e riparte | contro_deboli: assedia l'area
se_in_svantaggio: attacca con più uomini | se_in_vantaggio: si chiude e gestisce
fonte: https://www.esempio.it/napoli-tattica | fonte: https://altro.it/conte
confidenza: alta

**PROFILO_TATTICO: Roma**
transizione: 9
blocco: altissimo | pressing: basso
non_possesso: uomo
fonte: https://www.esempio.it/roma

PROFILO_TATTICO: Lazio
blocco: basso
"""

RULES = {
    "limiti": [0.90, 1.12],
    "regole": [
        {"id": "a", "nome": "Verticale contro blocco alto", "attiva": True,
         "condizione": {"attacco": {"transizione": [4, 5]}, "difesa": {"blocco": ["alto"]}}, "effetto": {"gol": 1.10}},
        {"id": "b", "nome": "Fasce contro uomo", "attiva": False,
         "condizione": {"attacco": {"fasce_cross": ["alto"]}, "difesa": {"non_possesso": ["uomo"]}}, "effetto": {"corner": 1.3}},
    ],
    "reazioni": {"passo": 0.1},
    "cambio_allenatore": {"peso_partite_precedenti": 0.3, "partite_per_fidarsi": 8},
}


def test_profiles_are_parsed_tolerantly_and_need_a_source():
    sheets, warnings = parse_profiles(ANSWER)
    assert [sheet.team for sheet in sheets] == ["Napoli", "Roma"]
    napoli, roma = sheets
    assert (napoli.transizione, napoli.blocco, napoli.pressing, napoli.non_possesso) == (4, "alto", "alto", "zona")
    assert napoli.dal == "2024-06-05" and napoli.coach_since() == date(2024, 6, 5) and napoli.allenatore == "Antonio Conte"
    assert napoli.modulo == "4-3-3" and napoli.alternativo == "3-5-2" and napoli.adattabilita == "media"
    assert napoli.fonti == ["https://www.esempio.it/napoli-tattica", "https://altro.it/conte"]
    assert napoli.origine == "Claude (da confermare)"
    # Valori fuori elenco scartati, il resto resta; il blocco senza link è scartato per intero.
    assert roma.transizione is None and roma.blocco is None and roma.pressing == "basso" and roma.non_possesso == "uomo"
    assert any("transizione «9»" in warning for warning in warnings)
    assert any("blocco «altissimo»" in warning for warning in warnings)
    assert any("Lazio: nessuna fonte" in warning for warning in warnings)
    assert parse_profiles("niente")[0] == []


def test_prompt_lists_teams_with_data_hints_and_the_format():
    hints = data_hints({"pressing": 80, "block_height": 20, "build_up": 10, "transitions": 90})
    assert hints == {"pressing": "alto", "blocco": "basso", "transizione": "5"}
    prompt = profile_prompt(["Napoli", "Roma"], {"Napoli": hints})
    assert "- Napoli (indizi dai dati: pressing alto, blocco basso, transizione 5)" in prompt and "- Roma" in prompt
    assert "PROFILO_TATTICO: <squadra>" in prompt and "fonte: https://" in prompt


def test_contrasts_warn_but_never_change_the_sheet():
    sheet = TacticalSheet("Napoli", transizione=1, blocco="alto", pressing="medio")
    warnings = contrasts(sheet, {"blocco": "basso", "pressing": "alto", "transizione": "5"})
    assert len(warnings) == 2 and "blocco «alto»" in warnings[0] and "transizione 1" in warnings[1]
    assert sheet.blocco == "alto" and sheet.transizione == 1


def test_matchup_text_follows_the_elo_of_the_opponent():
    sheet = TacticalSheet("Napoli", contro_forti="aspetta", contro_deboli="assedia")
    assert matchup_text(sheet, 1800, 1900) == "contro un avversario più forte: aspetta"
    assert matchup_text(sheet, 1900, 1800) == "contro un avversario più debole: assedia"
    assert matchup_text(TacticalSheet("X"), 1, 2) == ""


def test_crossing_uses_only_active_rules_scaled_by_adaptability_and_bounded():
    home = TacticalSheet("Napoli", transizione=5, fasce_cross="alto", adattabilita="alta")
    away = TacticalSheet("Roma", transizione=2, blocco="alto", non_possesso="uomo")
    factors, notes = crossing_adjustment(home, away, settings=RULES)
    # Adattabilità alta: metà dell'effetto (1 + 0.10 × 0.5); la regola spenta non conta.
    assert factors == {"gol_casa": pytest.approx(1.05), "gol_ospite": 1.0, "corner": 1.0, "cartellini": 1.0}
    assert len(notes) == 1 and "attenuata" in notes[0]
    every, _ = crossing_adjustment(replace(home, adattabilita="bassa"), away, settings=RULES, only_active=False)
    assert every["gol_casa"] == pytest.approx(1.10) and every["corner"] == pytest.approx(1.12)  # 1.3 tagliato al limite
    assert crossing_adjustment(home, None, settings=RULES)[0]["gol_casa"] == 1.0


def test_shipped_rules_are_bounded_and_switched_by_the_verification():
    settings = tactical_sheets.load_rules()
    low, high = settings["limiti"]
    assert (low, high) == (0.90, 1.12)
    for rule in settings["regole"]:
        assert all(low <= value <= high for value in rule["effetto"].values())
        assert "valore_da" in rule and isinstance(rule["attiva"], bool)


def test_reactions_are_read_from_the_text():
    sheet = TacticalSheet("Napoli", se_in_svantaggio="attacca con più uomini", se_in_vantaggio="si chiude e gestisce")
    assert reaction_factors(sheet, RULES) == (pytest.approx(1.1), pytest.approx(0.9))
    assert reaction_factors(TacticalSheet("X"), RULES) == (1.0, 1.0) and reaction_factors(None) == (1.0, 1.0)


def test_reactions_change_the_minute_engine_only_for_the_team_and_state():
    params = timeline.TimelineParams(state={s: (1.0,) * 4 for s in timeline.STATES}).with_components(("gol_stato",))
    inputs = dict(lambda_=1.5, mu=1.2, first_share_home=0.45, first_share_away=0.45, corner_home=5.0, corner_away=4.5,
                  corner_dispersion=50.0, yellow_mean=4.0, card_dispersion=13.0, red_mean=0.2, card_share=0.5)

    def trailing_ratio(reactions):
        out = timeline.sample(np.random.default_rng(5), 60_000, params=replace(params, reactions=reactions), **inputs)
        second = out["goals_home"] - out["first_home"]
        behind = out["first_home"] < out["first_away"]
        level = out["first_home"] == out["first_away"]
        return second[behind].mean() / second[level].mean()

    assert trailing_ratio((1.4, 1.0, 1.0, 1.0)) > trailing_ratio((1.0, 1.0, 1.0, 1.0)) * 1.15


def test_match_effects_find_sheets_and_feed_coach_change_and_timeline():
    sheets = upsert([], [TacticalSheet("SSC Napoli", dal="2026-09-01", se_in_svantaggio="spinge"),
                         TacticalSheet("Roma", blocco="alto")])
    effects = match_effects(sheets, "Napoli", "AS Roma", RULES)
    assert effects.any_sheet and effects.home.team == "SSC Napoli" and effects.away.team == "Roma"
    assert effects.reactions == (pytest.approx(1.1), 1.0, 1.0, 1.0)
    assert effects.coaches(RULES) == {"home": CoachChange(date(2026, 9, 1), 0.3, 8)}
    params = effects.timeline(timeline.TimelineParams())
    assert params.reactions == effects.reactions
    lines = prompt_lines(effects, (1850, 1800))
    assert lines[0].startswith("SCHEDE TATTICHE") and any("SSC Napoli" in line for line in lines)
    # Una nuova scheda della stessa squadra sostituisce la vecchia.
    updated = upsert(sheets, [TacticalSheet("Napoli", blocco="basso")])
    assert len(updated) == 2 and updated[-1]["blocco"] == "basso"
    assert not match_effects([], "Napoli", "Roma", RULES).any_sheet


def _league(new_coach_goals: int):
    rows = []
    for day in range(1, 21):
        when = pd.Timestamp(2026, 8, 1) + pd.Timedelta(days=3 * day)
        goals = 3 if when < pd.Timestamp(2026, 9, 20) else new_coach_goals
        rows.append({"date": when, "home_team": "Alfa", "away_team": "Beta" if day % 2 else "Gamma", "home_goals": goals,
                     "away_goals": 1})
        rows.append({"date": when, "home_team": "Beta" if day % 2 else "Gamma", "away_team": "Delta", "home_goals": 1,
                     "away_goals": 1})
    frame = pd.DataFrame(rows)
    for column in ("ht_goals", "corners", "yellows", "fouls", "xg_real", "sot", "shots"):
        for side in ("home", "away"):
            frame[f"{side}_{column}"] = 1.0
    frame["league"] = "I1"
    return team_match_rows(frame)


def test_coach_change_downweights_old_matches_and_shrinks_with_few_new_ones():
    rows = _league(new_coach_goals=0)
    as_of = date(2026, 10, 1)
    plain = team_profile("Alfa", rows, None, as_of=as_of, venue="home")
    changed = team_profile("Alfa", rows, None, as_of=as_of, venue="home", coach=CoachChange(date(2026, 9, 20)))
    assert changed.fields["attack"].value < plain.fields["attack"].value
    assert any("Allenatore nuovo da 4 partite" in warning for warning in changed.warnings)
    assert "allenatore dal 20/09/2026" in changed.fields["attack"].note
    # Allenatore in carica da prima di tutte le partite: stessi valori, nessun avviso.
    old = team_profile("Alfa", rows, None, as_of=as_of, venue="home", coach=CoachChange(date(2025, 1, 1)))
    assert old.fields["attack"].value == plain.fields["attack"].value
    assert not any("Allenatore nuovo" in warning for warning in old.warnings)
    weights = CoachChange(date(2026, 9, 20)).weights(rows[rows["team"] == "Alfa"])
    assert set(weights.round(2)) == {0.3, 1.0}


def test_combined_adjustment_multiplies_the_crossing_factors():
    adjustment = combined_adjustment([], None, tactical={"gol_casa": 1.05, "gol_ospite": 1.0, "corner": 0.95, "cartellini": 1.0})
    assert (adjustment.goals_home, adjustment.goals_away, adjustment.corners) == (pytest.approx(1.05), 1.0, pytest.approx(0.95))
    assert combined_adjustment([], None, tactical={"gol_casa": 1.0}) is None


def test_registry_note_says_whether_a_tactical_sheet_was_used():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=2000, seed=3))
    info = SaveInfo(date(2026, 10, 25), "20:45", "Serie A", "Giocata", "test", "confidenza Claude alta")
    assert prediction_rows(result, ["1"], info)[0]["Note"] == "confidenza Claude alta; motore: Calcolo attuale"
    result["tactical_sheet"] = True
    assert prediction_rows(result, ["1"], info)[0]["Note"] == "confidenza Claude alta; scheda tattica: sì; motore: Calcolo attuale"
    result["tactical_sheet"] = False
    assert prediction_rows(result, ["1"], replace(info, note=""))[0]["Note"] == "scheda tattica: no; motore: Calcolo attuale"


def test_today_analysis_passes_the_coach_change_to_the_data_layer():
    from datetime import datetime, timezone

    import today

    seen = {}

    def build(home, away, **kwargs):
        seen.update(kwargs)
        raise RuntimeError("solo per il test")

    match = today.TodayMatch("e1", "soccer_italy_serie_a", "Serie A", datetime(2026, 10, 25, 18, tzinfo=timezone.utc),
                             "Napoli", "Roma")
    analysis = today.analyze(match, build, {}, simulations=1000,
                             sheets=[TacticalSheet("Napoli", dal="2026-09-01").to_dict()])
    assert analysis.tactical.any_sheet and seen["coaches"]["home"].since == date(2026, 9, 1)
    seen.clear()
    today.analyze(match, build, {}, simulations=1000)
    assert "coaches" not in seen


# --- Nuovi mercati (6b) e goleade (6c) ---------------------------------------------------------------------

def test_new_markets_are_simulated_from_the_same_sample_and_coherent():
    config = config_from_input(parse_match_input(VALID), simulations=6000, seed=9)
    final = simulate_match(replace(config, v2=replace(config.v2, taratura=None)))["components"]["finale"]
    for key in ("Multigol 1T 1-2", "Multigol 2T 1-3", "Multigol Casa 1-2 + Ospite 0-1", "Over 5.5 gol", "Under 6.5 gol",
                "Goal + Over 2.5", "No Goal + Under 3.5", "2 + Under 1.5", "1X + Over 3.5", "Over 4.5 corner 1T",
                "Under 3.5 corner 2T", "1 corner 1T", "Over 1.5 cartellini 1T", "Over 3.5 cartellini 2T",
                "Casa Over 0.5 cartellini", "Corner totali 9-11", "Corner casa 7+", "Cartellini totali 4", "Cartellini casa 4+"):
        assert key in final, key
    assert final["Goal + Over 2.5"] <= min(final["Goal"], final["Over 2.5 gol"]) + 1e-9
    assert final["1X + Over 2.5"] == pytest.approx(final["1 + Over 2.5"] + final["X + Over 2.5"], abs=0.02)
    assert final["Over 4.5 corner 1T"] < final["Over 7.5 corner"]
    assert final["Over 5.5 gol"] + final["Under 5.5 gol"] == pytest.approx(100.0, abs=0.02)
    assert final["1 corner 1T"] + final["X corner 1T"] + final["2 corner 1T"] == pytest.approx(100.0, abs=0.05)


def test_goleada_line_reads_the_exact_scores_of_the_favourite():
    result = {"input": {"home": {"name": "Inter"}, "away": {"name": "Lecce"}}, "model": {"lambda": 2.4, "mu": 0.6},
              "exact_scores": {"finale": {"4-0": 10.0, "5-1": 5.0, "3-0": 20.0, "4-2": 4.0, "0-0": 61.0}}}
    data = dashboard.goleada(result)
    assert data == {"favorita": "Inter", "quattro": pytest.approx(19.0), "scarto": pytest.approx(35.0)}
    assert "Inter segna 4+ gol" in dashboard.goleada_line(result)


def test_performance_compares_selections_with_and_without_sheet():
    from performance import tactical_comparison

    frame = pd.DataFrame({"Prob_finale": [0.6, 0.6, 0.5, 0.7], "Esito": [1, 0, 1, None],
                          "Note": ["scheda tattica: sì", "x; scheda tattica: sì", "scheda tattica: no", "scheda tattica: no"]})
    table = tactical_comparison(frame).set_index("Gruppo")
    assert table.loc["con scheda tattica", "Selezioni"] == 2 and table.loc["senza scheda tattica", "Selezioni"] == 1
    assert table.loc["con scheda tattica", "Brier"] == pytest.approx((0.16 + 0.36) / 2)
