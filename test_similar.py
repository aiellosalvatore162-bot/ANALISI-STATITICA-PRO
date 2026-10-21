"""Test dell'analisi avversari simili e dei fattori tattici nel motore (nessuna rete)."""

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import engine
from datasources.builder import DataProvider
from datasources.cache import SourceCache
from datasources.similar import (
    FEATURES, BOUNDS, correction_factors, match_factors, match_history, profile_at, similar_matches, summary_sentence,
    SimilarResult,
)
from parser import parse_match_input
from test_parser import VALID
from tools import dataset

SAMPLES = Path(__file__).resolve().parent / "tests" / "fixtures" / "sources"


def _league(days: int = 30, teams=("A", "B", "C", "D", "E", "F")) -> pd.DataFrame:
    rng = np.random.default_rng(4)
    rows = []
    for day in range(days):
        order = list(teams[day % len(teams):] + teams[:day % len(teams)])
        for home, away in zip(order[::2], order[1::2]):
            rows.append({
                "league": "X1", "season": "2526", "date": pd.Timestamp("2025-08-01") + pd.Timedelta(days=7 * day),
                "home_team": home, "away_team": away, "home_goals": int(rng.integers(0, 4)), "away_goals": int(rng.integers(0, 3)),
                "home_ht_goals": 0, "away_ht_goals": 1, "home_corners": 6 if home == "A" else 4, "away_corners": 4,
                "home_yellows": 2, "away_yellows": 3 if away == "B" else 1, "home_fouls": 11, "away_fouls": 12,
                "home_shots": 12, "away_shots": 9, "home_xg_real": 1.5, "away_xg_real": 1.0,
            })
    return pd.DataFrame(rows)


def _history(matches: pd.DataFrame) -> pd.DataFrame:
    return match_history(matches, None, dataset.match_elos(matches))


def test_history_profiles_use_only_previous_matches():
    matches = _league()
    history = _history(matches)
    altered = matches.copy()
    last = altered["date"] == altered["date"].max()
    altered.loc[last, ["home_corners", "home_yellows"]] = [40, 15]
    altered_history = _history(altered)
    earlier = history["date"] < history["date"].max()
    columns = [column for column in history.columns if column.startswith(("z_", "opp_z_", "base_"))]
    pd.testing.assert_frame_equal(history.loc[earlier, columns].reset_index(drop=True),
                                  altered_history.loc[earlier, columns].reset_index(drop=True))
    assert {"opp_z_corners_for", "base_cards", "opponent_elo"} <= set(history.columns)
    profile, elo, count = profile_at(history, "A")
    assert "corners_for" in profile and count >= 5


def test_similar_matches_prefer_close_opponents_and_respect_the_window():
    rows = []
    for index, (distance, days_ago) in enumerate([(0.0, 10), (3.0, 20), (0.1, 40), (0.2, 900)]):
        rows.append({"team": "A", "date": pd.Timestamp("2026-10-01") - pd.Timedelta(days=days_ago), "history_matches": 20,
                     "opponent_elo": 1700.0, **{f"opp_z_{key}": distance for key in FEATURES}})
    history = pd.DataFrame(rows)
    selected, used = similar_matches(history, "A", {key: 0.0 for key in FEATURES}, 1700.0, pd.Timestamp("2026-10-01"), k=2)
    assert len(selected) == 2 and set(selected["opp_z_pressing"]) == {0.0, 0.1}
    assert used == list(FEATURES)
    partial, used = similar_matches(history, "A", {"corners_for": 0.0, "fouls": 0.0}, 1700.0, pd.Timestamp("2026-10-01"), k=3)
    assert used == ["corners_for", "fouls"]


def _selected(observed: float, baseline: float, count: int) -> pd.DataFrame:
    frame = {"weight": np.ones(count)}
    for stat in ("xg_for", "xg_against", "goals_for", "goals_against", "ht_goals", "corners_for", "corners_against", "cards", "fouls"):
        frame[stat] = np.full(count, observed)
        frame[f"base_{stat}"] = np.full(count, baseline)
    return pd.DataFrame(frame)


def test_shrinkage_pulls_few_matches_toward_one():
    tau = {"goals": 10.0, "first_half": 10.0, "corners": 10.0, "cards": 10.0}
    few, raw, effective = correction_factors(_selected(6.0, 5.0, 2), tau=tau)
    many, _, _ = correction_factors(_selected(6.0, 5.0, 40), tau=tau)
    assert raw["corners_for"] == pytest.approx(1.2) and effective == pytest.approx(2.0)
    assert few["corners_for"] == pytest.approx(np.exp(2 / 12 * np.log(1.2)))
    assert 1.0 < few["corners_for"] < many["corners_for"] < 1.2
    partial, _, _ = correction_factors(_selected(6.0, 5.0, 40), tau=tau, feature_ratio=2.0)
    assert 1.0 < partial["corners_for"] < many["corners_for"]
    empty, _, count = correction_factors(_selected(6.0, 5.0, 0), tau=tau)
    assert count == 0 and set(empty.values()) == {1.0}


