"""Test dell'integrazione con Claude via copia e incolla (risposte di esempio salvate)."""

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

import engine
from claude_bridge import (
    HEADER, RESPONSE_FORMAT, ResponseError, analysis_prompt, changes_table, extraction_prompt, parse_response,
)
from datasources.builder import plausibility_warnings
from datasources.cache import SourceCache
from parser import parse_match_input
from prediction_log import PredictionLog, SaveInfo, prediction_rows
from test_parser import VALID

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures" / "claude"


def _sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def test_valid_response_is_parsed_with_sources_and_comment():
    response = parse_response(_sample("valida.txt"))
    assert response.preamble.startswith("Il Napoli ha due titolari")
    assert response.confidence == "media" and "formazioni" in response.comment
    goals = response.corrections["gol_casa"]
    assert goals.applied == pytest.approx(0.96) and goals.source == "https://www.esempio.it/napoli-squalificati"
    assert response.corrections["corner"].accepted  # 1.00 senza fonte: nessuna modifica, ammessa
    adjustment = response.adjustment()
    assert adjustment == engine.ClaudeAdjustment(goals_home=0.96, goals_away=1.04, corners=1.0, cards=1.10)
    # Media dell'arbitro con lo shrinkage della fase D: (23·5.2 + 10·4.5) / 33.
    assert response.referee_yellow(4.5) == pytest.approx((23 * 5.2 + 10 * 4.5) / 33)
    assert response.warnings == []


def test_incomplete_response_keeps_only_valid_lines():
    response = parse_response(_sample("incompleta.txt"))
    assert not response.corrections["arbitro_gialli_medi"].accepted  # manca il numero di partite
    assert "partite" in response.corrections["arbitro_gialli_medi"].note
    assert not response.corrections["cartellini"].accepted and "senza fonte" in response.corrections["cartellini"].note
    assert response.adjustment() is None and response.referee_yellow(4.5) is None
    assert response.confidence is None and any("Confidenza" in warning for warning in response.warnings)


def test_out_of_range_values_are_clipped_or_rejected():
    response = parse_response(_sample("fuori_limite.txt"))
    applied = {key: correction.applied for key, correction in response.corrections.items()}
    assert applied["gol_casa"] == 1.10 and applied["gol_ospite"] == 0.90
    assert applied["corner"] == 1.10 and applied["cartellini"] == 0.85
    assert "limitata da 1.4 a 1.1" in response.corrections["gol_casa"].note
    assert applied["arbitro_gialli_medi"] is None and "fuori scala" in response.corrections["arbitro_gialli_medi"].note


def test_corrections_without_sources_are_ignored():
    response = parse_response(_sample("senza_fonti.txt"))
    assert not response.corrections["gol_casa"].accepted
    assert not response.corrections["gol_ospite"].accepted  # «sito di statistiche» non è un link
    assert not response.corrections["cartellini"].accepted and "non numerico" in response.corrections["cartellini"].note
    assert response.adjustment() is None  # resta solo il corner a 1.00: nessuna modifica
    states = {row["Campo"]: row["Stato"] for row in changes_table(response)}
    assert "senza fonte" in states["Gol attesi casa (dopo l'ancoraggio al mercato)"]


def test_missing_header_and_duplicates():
    with pytest.raises(ResponseError):
        parse_response("Nessun blocco qui.")
    response = parse_response(f"{HEADER}\ncorner: 1.05 | fonte: https://a.it\ncorner: 1.08 | fonte: https://b.it\nvarie: x")
    assert response.corrections["corner"].applied == pytest.approx(1.05)
    assert any("ripetuto" in warning for warning in response.warnings)
    assert any("ignorata" in warning for warning in response.warnings)


def _config(**changes):
    config = engine.config_from_input(parse_match_input(VALID), simulations=30_000, seed=5)
    return replace(config, **changes)


