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
                "home_ht_goals": 0, "away_ht_goals": 0,
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


def test_closing_odds_use_engine_event_keys_and_skip_missing_values():
    row = {"close_home": 2.1, "close_draw": 3.3, "close_away": 3.6, "close_over25": 1.9, "close_under25": np.nan}
    assert baseline.closing_odds(row) == {"1": 2.1, "X": 3.3, "2": 3.6, "Over 2.5 gol": 1.9}


def test_secondary_markets_are_coherent_and_match_the_engine():
    half = engine.HalfTimeParams(0.45, 0.43, 0.15, 2.8)
    lambdas, mus = np.array([1.2, 2.4]), np.array([1.0, 0.7])
    markets = baseline.secondary_markets(lambdas, mus, -0.12, half)
    np.testing.assert_allclose(markets["Somma gol"].sum(axis=1), 1.0)
    np.testing.assert_allclose(markets["1X2 1T"].sum(axis=1), 1.0)
    np.testing.assert_allclose(markets["Multigol 1-3"], markets["Somma gol"][:, 1:4].sum(axis=1))
    assert np.all(markets["Over 1.5 1T"] <= markets["Over 0.5 1T"])
    matrix = engine.dixon_coles_matrix(2.4, 0.7, -0.12, max_goals=calibrate.MAX_GOALS)
    shares = engine.first_half_shares(2.4, 0.7, half)
    first_half = engine.half_time_matrix(matrix, float(shares[0]), float(shares[1]))
    assert markets["GG 1T"][1] == pytest.approx(first_half[1:, 1:].sum())


def test_secondary_outcomes_from_full_and_half_time_goals():
    frame = pd.DataFrame({"home_goals": [2, 0], "away_goals": [1, 0], "home_ht_goals": [1, 0], "away_ht_goals": [1, 0]})
    observed = baseline.secondary_outcomes(frame)
    assert observed["Multigol 2-4"].tolist() == [1, 0]
    assert observed["Somma gol"].tolist() == [3, 0]
    assert observed["1X2 1T"].tolist() == [1, 1]
    assert observed["GG 1T"].tolist() == [1, 0]
    assert observed["Multigol Casa 1-2"].tolist() == [1, 0]


def test_half_time_fit_recovers_known_shares():
    rng = np.random.default_rng(3)
    goals = rng.poisson(1.4, (4000, 2))
    data = pd.DataFrame({
        "home_goals": goals[:, 0], "away_goals": goals[:, 1],
        "home_ht_goals": rng.binomial(goals[:, 0], 0.44), "away_ht_goals": rng.binomial(goals[:, 1], 0.41),
        "final_lambda": 1.4, "final_mu": 1.4,
    })
    params = calibrate.fit_half_time(data, with_slope=False)
    assert params.home_share == pytest.approx(0.44, abs=0.02)
    assert params.away_share == pytest.approx(0.41, abs=0.02)


def test_card_points_distribution_matches_the_engine_rule():
    from scipy.stats import poisson as poisson_dist

    from tools.calibrate import observed_points, points_pmf, points_sf

    rule = engine.CardRule()
    pmf = points_pmf(np.array([4.0, 2.5]), 0.0, np.array([0.2, 0.0]), rule)
    assert pmf.sum(axis=1) == pytest.approx([1.0, 1.0], abs=1e-9)
    # Senza rossi i punti sono i gialli.
    assert pmf[1, :10] == pytest.approx(poisson_dist.pmf(np.arange(10), 2.5))
    # Un rosso vale 2: P(punti = 1) = P(0 rossi)·P(1 giallo).
    assert pmf[0, 1] == pytest.approx(poisson_dist.pmf(0, 0.2) * poisson_dist.pmf(1, 4.0))
    assert points_sf(4.5, np.array([4.0]), 0.0, np.array([0.2]), rule)[0] == pytest.approx(pmf[0, 5:].sum())
    data = pd.DataFrame({"home_yellows": [2, 3], "away_yellows": [1, 0], "home_reds": [0, 1], "away_reds": [1, 0]})
    assert list(observed_points(data, rule)) == [5, 5]


def test_exact_score_metrics_on_a_known_matrix():
    size = baseline.EXACT_MAX_GOALS + 1
    matrix = np.zeros((size, size))
    matrix[1, 0], matrix[1, 1], matrix[0, 0], matrix[2, 1] = 0.4, 0.3, 0.2, 0.1
    matrices = np.stack([matrix, matrix])
    metrics = baseline.exact_score_metrics(matrices, np.array([1, 2]), np.array([0, 1]), matrix)
    assert metrics["log_loss"] == pytest.approx(-(np.log(0.4) + np.log(0.1)) / 2)
    assert metrics["risultato_piu_probabile"] == {"prevista": pytest.approx(0.4), "reale": 0.5}
    coverage = {row["copertura_nominale"]: row for row in metrics["copertura"]}
    # 40%: solo 1-0 (vinto nella prima partita); 70%: 1-0 e 1-1; 90%: anche 0-0, il 2-1 resta fuori.
    assert coverage[0.4]["risultati_medi"] == 1 and coverage[0.4]["frequenza_reale"] == 0.5
    assert coverage[0.7]["risultati_medi"] == 2 and coverage[0.9]["risultati_medi"] == 3
    assert coverage[0.9]["frequenza_reale"] == 0.5


def test_phase_m_corrections_can_be_switched_off_and_are_neutral_by_default():
    from tools import calibrate

    neutral = engine.CountModelParams()
    assert neutral.corner_shrink_reference == 0.0 and neutral.card_balance_weight == 0.0
    stripped = calibrate.without_extremes(engine.DEFAULT_COUNT_MODEL)
    assert all(getattr(stripped, key) == getattr(neutral, key) for key in calibrate.EXTREME_FIELDS)
    assert stripped.corner_dispersion == engine.DEFAULT_COUNT_MODEL.corner_dispersion
