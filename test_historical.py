from io import BytesIO

import numpy as np
import pandas as pd

from historical import HistoricalDataError, load_football_data_uploads, predict_historical_match, predict_manual_only, resolve_team_name, run_walk_forward
from test_parser import VALID
from parser import parse_match_input


class Upload:
    def __init__(self, name, content):
        self.name = name
        self.content = content

    def getvalue(self):
        return self.content


def _synthetic_history():
    random = np.random.default_rng(18)
    strengths = {f"Club {index}": (index - 2.5) * 0.12 for index in range(6)}
    records = []
    for season_index in range(5):
        season_start = 2018 + season_index
        season = f"{season_start}-{(season_start + 1) % 100:02d}"
        kickoff = pd.Timestamp(f"{season_start}-08-01")
        match_index = 0
        for home_team, home_strength in strengths.items():
            for away_team, away_strength in strengths.items():
                if home_team == away_team:
                    continue
                home_mean = 1.35 * np.exp(home_strength - away_strength + 0.14)
                away_mean = 1.10 * np.exp(away_strength - home_strength)
                records.append({
                    "date": kickoff + pd.Timedelta(days=match_index * 10),
                    "season": season,
                    "league": "Test League",
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_goals": int(random.poisson(home_mean)),
                    "away_goals": int(random.poisson(away_mean)),
                    "odds_home": 2.10,
                    "odds_draw": 3.35,
                    "odds_away": 3.70,
                    "home_corners": int(random.poisson(5.2)),
                    "away_corners": int(random.poisson(4.6)),
                    "home_yellows": int(random.poisson(1.7)),
                    "away_yellows": int(random.poisson(1.9)),
                })
                match_index += 1
    return pd.DataFrame(records)


def test_free_csv_loader_normalizes_football_data_columns_and_filename_season():
    csv = pd.DataFrame({
        "Div": ["E0"],
        "Date": ["10/08/2020"],
        "HomeTeam": ["Arsenal"],
        "AwayTeam": ["Fulham"],
        "FTHG": [3],
        "FTAG": [0],
        "B365H": [1.55],
        "B365D": [4.0],
        "B365A": [6.0],
        "HC": [6],
        "AC": [2],
        "HY": [1],
        "AY": [2],
    }).to_csv(index=False).encode()

    matches = load_football_data_uploads([Upload("E0_2020-21.csv", csv)])

    assert matches.loc[0, "season"] == "2020-21"
    assert matches.loc[0, "league"] == "E0"
    assert matches.loc[0, "home_goals"] == 3
    assert matches.loc[0, "odds_home"] == 1.55
    assert matches.loc[0, "home_corners"] == 6


def test_remote_team_name_resolution_only_accepts_unambiguous_matches():
    teams = ["AC Milan", "Inter", "Roma", "Roma City"]

    assert resolve_team_name("Milan", teams) == "AC Milan"
    assert resolve_team_name("Inter", teams) == "Inter"
    assert resolve_team_name("Unknown FC", teams) is None


def test_walk_forward_uses_future_seasons_only_as_test_data():
    result = run_walk_forward(_synthetic_history(), bootstrap_rounds=100)

    assert result["fold_count"] == 3
    assert result["match_count"] == 90
    assert {"Dixon-Coles calibrato", "Dixon-Coles grezzo", "Uniforme", "Quote bookmaker senza margine"}.issubset(
        set(result["metrics"]["Modello"])
    )
    assert set(result["metrics"].columns) >= {"log_loss", "brier", "rps", "ece", "N"}
    assert result["market_comparison"] is not None
    assert np.isfinite(result["market_comparison"]["ci95_low"])
    assert set(result["count_baselines"]["Misura"]) == {"Corner totali", "Gialli totali"}
    assert set(result["predictions"]["season"]) == {"2020-21", "2021-22", "2022-23"}
    predictions = result["predictions"]
    for row in predictions.itertuples():
        assert row.train_through_season < row.validation_season < row.season