def test_claude_goal_factors_apply_after_the_market_blend():
    odds = {"1": 1.9, "X": 3.5, "2": 4.2}
    base = _config(odds=odds)
    adjusted = replace(base, claude=engine.ClaudeAdjustment(goals_home=0.95, goals_away=1.05, corners=1.1, cards=0.9))
    lam, mu, details = engine.final_goal_rates(base)
    lam_c, mu_c, details_c = engine.final_goal_rates(adjusted)
    assert (lam_c, mu_c) == pytest.approx((lam * 0.95, mu * 1.05))  # moltiplicazione piena, non attenuata dal mercato
    assert details_c["claude"]["lambda_before"] == pytest.approx(lam)
    home, away = engine.corner_signals(base)
    assert engine.corner_signals(adjusted) == pytest.approx((home * 1.1, away * 1.1))
    assert engine.card_total_mean(adjusted) == pytest.approx(engine.card_total_mean(base) * 0.9)


def test_analysis_prompt_contains_instructions_inputs_probabilities_and_format():
    result = engine.simulate_match(_config(odds={"1": 1.9, "X": 3.5, "2": 4.2, "Over 2.5 gol": 1.8, "Under 2.5 gol": 2.0}))
    sources = [{"Soggetto": "Inter", "Campo": "Elo", "Valore": "1835", "Fonte": "ClubElo",
                "Aggiornato": "21/10/2026", "Ultima partita inclusa": "18/10/2026"}]
    prompt = analysis_prompt(VALID, result, sources=sources, match_date="25/10/2026", competition="Serie A")
    for expected in ("formazioni", "squalifiche", "Turnover", "Arbitro designato", "coppe europee", "meteo",
                     "Incoerenze", "CASA: Inter", "ClubElo (agg. 21/10/2026", "1X2:", "Multigol:", "Primo tempo:",
                     "Corner: media", "Cartellini (punti: giallo 1, rosso 2", "mercato λ", "finali λ", RESPONSE_FORMAT):
        assert expected in prompt, expected


def test_extraction_prompt_produces_parser_compatible_instructions():
    prompt = extraction_prompt("Napoli", "Roma")
    assert prompt.startswith("Partita: Napoli (casa) - Roma (ospite).")
    assert "NON inventarlo" in prompt and "[INCOLLA QUI IL TESTO COPIATO DAL SITO]" in prompt
    # Un blocco come quello richiesto passa parser e controllo di plausibilità.
    block = """CASA: Napoli
Attacco: 1.31 | Difesa: 1.46 | Elo: 1826 | Forma: L-W-D-W-L | xG Fatti: 1.79 | xG Subiti: 0.99 | Corner pro/sub: 5.9/3.6 | Cartellini pro: 1.6
# Fonti: sito esempio, 21/10/2026

OSPITE: Roma
Attacco: 1.59 | Difesa: 1.44 | Elo: 1858 | Forma: W-W-D-D-W | xG Fatti: 2.08 | xG Subiti: 1.03 | Corner pro/sub: 4.9/3.9 | Cartellini pro: 1.72

ARBITRO: Gialli medi 4.4 | Falli medi 24

QUOTE_MERCATI_PRINCIPALI:
Quota 1: 2.30 | Quota X: 3.30 | Quota 2: 3.20 | Quota Over 2.5: 2.05 | Quota Under 2.5: 1.80
"""
    assert parse_match_input(block).odds["1"] == pytest.approx(2.30)
    assert plausibility_warnings(block) == []


def test_registry_stores_probabilities_before_and_after_claude(tmp_path):
    config = _config(odds={"1": 1.9, "X": 3.5, "2": 4.2})
    before = engine.simulate_match(config)
    after = engine.simulate_match(replace(config, claude=engine.ClaudeAdjustment(goals_home=0.9)))
    info = SaveInfo(date(2026, 10, 25), "20:45", "Serie A", "A carta", "test")
    rows = prediction_rows(before, ["1", "X", "2"], info, claude=after, odds=config.odds)
    one = next(row for row in rows if row["Selezione"] == "1")
    assert one["Prob_Claude"] < one["Prob_modello"] and one["Quota_presa"] == 1.9
    assert one["Prob_finale"] == one["Prob_Claude"]
    log = PredictionLog(SourceCache(tmp_path / "c.sqlite", opener=lambda *args: b""))
    log.save(rows, "sessione-1")
    log.save(prediction_rows(before, ["Over 2.5 gol"], info), "sessione-2")
    stored = log.rows("sessione-1")
    assert len(stored) == len(rows) and stored[0]["Prob_Claude"] is not None
    assert all(row["Prob_Claude"] is None for row in log.rows("sessione-2"))
