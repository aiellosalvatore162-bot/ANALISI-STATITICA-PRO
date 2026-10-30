"""Fase AH: esiti unificati, parser profili unico, campi PARTITA nuovi, prior dei profili, contesto del motore."""

from dataclasses import fields
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

import analyst
import lineup as lu
import match_context as mc
import match_extras
import outcomes
import players as pl
import style_profile as sp
import tactical_sheets as ts
from claude_bridge import ResponseError
from test_lineup import KEY, WHEN, fake_matches
from test_style_profile import PROXY, raw_matches

FIXTURES = Path(__file__).parent / "tests" / "fixtures" / "analista"
REPORT_AH = (FIXTURES / "report_ah.md").read_text(encoding="utf-8")
REPORT_OLD = (FIXTURES / "report_completo.md").read_text(encoding="utf-8")


# --- Esiti unificati ----------------------------------------------------------------------------------------------------

def _csv(goals=(2, 1), corners=(6, 4)):
    return pd.DataFrame([{"date": "2026-10-26", "home_team": "Inter", "away_team": "Fiorentina", "home_goals": goals[0],
                          "away_goals": goals[1], "home_corners": corners[0], "away_corners": corners[1]}])


ESITO_TEXT = """ESITO: Internazionale - Fiorentina | Serie A | 26/10/2026 20:45
risultato: 2-1
corner: 6-4
gialli: 2-3
fonte: https://esempio.it/tabellino
"""


def test_csv_and_esito_make_one_record_and_conflicts_are_warnings():
    esito, warnings = outcomes.from_esito(analyst.parse_outcomes(ESITO_TEXT))
    assert warnings == []
    merged = outcomes.unify(outcomes.from_csv(_csv()), esito)
    assert len(merged.records) == 1 and merged.conflicts == []
    record = merged.records[0]
    assert record.origin == "CSV" and record.values["home_yellows"] == 2          # il campo mancante nel CSV viene dall'ESITO
    assert set(record.sources) == {"CSV", "ESITO"}
    different = outcomes.unify(outcomes.from_csv(_csv(corners=(7, 4))), esito)
    assert len(different.records) == 1 and different.records[0].values["home_corners"] == 7       # vince il CSV
    assert len(different.conflicts) == 1 and "home_corners" in different.warnings[0]
    assert different.conflicts[0].kept_origin == "CSV" and different.conflicts[0].discarded_origin == "ESITO"


def test_esiti_claude_text_is_still_accepted_and_has_the_lowest_priority():
    targets = [{"id": "E1", "date": pd.Timestamp("2026-10-26"), "match": "Inter - Fiorentina", "competition": "", "selections": []}]
    text = "ESITI_CLAUDE: E1\nrisultato: 3-1\ncorner: 6-4\nfonte: https://esempio.it/x\n"
    claude, warnings = outcomes.parse_esiti_claude(text, targets)
    assert warnings == [] and claude[0].origin == "ESITI_CLAUDE"
    esito, _ = outcomes.from_esito(analyst.parse_outcomes(ESITO_TEXT))
    merged = outcomes.unify(claude, esito)
    assert merged.records[0].values["home_goals"] == 2 and merged.conflicts[0].field == "home_goals"      # ESITO > ESITI_CLAUDE
    assert outcomes.lookup(merged, "Inter", "Fiorentina", "2026-10-27") is merged.records[0]
    assert outcomes.lookup(merged, "Inter", "Fiorentina", "2026-11-20") is None
    with pytest.raises(ResponseError):
        outcomes.parse_esiti_claude("niente", targets)
    assert outcomes.result_rows(merged)[0]["home_team"] == "Internazionale"


def test_today_parse_outcomes_delegates_with_the_same_shape():
    import today

    targets = [{"id": "E1", "date": pd.Timestamp("2026-10-26"), "match": "Inter - Fiorentina", "competition": "", "selections": []}]
    rows, warnings = today.parse_outcomes("ESITI_CLAUDE: E1\nrisultato: 3-1\nfonte: https://esempio.it/x\n", targets)
    assert rows[0]["home_goals"] == 3 and rows[0]["source"] == "https://esempio.it/x" and warnings == []