def test_historical_candidate_uses_only_matches_before_kickoff_and_coherent_scores():
    history = _synthetic_history()
    kickoff = pd.Timestamp("2023-01-01")
    first = predict_historical_match(history, "Test League", "Club 4", "Club 1", kickoff)
    future_match = history.iloc[[-1]].copy()
    future_match["date"] = pd.Timestamp("2023-05-01")
    future_match["home_goals"] = 99
    future_match["away_goals"] = 0
    with_future_data = pd.concat([history, future_match], ignore_index=True)
    second = predict_historical_match(with_future_data, "Test League", "Club 4", "Club 1", kickoff)

    assert first["data_through"] < kickoff
    assert first["training_matches"] == second["training_matches"]
    assert first["probabilities_1x2_pct"] == second["probabilities_1x2_pct"]
    assert abs(sum(first["probabilities_1x2_pct"].values()) - 100.0) < 1e-9
    fixed_home, fixed_away = map(int, first["fixed_score"]["score"].split("-"))
    if first["favorite_sign"] == "1":
        assert fixed_home > fixed_away
    elif first["favorite_sign"] == "X":
        assert fixed_home == fixed_away
    else:
        assert fixed_home < fixed_away


def test_manual_recent_rates_blend_with_historical_score_matrix():
    history = _synthetic_history()
    kickoff = pd.Timestamp("2023-01-01")
    historical = predict_historical_match(history, "Test League", "Club 4", "Club 1", kickoff)
    blended = predict_historical_match(
        history,
        "Test League",
        "Club 4",
        "Club 1",
        kickoff,
        manual_rates=(3.5, 0.25),
        manual_weight=0.75,
    )

    assert blended["manual_weight_pct"] == 75.0
    assert blended["historical_probabilities_1x2_pct"] == historical["probabilities_1x2_pct"]
    assert blended["manual_lambda_home"] == 3.5
    assert blended["manual_lambda_away"] == 0.25
    assert abs(sum(blended["probabilities_1x2_pct"].values()) - 100.0) < 1e-9
    assert blended["probabilities_1x2_pct"] != blended["historical_probabilities_1x2_pct"]


def test_manual_data_must_keep_majority_in_blend():
    try:
        predict_historical_match(
            _synthetic_history(),
            "Test League",
            "Club 4",
            "Club 1",
            pd.Timestamp("2023-01-01"),
            manual_rates=(1.6, 1.1),
            manual_weight=0.50,
        )
    except HistoricalDataError as error:
        assert "maggioranza" in str(error)
    else:
        raise AssertionError("Manual inputs must always have a strict majority")


def test_missing_team_in_history_requires_manual_fallback():
    try:
        predict_historical_match(
            _synthetic_history(),
            "Test League",
            "Brand New FC",
            "Club 1",
            pd.Timestamp("2023-01-01"),
            manual_rates=(1.5, 1.0),
            manual_weight=0.75,
        )
    except HistoricalDataError as error:
        assert "100% manuale" in str(error)
    else:
        raise AssertionError("Unknown historical teams must fall back to manual-only predictions")


def test_manual_only_fallback_is_100_percent_manual_and_still_predicts():
    result = predict_manual_only(
        parse_match_input(VALID),
        simulations=3000,
        seed=71,
        reason="historical team not found",
    )

    assert result["source_mode"] == "manual_only"
    assert result["manual_weight_pct"] == 100.0
    assert result["historical_probabilities_1x2_pct"] is None
    assert result["probabilities_1x2_pct"] == result["manual_probabilities_1x2_pct"]
    assert result["fallback_reason"] == "historical team not found"
    assert result["training_matches"] == 0
    assert result["fixed_score"]["score"]


def test_manual_recent_corners_and_yellows_blend_with_team_history():
    history = _synthetic_history()
    manual = {
        "home_corners_for": 5.5,
        "home_corners_against": 4.0,
        "away_corners_for": 4.5,
        "away_corners_against": 5.0,
        "home_yellows_for": 1.8,
        "away_yellows_for": 2.0,
        "referee_yellow_avg": 4.5,
        "referee_fouls_avg": 24.0,
    }
    result = predict_historical_match(
        history, "Test League", "Club 4", "Club 1", pd.Timestamp("2023-01-01"),
        manual_auxiliary=manual, manual_weight=0.75,
    )
    counts = result["count_predictions"]
    expected_manual_corners = (5.5 + 5.0 + 4.5 + 4.0) / 2.0
    expected_manual_yellows = 1.8 + 2.0

    assert np.isclose(
        counts["corner_mean_blended"],
        0.25 * counts["corner_mean_historical"] + 0.75 * expected_manual_corners,
    )
    assert np.isclose(
        counts["yellow_mean_blended"],
        0.25 * counts["yellow_mean_historical"] + 0.75 * expected_manual_yellows,
    )
    assert counts["corner_over_8_5_pct"] is not None
    assert counts["yellow_over_4_5_pct"] is not None