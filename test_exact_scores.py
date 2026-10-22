"""Test dei risultati esatti e dei gruppi (fase I): stesso campione della simulazione, nessuna rete."""

import numpy as np
import pytest

import engine
from exact_scores import (
    coherence, coherence_summary, correlation, group_probability, group_scores, group_selection, group_value, is_group,
    minimum_group, parse_score, score_only_markets, score_table, settle_group,
)
from parser import parse_match_input
from test_parser import VALID

DISTRIBUTION = {"1-0": 20.0, "1-1": 15.0, "2-0": 12.0, "2-1": 10.0, "0-0": 9.0, "0-1": 8.0, "3-0": 6.0, "2-2": 5.0,
                "3-1": 5.0, "0-2": 4.0, "4-0": 3.0, "1-2": 3.0}


@pytest.fixture(scope="module")
def result():
    config = engine.config_from_input(parse_match_input(VALID), simulations=50_000, seed=9)
    return engine.simulate_match(engine.MatchConfig(**{**config.__dict__, "odds": {"1": 1.9, "X": 3.5, "2": 4.2}}))


def test_engine_exact_scores_come_from_the_same_sample(result):
    finale = result["exact_scores"]["finale"]
    assert sum(finale.values()) == pytest.approx(100.0, abs=0.05)
    assert list(finale.values()) == sorted(finale.values(), reverse=True)
    home_wins = sum(value for score, value in finale.items() if parse_score(score)[0] > parse_score(score)[1])
    assert home_wins == pytest.approx(result["components"]["finale"]["1"], abs=0.02)
    under = sum(value for score, value in finale.items() if sum(parse_score(score)) < 3.5)
    assert under == pytest.approx(result["components"]["finale"]["Under 3.5 gol"], abs=0.02)
    # Con le quote l'ancoraggio è attivo: modello e mercato hanno la loro distribuzione.
    assert result["exact_scores"]["modello"] is not None and result["exact_scores"]["mercato"] is not None
    assert result["exact_scores"]["modello"] != result["exact_scores"]["mercato"]


def test_group_selection_parsing_and_settlement():
    assert group_selection(["2-1", "1-0", " 2 - 0 ", "1-0"]) == "1-0/2-0/2-1"
    assert is_group("1-0/2-0") and is_group("0-0") and not is_group("1 + Goal") and not is_group("1-0/")
    assert group_scores("1-0/2-1") == ["1-0", "2-1"]
    assert settle_group("1-0/2-1", 2, 1) == 1 and settle_group("1-0/2-1", 1, 1) == 0
    with pytest.raises(ValueError):
        group_selection([])
    with pytest.raises(ValueError, match="casa-ospite"):
        parse_score("uno a zero")


def test_table_minimum_group_and_value():
    table = score_table(DISTRIBUTION)
    assert list(table["Risultato"][:3]) == ["1-0", "1-1", "2-0"]
    assert table["Cumulata %"].iloc[2] == pytest.approx(47.0) and table["Quota equa"].iloc[0] == pytest.approx(5.0)
    chosen, probability = minimum_group(DISTRIBUTION, 0.50)
    assert chosen == ["1-0", "1-1", "2-0", "2-1"] and probability == pytest.approx(0.57)
    assert minimum_group(DISTRIBUTION, 0.47)[0] == ["1-0", "1-1", "2-0"]  # copertura esatta: niente risultato in più
    assert group_probability(DISTRIBUTION, ["1-0", "2-0", "2-1", "1-1", "1-0"]) == pytest.approx(0.57)
    assert group_probability(DISTRIBUTION, ["9-9"]) == 0.0
    value = group_value(0.57, 1.60)
    assert value["fair_odds"] == pytest.approx(1 / 0.57) and value["ev"] == pytest.approx(0.57 * 1.6 - 1)
    assert value["ev"] < 0 and group_value(0.57, None)["ev"] is None


def test_score_only_markets_exclude_half_time_corners_and_cards():
    markets = set(score_only_markets())
    assert {"1", "X2", "Under 3.5 gol", "Goal", "Multigol 1-3", "Multigol Casa 1-2", "Casa DNB"} <= markets
    assert not any(key.endswith((" 1T", " 2T")) or "corner" in key or "cartellini" in key for key in markets)


def test_coherence_and_correlation():
    group = ["1-0", "2-0", "2-1", "1-1"]
    table = coherence(DISTRIBUTION, group).set_index("Mercato")
    assert bool(table.loc["1X", "Contiene tutto il gruppo"]) and bool(table.loc["Under 3.5 gol", "Contiene tutto il gruppo"])
    assert table.loc["1", "Quota del gruppo %"] == pytest.approx(42 / 57 * 100, abs=0.1)
    assert not table.loc["Goal", "Contiene tutto il gruppo"]
    summary = coherence_summary(coherence(DISTRIBUTION, group))
    assert "tutto 1X" in summary and "tutto Under 3.5 gol" in summary
    finale = {"1X": 80.0, "Under 3.5 gol": 75.0, "2": 15.0, "Goal": 50.0, "Over 9.5 corner": 45.0}
    joint = correlation(DISTRIBUTION, group, ["1X", "2", "Goal", "Over 9.5 corner"], finale).set_index("Mercato")
    assert joint.loc["1X", "Giudizio"].startswith("ridondante")
    assert joint.loc["1X", "Probabilità congiunta %"] == pytest.approx(57.0)
    assert joint.loc["2", "Giudizio"].startswith("incompatibile") and joint.loc["2", "Probabilità congiunta %"] == 0
    assert joint.loc["Goal", "Probabilità congiunta %"] == pytest.approx(25.0)  # 2-1 e 1-1
    assert joint.loc["Goal", "Rapporto con l'indipendenza"] == pytest.approx(0.25 / (0.57 * 0.5), abs=1e-3)
    assert "non calcolabile" in joint.loc["Over 9.5 corner", "Giudizio"]
    assert np.isnan(joint.loc["Over 9.5 corner", "Probabilità congiunta %"]) or joint.loc["Over 9.5 corner", "Probabilità congiunta %"] is None