# --- Parser profili unico --------------------------------------------------------------------------------------------------

PROFILE_TEXT = """PROFILO_TATTICO: Genoa
transizione: 4 | blocco: alto | pressing: medio | adattabilita: alta | se_in_svantaggio: pressa alto | fonte: https://esempio.it/p
"""


def test_single_profile_parser_gives_the_same_fields_for_scheda_and_report():
    scheda, _ = ts.parse_profiles(PROFILE_TEXT)
    report, _ = analyst.parse_profiles(PROFILE_TEXT, date(2026, 10, 26))
    assert scheda[0].origine == "Claude (da confermare)" and report[0].origine == "Analista"
    assert report[0].aggiornata == "2026-10-26"
    for item in fields(ts.TacticalSheet):
        if item.name not in ("origine", "aggiornata"):
            assert getattr(scheda[0], item.name) == getattr(report[0], item.name)


# --- Campi nuovi di PARTITA -----------------------------------------------------------------------------------------------------

def test_new_fields_are_read_and_malformed_ones_discarded_with_a_warning():
    block = analyst.parse_report(REPORT_AH)[0]
    extras = block.extras
    assert [(item.side, item.player, item.role, item.weight) for item in extras.absent] == [
        ("casa", "Giocatore Esterno Uno", "ATT", 0.12), ("ospite", "Giocatore Esterno Due", "DIF", match_extras.MAX_WEIGHT)]
    assert extras.rest_days == {"casa": 3, "ospite": 7} and extras.turnover["casa"][0] is True and extras.turnover["ospite"][0] is False
    assert any("riga scartata" in message and "ALA" in message for message in extras.warnings)
    assert any("esorbitante" in message for message in extras.warnings)                        # 0.50 riportato a 0.35
    bad = match_extras.parse_extras("RIPOSO:\ncasa: 99 | ospite: x | fonte: https://a.it\nTURNOVER:\ncasa: forse | fonte: https://a.it\n"
                                    "ASSENTI_PESATI:\ncasa: Tizio | ruolo: ATT | peso: 0.1\n")
    assert not bad and len(bad.warnings) == 4 and bad.rest_days == {}


def test_old_report_gives_the_same_result_as_before():
    plain = analyst.parse_report(REPORT_OLD)
    assert all(not block.extras for block in plain)
    with_fields = analyst.parse_report(REPORT_AH)[0]
    without = analyst.parse_report(REPORT_AH[:REPORT_AH.index("ASSENTI_PESATI:")] + REPORT_AH[REPORT_AH.index("CORREZIONI_CLAUDE:"):])[0]
    assert with_fields.corrections_text == without.corrections_text and with_fields.comment == without.comment
    assert with_fields.response.absent == without.response.absent
    assert {k: v.applied for k, v in with_fields.response.corrections.items()} == {k: v.applied for k, v in without.response.corrections.items()}
    assert not without.extras


def test_swapped_teams_swap_the_extras():
    block = analyst.parse_report(REPORT_AH)[0]
    swapped = block.extras.swapped()
    assert swapped.rest_days == {"ospite": 3, "casa": 7} and swapped.absent[0].side == "ospite"


# --- Assenti pesati e turnover con l'AL: nessuna doppia conta -----------------------------------------------------------------

@pytest.fixture()
def player_store():
    return pl.PlayerStore(pl.rows_from_matches(fake_matches(), "I1"), config={**pl.load_config(), "fattore_attacco": {"limiti": None, "esponente": 1.0}})


