import numpy as np
import pandas as pd
import pytest

import engine
from tools import baseline, calibrate, dataset


def test_metrics_on_known_values():
    probabilities = np.array([[0.5, 0.3, 0.2], [0.1, 0.1, 0.8]])
    outcomes = np.array([0, 2])
    assert baseline.log_loss(probabilities, outcomes) == pytest.approx(-(np.log(0.5) + np.log(0.8)) / 2)
    assert baseline.brier(probabilities, outcomes) == pytest.approx(((0.25 + 0.09 + 0.04) + (0.01 + 0.01 + 0.04)) / 2)
    perfect = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert baseline.expected_calibration_error(perfect, np.array([0, 1])) == pytest.approx(0.0)


def test_de_vig_removes_margin_proportionally():
    probabilities = baseline.de_vig(np.array([2.0]), np.array([3.5]), np.array([4.0]))
    implied = np.array([1 / 2.0, 1 / 3.5, 1 / 4.0])
    np.testing.assert_allclose(probabilities[0], implied / implied.sum())
    assert probabilities.sum() == pytest.approx(1.0)


def test_vectorized_score_matrices_match_engine():
    lambdas, mus = np.array([0.6, 1.4, 2.8]), np.array([1.9, 1.1, 0.5])
    matrices = calibrate.score_matrices(lambdas, mus, -0.12, max_goals=12)
    for matrix, lambda_, mu in zip(matrices, lambdas, mus):
        np.testing.assert_allclose(matrix, engine.dixon_coles_matrix(lambda_, mu, -0.12, max_goals=12), atol=1e-12)
    markets = calibrate.market_probabilities(matrices)
    np.testing.assert_allclose(markets["1x2"].sum(axis=1), 1.0)


def _raw_matches(days: int = 12) -> pd.DataFrame:
    rows = []
    teams = ["A", "B", "C", "D"]
    start = pd.Timestamp("2024-08-01")
    for day in range(days):
        pairs = [(teams[day % 4], teams[(day + 1) % 4]), (teams[(day + 2) % 4], teams[(day + 3) % 4])]
        for home, away in pairs:
            rows.append({
                "league": "I1", "season": "2425", "date": start + pd.Timedelta(days=7 * day),
                "home_team": home, "away_team": away, "home_goals": (day + len(home)) % 3, "away_goals": day % 2,
                "home_shots": 12, "away_shots": 9, "home_sot": 5, "away_sot": 3,
                "home_fouls": 11, "away_fouls": 12, "home_corners": 6, "away_corners": 4,
                "home_yellows": 2, "away_yellows": 2, "referee": "Rossi",
                "home_xg_real": np.nan, "away_xg_real": np.nan,
                "close_home": 2.0, "close_draw": 3.4, "close_away": 3.8, "close_over25": 1.9, "close_under25": 1.9,
            })
    return pd.DataFrame(rows)


def test_features_use_only_matches_before_the_match_date():
    raw = _raw_matches()
    xg_model = dataset.ShotXgModel(0.3, 0.0)
    features = dataset.build_features(raw, xg_model)
    altered = raw.copy()
    last_day = altered["date"].max()
    altered.loc[altered["date"] == last_day, ["home_goals", "away_goals", "home_corners"]] = [9, 0, 20]
    altered_features = dataset.build_features(altered, xg_model)
    pd.testing.assert_frame_equal(features, altered_features.assign(
        home_goals=features["home_goals"], away_goals=features["away_goals"], home_corners=features["home_corners"],
    ))
    first_day = features[features["date"] == features["date"].min()]
    assert (first_day["home_history"] == 0).all()
    assert first_day["home_xg_for"].isna().all()


def test_elo_updates_are_zero_sum_and_reward_the_winner():
    raw = _raw_matches(days=2)
    features = dataset.build_features(raw, dataset.ShotXgModel(0.3, 0.0))
    first = raw.iloc[0]
    second_day = features[features["date"] == features["date"].max()]
    ratings = {**dict(zip(second_day["home_team"], second_day["home_elo"])),
               **dict(zip(second_day["away_team"], second_day["away_elo"]))}
    assert sum(ratings.values()) == pytest.approx(4 * dataset.ELO_START)
    assert first["home_goals"] > first["away_goals"]
    assert ratings[first["home_team"]] > ratings[first["away_team"]]


def test_shot_xg_proxy_is_non_negative_least_squares():
    raw = _raw_matches().assign(season="1920")
    raw["home_goals"] = (raw["home_sot"] * 0.3).round().astype(int)
    model = dataset.fit_shot_xg(raw)
    assert model.on_target >= 0.0 and model.off_target >= 0.0