def test_match_factors_are_bounded():
    strong = {stat: 2.0 for stat in ("xg_for", "xg_against", "goals_for", "goals_against", "ht_goals",
                                     "corners_for", "corners_against", "cards", "fouls")}
    factors = match_factors(strong, strong)
    assert factors["lambda"] == BOUNDS["goals"][1] and factors["corners_home"] == BOUNDS["corners"][1]
    assert factors["cards"] == BOUNDS["cards"][1]
    neutral = {key: 1.0 for key in strong}
    assert set(match_factors(neutral, neutral).values()) == {1.0}


def test_summary_sentence_reports_changes_and_counts():
    selected = _selected(6.0, 5.0, 5)
    result = SimilarResult("City", "PSV", selected, {"corners_for": 1.2, "xg_for": 0.9, "cards": 1.0}, {}, 5.0)
    sentence = summary_sentence(result, "PSV")
    assert "+20% corner prodotti" in sentence and "-10% xG fatti" in sentence and "5 partite" in sentence


def _config(**changes) -> engine.MatchConfig:
    config = engine.config_from_input(parse_match_input(VALID), simulations=40_000, seed=3)
    return replace(config, **changes)


def test_engine_applies_tactical_factors_only_when_enabled():
    factors = engine.TacticalFactors(lambda_=1.1, mu=0.9, first_half=1.1, corners_home=1.2, corners_away=0.8, cards=1.15)
    base = _config()
    off = _config(tactical=factors, tactical_switches=engine.TacticalSwitches())
    assert engine.final_goal_rates(off)[:2] == pytest.approx(engine.final_goal_rates(base)[:2])
    assert engine.corner_signals(off) == pytest.approx(engine.corner_signals(base))

    on = _config(tactical=factors, tactical_switches=engine.TacticalSwitches(goals=True, corners=True, cards=True))
    model_lambda, model_mu, _ = engine.expected_goals(base)
    assert engine.final_goal_rates(on)[:2] == pytest.approx((model_lambda * 1.1, model_mu * 0.9))
    home, away = engine.corner_signals(base)
    assert engine.corner_signals(on) == pytest.approx((home * 1.2, away * 0.8))
    assert engine.card_total_mean(on) == pytest.approx(engine.card_total_mean(base) * 1.15)

    supremacy = _config(tactical=factors, tactical_switches=engine.TacticalSwitches(goals_supremacy=True))
    lam, mu, _ = engine.final_goal_rates(supremacy)
    assert lam * mu == pytest.approx(model_lambda * model_mu) and lam > model_lambda


def test_goal_factor_is_applied_before_the_market_blend():
    odds = {"1": 2.0, "X": 3.4, "2": 3.9}
    factors = engine.TacticalFactors(lambda_=1.15, mu=0.85)
    anchored = _config(odds=odds, market_anchor=engine.MarketAnchorParams(market_weight=0.9))
    corrected = replace(anchored, tactical=factors, tactical_switches=engine.TacticalSwitches(goals=True))
    plain_lambda = engine.final_goal_rates(anchored)[0]
    corrected_lambda = engine.final_goal_rates(corrected)[0]
    # Con peso mercato 0.9 l'effetto finale è circa 1.15^0.1.
    assert corrected_lambda / plain_lambda == pytest.approx(1.15 ** 0.1, rel=1e-3)


def test_first_half_factor_moves_first_half_goals():
    factors = engine.TacticalFactors(first_half=1.15)
    base = engine.simulate_match(_config())
    corrected = engine.simulate_match(_config(tactical=factors, tactical_switches=engine.TacticalSwitches(first_half=True)))
    assert corrected["components"]["finale"]["Over 0.5 gol 1T"] > base["components"]["finale"]["Over 0.5 gol 1T"]
    assert corrected["components"]["finale"]["Over 2.5 gol"] == base["components"]["finale"]["Over 2.5 gol"]


def test_switches_are_read_from_the_config_file(tmp_path):
    path = tmp_path / "goal_model.json"
    path.write_text(json.dumps({"scenario_tattico": {"attivo": {"cards": True, "goals": False, "ignoto": True}}}), encoding="utf-8")
    assert engine.load_tactical_switches(path) == engine.TacticalSwitches(cards=True)
    assert engine.load_tactical_switches(tmp_path / "assente.json") == engine.TacticalSwitches()


def test_provider_scenario_on_sample_data(tmp_path):
    pages = {
        "https://www.football-data.co.uk/mmz4281/2627/I1.csv": (SAMPLES / "footballdata_I1_2627.csv").read_bytes(),
        "https://understat.com/getLeagueData/Serie_A/2026": (SAMPLES / "understat_serie_a_2026.json").read_bytes(),
    }

    def opener(url, headers, timeout):
        if url not in pages:
            raise ConnectionError("non disponibile nel test")
        return pages[url]

    cache = SourceCache(tmp_path / "c.sqlite", opener=opener, sleep=lambda _: None, min_interval={})
    scenario = DataProvider(cache, today=date(2026, 10, 21), football_data_key=None).tactical_scenario(
        "Napoli", "Roma", match_date=date(2026, 10, 25))
    assert not scenario["cross_league"]
    home = scenario["results"]["home"]
    assert home is not None and not home.matches.empty and home.matches["date"].max() < pd.Timestamp("2026-10-25")
    for name, value in scenario["factors"].items():
        family = "goals" if name in ("lambda", "mu") else "first_half" if name == "first_half" else \
                 "corners" if name.startswith("corners") else "cards"
        low, high = BOUNDS[family]
        assert low <= value <= high