def test_absent_known_to_understat_and_in_assenti_pesati_counts_once(player_store):
    once = lu.team_lineup(player_store, "I1", KEY, WHEN, absent=[{"nome": "Bomber Rossi", "fonte": "https://x.it"}])
    both = lu.team_lineup(player_store, "I1", KEY, WHEN, absent=[{"nome": "Bomber Rossi", "fonte": "https://x.it"}],
                          extra_absent=[{"nome": "Bomber Rossi", "peso": 0.2, "fonte": "https://y.it"}])
    assert both["fattore_attacco"]["valore_grezzo"] == pytest.approx(once["fattore_attacco"]["valore_grezzo"])
    assert both["assenti_esterni"] == [] and len(both["assenti"]) == 1
    only_report = lu.team_lineup(player_store, "I1", KEY, WHEN, extra_absent=[{"nome": "Bomber Rossi", "peso": 0.2, "fonte": "https://y.it"}])
    assert only_report["fattore_attacco"]["valore_grezzo"] == pytest.approx(once["fattore_attacco"]["valore_grezzo"])   # noto a Understat: vale Understat
    external = lu.team_lineup(player_store, "I1", KEY, WHEN, extra_absent=[{"nome": "Giocatore Fuori Understat", "peso": 0.2, "fonte": "https://y.it"}])
    assert external["fattore_attacco"]["valore_grezzo"] == pytest.approx(0.8)
    assert external["assenti_esterni"][0]["peso"] == 0.2


def test_turnover_lowers_the_expected_xi_strength(player_store):
    matches = fake_matches()
    for match in matches:
        for player in match["players"]:
            if player["position"] == "Sub":
                player["xG"] = player["xA"] = "0"            # panchina senza produzione: ruotare costa
    store = pl.PlayerStore(pl.rows_from_matches(matches, "I1"), config={**player_store.config, "k_minuti": {r: 1.0 for r in pl.ROLES}})
    base = lu.team_lineup(store, "I1", KEY, WHEN)
    rotated = lu.team_lineup(store, "I1", KEY, WHEN, turnover=True)
    assert rotated["turnover"]["rotazioni"] == 3 and "Understat" in rotated["turnover"]["fonte"]
    assert rotated["fattore_attacco"]["valore_grezzo"] < base["fattore_attacco"]["valore_grezzo"] == pytest.approx(1.0)


def test_apply_report_context_fills_rest_only_when_calendar_is_missing(player_store):
    import today
    from dataclasses import replace
    import engine
    from parser import parse_match_input
    from test_engine import VALID

    block = analyst.parse_report(REPORT_AH)[0]
    match = today.TodayMatch("e1", "soccer_italy_serie_a", "Serie A", datetime(2026, 10, 26, 18, tzinfo=timezone.utc), "Inter", "Fiorentina")
    config = engine.config_from_input(parse_match_input(VALID), simulations=1000)
    missing = today.Analysis(match=match, config=config)
    today.apply_report_context(missing, block)
    assert missing.config.rest_days == (3, 7) and missing.extras is block.extras
    with_calendar = today.Analysis(match=match, config=replace(config, rest_days=(5, 4)))
    today.apply_report_context(with_calendar, block)
    assert with_calendar.config.rest_days == (5, 4)             # vale il calendario
    nothing = today.Analysis(match=match, config=config)
    today.apply_report_context(nothing, None)
    assert nothing.config is config and nothing.extras is None


# --- Prior, profilo e contesto --------------------------------------------------------------------------------------------------

def test_prior_blend_n0_gives_the_prior_and_large_n_gives_the_data():
    value, weight, origin = mc.blend(12.0, 0, 8.0, 8.0)
    assert value == 8.0 and weight == 0.0 and "prior" in origin
    value, weight, _ = mc.blend(12.0, 800, 8.0, 8.0)
    assert value == pytest.approx(12.0, abs=0.05) and weight > 0.98
    assert mc.blend(12.0, 8, 8.0, 8.0)[0] == pytest.approx(10.0)                   # n = k: metà e metà
    assert mc.blend(12.0, 5, None, 8.0)[0] == 12.0                                  # senza prior stimato vale il dato
    assert mc.blend(None, 0, None, 8.0)[0] is None


def test_every_report_field_is_absorbed_or_marked_informative():
    expected = {item.name for item in fields(ts.TacticalSheet)} | set(match_extras.SECTIONS) | {"CORREZIONI_CLAUDE", "CHIAVI_MATCH", "FORMA"}
    assert expected <= set(mc.FIELD_STATUS)
    assert {status for status, _ in mc.FIELD_STATUS.values()} == {mc.ABSORBED, mc.INFORMATIVE}
    assert all(how for _, how in mc.FIELD_STATUS.values())


@pytest.fixture()
def style_store():
    return sp.StyleStore(sp.build_table(raw_matches(), None, PROXY))


def _rows(*sheets):
    return ts.upsert([], list(sheets))


def test_context_runs_without_any_report_and_with_one(style_store):
    when = pd.Timestamp("2026-02-01")
    bare = mc.match_context("Alfa", "Beta", when, league="I1", style_store=style_store, elo=(1700.0, 1500.0))
    assert bare["casa"]["profilo"] == [] and bare["casa"]["stile"]["forma_reale"]["valore"] is not None
    assert bare["incroci"]["note"] == [] and bare["riposo"] == {"casa": None, "ospite": None}
    assert set(bare["casa"]["etichette"]) == {"forma", "territorio", "pressing"}
    sheet = ts.TacticalSheet(team="Alfa", transizione=4, blocco="alto", pressing="alto", non_possesso="zona", fasce_cross="medio",
                             adattabilita="alta", contro_deboli="gioca più diretto", se_in_svantaggio="alza il pressing", dal="2026-01-20",
                             fonti=["https://esempio.it/p"], origine="Analista")
    block = analyst.parse_report(REPORT_AH)[0]
    full = mc.match_context("Alfa", "Beta", when, league="I1", style_store=style_store, sheets=_rows(sheet), extras=block.extras,
                            response=block.response, elo=(1700.0, 1500.0), calendar_rest=(None, None))
    profile = {item["campo"]: item for item in full["casa"]["profilo"]}
    assert profile["pressing"]["parametro"] == "ppda" and profile["transizione"]["parametro"] == "deep"
    assert profile["blocco"]["prior"] is None and profile["blocco"]["dato"] is None        # niente Understat nei dati sintetici
    assert full["casa"]["adattabilita"]["sposta_verso"] == "contro_deboli" and full["casa"]["reazioni"]["se_in_svantaggio"] > 1.0
    assert full["casa"]["cambio_allenatore"]["dal"] == "2026-01-20"
    assert full["riposo"]["casa"]["giorni"] == 3 and "report" in full["riposo"]["casa"]["origine"]
    assert full["turnover"]["casa"][0] is True and any("scartata" in m for m in full["avvisi"])
    assert full["correzioni_claude"][0]["chiave"] == "gol_casa"
    rows = mc.absorbed_rows(full)
    assert {row["Stato"] for row in rows} <= {mc.ABSORBED, mc.INFORMATIVE} and any(row["Campo"] == "pressing" for row in rows)


def test_context_without_style_data_degrades_with_a_warning():
    context = mc.match_context("Alfa", "Beta", pd.Timestamp("2026-02-01"))
    assert context["casa"]["stile"] is None and any("stile misurato non disponibile" in m for m in context["avvisi"])


def test_prior_estimation_needs_the_minimum_sample(style_store):
    from tools import stile_prior

    sheets = [{"team": team, "non_possesso": "zona"} for team in ("Alfa", "Beta")]
    few = stile_prior.estimate(sheets, style_store, "I1", pd.Timestamp("2026-02-01"))
    assert few["prior"]["non_possesso"]["zona"] is None            # 2 squadre < 5: nessun valore inventato
    many = stile_prior.estimate([{"team": team, "non_possesso": "zona"} for team in ("Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta")],
                                style_store, "I1", pd.Timestamp("2026-02-01"))
    assert many["prior"]["non_possesso"]["zona"] is not None and many["squadre"] == 6
