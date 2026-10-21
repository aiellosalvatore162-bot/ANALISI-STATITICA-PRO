from dataclasses import replace
import json
from pathlib import Path
import re

import numpy as np
import pytest

import engine
from engine import (
    GoalModelParams, MatchConfig, TeamParams, _event_catalog, config_from_input,
    dixon_coles_matrix, expected_goals, simulate_match, smart_combo,
)
from parser import parse_match_input

from test_parser import COMPLETE_COPY_BLOCK, VALID


def test_simulation_is_reproducible_and_auditable():
    match = parse_match_input(VALID)
    config = config_from_input(match, simulations=3000, seed=11)
    first = simulate_match(config)
    second = simulate_match(config)
    assert first == second
    assert first["model"]["simulation_count"] == 3000
    ledger = first["model"]["formula_ledger"]
    assert ledger["model"] == first["model"]["goal_model"] == "calibrato"
    assert set(ledger["weights"]) == set(GoalModelParams.__dataclass_fields__)
    for side, rate in (("home", first["model"]["lambda"]), ("away", first["model"]["mu"])):
        contributions = ledger[side]
        product = contributions["base_goals"] * np.prod([
            contributions[key] for key in (
                "home_advantage_multiplier", "attack_multiplier", "opponent_defense_multiplier",
                "elo_multiplier", "form_multiplier",
            )
        ])
        assert abs(product - rate) < 1e-5
    assert set(first["markets"]["1x2"]) == {"1", "X", "2"}
    assert set(first["markets"]["first_half_1x2"]) == {"1", "X", "2"}
    assert set(first["markets"]["first_half_goal_no_goal"]) == {"Goal", "No_Goal"}
    assert set(first["markets"]["multigol"]) == {"1-2", "1-3", "2-4", "2-5"}
    assert "Over_10.5" in first["markets"]["corners"]
    assert "Under_6.5" in first["markets"]["cards"]


def test_probabilities_use_the_declared_sample_size():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=2000, seed=3))
    assert sum(item["count"] for item in result["markets"]["1x2"].values()) == 2000
    assert result["summary"]["modal_score"]["share_pct"] > 0
    score_distribution = result["dashboard"]["exact_score_distribution"]
    assert score_distribution["labels"] == [*(str(value) for value in range(8)), "8+"]
    assert abs(sum(map(sum, score_distribution["probabilities_pct"])) - 100.0) < 0.01
    goal_distribution = result["dashboard"]["goals_distribution"]
    assert goal_distribution["goals"][-1] == "8+"
    assert abs(sum(goal_distribution["home"]) - 100.0) < 0.01
    assert abs(sum(goal_distribution["away"]) - 100.0) < 0.01
    for market in result["markets"]["1x2"].values():
        low, high = market["confidence_interval_95"]
        assert 0 <= low <= high <= 100
        assert 0 <= market["reliability_pct"] <= 100
        assert market["fair_odds"] > 1.0


def test_score_derived_markets_are_coherent_for_every_simulation():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=4000, seed=17))
    markets = result["markets"]
    simulation_count = result["model"]["simulation_count"]

    assert sum(markets["1x2"][key]["count"] for key in ("1", "X", "2")) == simulation_count
    assert markets["double_chance"]["1X"]["count"] + markets["double_chance"]["X2"]["count"] >= simulation_count
    assert markets["goal_no_goal"]["Goal"]["count"] + markets["goal_no_goal"]["No_Goal"]["count"] == simulation_count
    assert markets["over_under"]["Over_2.5"]["count"] + markets["over_under"]["Under_2.5"]["count"] == simulation_count
    assert sum(markets["goal_sums"][str(value)]["count"] for value in range(5)) + markets["goal_sums"]["5+"]["count"] == simulation_count
    assert markets["multigol_complete"]["2-3"]["count"] <= markets["over_under"]["Over_1.5"]["count"]


def test_exact_score_two_one_activates_all_dependent_markets():
    one = lambda value: np.array([value])
    events = _event_catalog(one(2), one(1), one(1), one(0), one(1), one(1), one(4), one(3), one(2), one(1))

    assert events["1"][0]
    assert not events["X2"][0]
    assert events["Casa DNB"][0]
    assert events["Over 2.5 gol"][0]
    assert events["Goal"][0]
    assert events["Multigol 2-3"][0]
    assert events["Multigol Casa 1-2"][0]
    assert events["Somma gol 3"][0]


def test_team_multigol_ranges_are_dynamic_and_reach_financial_analysis():
    config = config_from_input(parse_match_input(VALID), simulations=3000, seed=21)
    config = config.__class__(
        **{
            **config.__dict__,
            "odds": {
                "Multigol Casa 1-4": 1.75,
                "Multigol Ospite 3-4": 2.40,
            },
        }
    )
    result = simulate_match(config)

    assert {"Casa 1-4", "Ospite 3-4"}.issubset(result["markets"]["team_multigol"])
    financial = {row["market"]: row for row in result["financial"]["markets"]}
    assert {"Multigol Casa 1-4", "Multigol Ospite 3-4"} == set(financial)
    for row in financial.values():
        assert row["fair_odds"] is not None
        assert len(row["confidence_interval_95"]) == 2
        assert "recommended_quarter_kelly_pct" in row


def test_complete_market_catalog_exposes_all_requested_families():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=2000, seed=9))
    markets = result["markets"]
    assert set(markets["double_chance"]) == {"1X", "X2", "12"}
    assert set(markets["second_half_1x2"]) == {"1", "X", "2"}
    assert set(markets["second_half_double_chance"]) == {"1X", "X2", "12"}
    assert set(markets["over_under"]) == {
        "Over_0.5", "Under_0.5", "Over_1.5", "Under_1.5",
        "Over_2.5", "Under_2.5", "Over_3.5", "Under_3.5",
        "Over_4.5", "Under_4.5",
    }
    assert set(markets["multigol_complete"]) == {
        "1-2", "1-3", "1-4", "1-5", "2-3", "2-4", "2-5", "2-6",
        "3-4", "3-5", "3-6",
    }
    assert set(markets["goal_sums"]) == {"0", "1", "2", "3", "4", "5+"}
    assert len(markets["combos"]) >= 10
    assert set(markets["corner_1x2"]) == {"1", "X", "2"}
    assert set(markets["card_1x2"]) == {"1", "X", "2"}


def test_financial_analysis_and_smart_combo_use_joint_samples():
    match = parse_match_input(VALID)
    config = config_from_input(match, simulations=5000, seed=4)
    config = config.__class__(
        **{**config.__dict__, "odds": {"1X": 1.35, "Over 1.5 gol": 1.30, "Over 8.5 corner": 1.90, "Over 4.5 cartellini": 1.80}}
    )
    result = simulate_match(config)
    assert result["financial"]["quotes_provided"] == 4
    assert result["financial"]["best_value"] is not None
    best = result["financial"]["best_value"]
    assert best["recommended_stake_pct"] == best["recommended_quarter_kelly_pct"]
    assert best["kelly_fraction"] == 0.25
    assert len(best["confidence_interval_95"]) == 2
    assert result["smart_combo"]["recommendation"] is not None
    combo = result["smart_combo"]["recommendation"]
    assert len(combo["legs"]) == 2
    assert combo["recommended_stake_pct"] >= 0
    assert 0 <= combo["reliability_pct"] <= 100


def test_quotes_from_parsed_input_reach_value_bet_analysis():
    text = VALID.replace("CASA: Inter", "CASA: Inter | Quota 1: 1.85").replace(
        "OSPITE: Milan", "OSPITE: Milan | Quota X: 3.40 | Quota 2: 4.20"
    )
    result = simulate_match(config_from_input(parse_match_input(text), simulations=2000, seed=5))
    assert {row["market"] for row in result["financial"]["markets"]} == {"1", "X", "2"}
    assert all("recommended_stake_pct" in row for row in result["financial"]["markets"])


def test_complete_copy_block_quotes_reach_market_and_financial_analysis():
    match = parse_match_input(COMPLETE_COPY_BLOCK)
    result = simulate_match(config_from_input(match, simulations=3000, seed=59))
    financial_markets = {row["market"] for row in result["financial"]["markets"]}

    assert len(match.odds) == 72
    assert len(financial_markets) == 72
    assert "Casa DNB" in financial_markets
    assert "Ospite DNB" in financial_markets
    assert "Over 1.5 gol 1T" in financial_markets
    assert "1X + Over 1.5 gol" in financial_markets
    assert "X2 + Over 1.5 gol" in financial_markets
    assert "X2 + Multigol 1-3" in financial_markets
    assert set(match.odds) == financial_markets


def test_dnb_financial_settlement_exposes_push_probability():
    config = config_from_input(parse_match_input(VALID), simulations=4000, seed=6)
    config = config.__class__(**{**config.__dict__, "odds": {"Casa DNB": 1.70}})
    result = simulate_match(config)
    row = result["financial"]["markets"][0]
    assert row["market"] == "Casa DNB"
    assert row["push_probability_pct"] > 0
    assert 0 <= row["loss_probability_pct"] <= 100
    expected_fair_odds = 1.0 + row["loss_probability_pct"] / row["simulated_probability_pct"]
    assert row["fair_odds"] == round(expected_fair_odds, 3)
    assert row["settlement_fair_odds"] == row["fair_odds"]
    expected_edge = (
        row["simulated_probability_pct"] * 100.0
        / (100.0 - row["push_probability_pct"])
        - row["implied_probability_pct"]
    )
    assert row["edge_pct"] == round(expected_edge, 2)


def test_smart_combo_does_not_treat_dnb_push_as_a_binary_loss():
    events = {
        "Casa DNB": np.array([True] * 9 + [False]),
        "Over 1.5 gol": np.array([True] * 8 + [False, False]),
    }

    result = smart_combo(events, {"Casa DNB": 2.0, "Over 1.5 gol": 2.0})

    assert result["recommendation"] is None
    assert result["status"] == "insufficient_quotes"


def test_report_is_consistent_with_returned_probabilities():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=3000, seed=2))
    report = result["statistical_report"]
    p1 = result["markets"]["1x2"]["1"]["percentage"]
    assert f"{p1:.2f}%" in report
    assert f"λ={result['model']['lambda']:.3f}" in report


def test_simulation_samples_the_dixon_coles_score_distribution(monkeypatch):
    forced_distribution = np.zeros((3, 2))
    forced_distribution[2, 1] = 1.0
    monkeypatch.setattr(engine, "dixon_coles_matrix", lambda *_args, **_kwargs: forced_distribution)

    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=100, seed=7))

    assert result["summary"]["modal_score"] == {
        "home": 2,
        "away": 1,
        "share_pct": 100.0,
        "conditional_share_pct": 100.0,
    }
    assert result["markets"]["1x2"]["1"]["percentage"] == 100.0


def test_fixed_score_follows_favorite_sign_and_derived_markets(monkeypatch):
    forced_distribution = np.zeros((4, 2))
    forced_distribution[1, 1] = 0.40
    forced_distribution[2, 1] = 0.35
    forced_distribution[3, 1] = 0.25
    monkeypatch.setattr(engine, "dixon_coles_matrix", lambda *_args, **_kwargs: forced_distribution)
    config = config_from_input(parse_match_input(VALID), simulations=20_000, seed=13)

    result = simulate_match(config)
    summary = result["summary"]
    score_markets = result["fixed_score_scenario"]["markets"]

    assert summary["most_likely_exact_score"]["home"] == 1
    assert summary["most_likely_exact_score"]["away"] == 1
    assert summary["favorite_sign"] == "1"
    assert summary["modal_score"]["home"] == 2
    assert summary["modal_score"]["away"] == 1
    assert score_markets["1"] == 100.0
    assert score_markets["Over 2.5 gol"] == 100.0
    assert score_markets["Goal"] == 100.0
    assert score_markets["Multigol 2-3"] == 100.0
    assert score_markets["Somma gol 3"] == 100.0


def test_conditional_scenarios_keep_markets_tied_to_the_selected_sign():
    simulations = 4000
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=simulations, seed=31))
    scenarios = result["conditional_scenarios"]

    assert sum(scenario["sample_count"] for scenario in scenarios.values()) == simulations
    assert scenarios["1"]["sample_count"] == result["markets"]["1x2"]["1"]["count"]
    assert scenarios["1"]["markets"]["1"] == 100.0
    assert scenarios["1"]["markets"]["X"] == 0.0
    assert scenarios["1"]["markets"]["2"] == 0.0
    assert scenarios["1"]["markets"]["1X"] == 100.0
    assert scenarios["2"]["markets"]["X2"] == 100.0


def test_corner_mean_uses_for_and_opponent_conceded_averages():
    config = config_from_input(parse_match_input(VALID), simulations=12_000, seed=33)
    config = config.__class__(
        **{
            **config.__dict__,
            "home": config.home.__class__(**{**config.home.__dict__, "corners_for": 6.0, "corners_against": 4.0}),
            "away": config.away.__class__(**{**config.away.__dict__, "corners_for": 5.0, "corners_against": 7.0}),
        }
    )

    result = simulate_match(config)

    assert abs(result["markets"]["corners"]["mean"] - 11.0) < 0.12


def test_zero_card_inputs_do_not_create_artificial_cards():
    config = config_from_input(parse_match_input(VALID), simulations=2000, seed=47)
    config = config.__class__(
        **{
            **config.__dict__,
            "home": config.home.__class__(**{**config.home.__dict__, "cards_for": 0.0}),
            "away": config.away.__class__(**{**config.away.__dict__, "cards_for": 0.0}),
            "referee_yellow_avg": 0.0,
        }
    )

    result = simulate_match(config)

    assert result["markets"]["cards"]["mean"] == 0.0
    assert result["markets"]["cards"]["Over_2.5"]["percentage"] == 0.0
    assert result["markets"]["card_1x2"]["X"]["percentage"] == 100.0


def _team(name: str, **overrides) -> TeamParams:
    values = dict(
        name=name, attack=1.0, defense=1.0, elo=1700.0, form="W-D-L-W-D",
        xg_for=engine.DEFAULT_GOAL_PARAMS.base_goals, xg_against=engine.DEFAULT_GOAL_PARAMS.base_goals,
        corners_for=5.0, corners_against=5.0, cards_for=2.0,
    )
    return TeamParams(**{**values, **overrides})


def _probabilities_1x2(config: MatchConfig) -> np.ndarray:
    lambda_, mu, _ = expected_goals(config)
    matrix = dixon_coles_matrix(lambda_, mu, config.dixon_coles_rho)
    home, away = np.indices(matrix.shape)
    return np.array([matrix[home > away].sum(), np.trace(matrix), matrix[home < away].sum()])


def test_neutral_inputs_are_symmetric_except_home_advantage():
    neutral = MatchConfig(home=_team("A"), away=_team("B"), referee_yellow_avg=4.5, referee_fouls_avg=24.0)
    no_home_advantage = replace(neutral, goal_params=replace(neutral.goal_params, home_advantage=0.0))

    lambda_, mu, _ = expected_goals(no_home_advantage)
    p1, _, p2 = _probabilities_1x2(no_home_advantage)
    assert lambda_ == pytest.approx(mu)
    assert p1 == pytest.approx(p2)

    lambda_, mu, _ = expected_goals(neutral)
    p1, _, p2 = _probabilities_1x2(neutral)
    assert lambda_ / mu == pytest.approx(np.exp(neutral.goal_params.home_advantage))
    assert p1 > p2


def test_swapping_home_and_away_is_coherent():
    strong = _team("Forte", attack=1.6, defense=1.4, elo=1900.0, form="W-W-W-W-W", xg_for=2.1, xg_against=0.9)
    weak = _team("Debole", attack=0.8, defense=0.8, elo=1600.0, form="L-L-D-L-W", xg_for=1.0, xg_against=1.8)
    forward = MatchConfig(home=strong, away=weak, referee_yellow_avg=4.5, referee_fouls_avg=24.0)
    reverse = replace(forward, home=weak, away=strong)

    neutral_params = replace(forward.goal_params, home_advantage=0.0)
    p_forward = _probabilities_1x2(replace(forward, goal_params=neutral_params))
    p_reverse = _probabilities_1x2(replace(reverse, goal_params=neutral_params))
    np.testing.assert_allclose(p_forward, p_reverse[::-1], atol=1e-12)

    # Con il vantaggio casa la squadra forte vince più spesso in casa che in trasferta.
    assert _probabilities_1x2(forward)[0] > _probabilities_1x2(reverse)[2]


def test_calibrated_model_does_not_compress_a_clear_favourite():
    strong = _team("Forte", attack=1.9, defense=1.6, elo=1950.0, form="W-W-W-W-W", xg_for=2.4, xg_against=0.8)
    weak = _team("Debole", attack=0.75, defense=0.7, elo=1600.0, form="L-L-D-L-L", xg_for=0.9, xg_against=1.9)
    config = MatchConfig(home=strong, away=weak, referee_yellow_avg=4.5, referee_fouls_avg=24.0)

    calibrated = _probabilities_1x2(replace(config, goal_model="calibrato"))
    legacy = _probabilities_1x2(replace(config, goal_model="legacy", dixon_coles_rho=-0.11))
    assert calibrated[0] > legacy[0] + 0.05
    assert calibrated[0] > 0.75


def test_goal_rates_vectorized_matches_scalar_expected_goals():
    config = config_from_input(parse_match_input(VALID))
    lambda_, mu, _ = expected_goals(config)
    rates = engine.goal_rates(
        config.goal_params,
        home_attack=np.array([config.home.attack] * 2), home_defense=np.array([config.home.defense] * 2),
        home_xg_for=np.array([config.home.xg_for] * 2), home_xg_against=np.array([config.home.xg_against] * 2),
        home_form=np.array([engine.form_score(config.home.form)] * 2),
        away_attack=np.array([config.away.attack] * 2), away_defense=np.array([config.away.defense] * 2),
        away_xg_for=np.array([config.away.xg_for] * 2), away_xg_against=np.array([config.away.xg_against] * 2),
        away_form=np.array([engine.form_score(config.away.form)] * 2),
        elo_diff=np.array([config.home.elo - config.away.elo] * 2),
    )
    np.testing.assert_allclose(rates[0], lambda_)
    np.testing.assert_allclose(rates[1], mu)


def test_goal_model_file_drives_defaults_and_missing_file_falls_back_to_legacy(tmp_path):
    assert engine.load_goal_model(tmp_path / "assente.json") == ("legacy", GoalModelParams())

    path = tmp_path / "goal_model.json"
    path.write_text(json.dumps({"modello_attivo": "calibrato", "parametri": {"elo_k": 2.0}}), encoding="utf-8")
    active, params = engine.load_goal_model(path)
    assert active == "calibrato" and params.elo_k == 2.0

    path.write_text(json.dumps({"modello_attivo": "altro", "parametri": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        engine.load_goal_model(path)


def test_legacy_model_keeps_original_rho_and_formula():
    config = replace(config_from_input(parse_match_input(VALID)), goal_model="legacy", dixon_coles_rho=None)
    assert config.dixon_coles_rho == -0.11
    assert expected_goals(config)[2]["model"] == "legacy"
    with pytest.raises(ValueError):
        replace(config, goal_model="sconosciuto")


# Partite reali del 20/10/2026: dati squadra e arbitro dalle schede usate quella
# sera (tests/fixtures). Le quote nelle schede sono stime e vengono ignorate;
# il confronto usa solo le quote 1X2 reali qui sotto e il modello "solo dati".
FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"
REAL_MATCHES_2026_10_20 = {
    "MANCHESTER CITY vs AEK ATENE": {"1": 1.11},
    "ROMA vs SLOVAN BRATISLAVA": {"1": 1.15, "X": 8.50, "2": 18.00},
    "NAPOLI vs BODO/GLIMT": {"1": 1.55, "X": 4.50, "2": 5.00},
    "PSG vs BARCELLONA": {"1": 2.40, "X": 4.33, "2": 2.45},
}


def _match_sheets(filename: str) -> dict[str, str]:
    text = (FIXTURES / filename).read_text(encoding="utf-8")
    parts = re.split(r"=+\nPARTITA – (.+?)\n=+\n", text)
    return dict(zip(parts[1::2], parts[2::2]))


@pytest.mark.parametrize("name", REAL_MATCHES_2026_10_20)
def test_real_matches_of_2026_10_20_stay_close_to_the_market(name):
    sheet = _match_sheets("schede_complete_21-00.txt")[name]
    config = replace(config_from_input(parse_match_input(sheet)), odds={})
    model = _probabilities_1x2(config)
    odds = REAL_MATCHES_2026_10_20[name]
    if set(odds) != {"1", "X", "2"}:
        # Solo la quota 1 è reale: nessuna rimozione del margine, solo una soglia.
        assert model[0] >= 0.80, f"vittoria casa {model[0]:.3f}"
        return
    implied = np.array([1.0 / odds[key] for key in ("1", "X", "2")])
    market = implied / implied.sum()
    assert np.all(np.abs(model - market) <= 0.07), f"modello {model.round(3)} mercato {market.round(3)}"
    if name == "PSG vs BARCELLONA":
        assert abs(model[0] - model[2]) <= 0.10, f"modello {model.round(3)} non equilibrato"


def _fair_odds(lambda_: float, mu: float, rho: float) -> dict[str, float]:
    probabilities = engine._score_market_probabilities(lambda_, mu, rho)
    return {key: 1.0 / value for key, value in probabilities.items()}


def test_remove_margin_methods():
    odds = [1.30, 5.50, 11.0]
    proportional = engine.remove_margin(odds, "proporzionale")
    shin = engine.remove_margin(odds, "shin")
    assert proportional.sum() == pytest.approx(1.0)
    assert shin.sum() == pytest.approx(1.0)
    # Shin toglie più margine dagli esiti improbabili: la favorita sale.
    assert shin[0] > proportional[0] and shin[2] < proportional[2]
    fair = [2.0, 4.0, 4.0]
    np.testing.assert_allclose(engine.remove_margin(fair, "shin"), [0.5, 0.25, 0.25])
    with pytest.raises(ValueError):
        engine.remove_margin(odds, "altro")


@pytest.mark.parametrize("method", engine.DEVIG_METHODS)
def test_market_goal_rates_recover_the_generating_rates(method):
    rho = -0.12
    fitted = engine.market_goal_rates(_fair_odds(1.9, 0.8, rho), method, rho)
    assert fitted["lambda"] == pytest.approx(1.9, abs=2e-3)
    assert fitted["mu"] == pytest.approx(0.8, abs=2e-3)
    assert fitted["markets_used"] == list(engine.ANCHOR_MARKETS)
    assert fitted["max_fit_error_pct"] < 0.05


def test_market_goal_rates_need_1x2_and_both_over_under_sides():
    odds = _fair_odds(1.5, 1.1, -0.11)
    assert engine.market_goal_rates({"1": odds["1"], "X": odds["X"]}) is None
    without_under = {key: odds[key] for key in ("1", "X", "2", "Over 2.5 gol")}
    assert engine.market_goal_rates(without_under)["markets_used"] == ["1", "X", "2"]


def test_anchor_blend_is_log_scale_and_bounded():
    params = engine.MarketAnchorParams(market_weight=0.7)
    lambda_, mu, correction_home, correction_away = engine.anchor_goal_rates(1.1, 1.3, 1.0, 1.0, params)
    assert lambda_ == pytest.approx(1.1 ** 0.3)
    assert mu == pytest.approx(1.3 ** 0.3)
    only_market = replace(params, market_weight=1.0)
    assert engine.anchor_goal_rates(2.5, 0.4, 1.8, 0.9, only_market)[:2] == pytest.approx((1.8, 0.9))
    bounded = engine.anchor_goal_rates(4.0, 0.2, 1.0, 1.0, replace(params, market_weight=0.0))
    assert bounded[2] == pytest.approx(1.2) and bounded[3] == pytest.approx(0.8)


def _with_odds(odds: dict[str, float]) -> MatchConfig:
    config = config_from_input(parse_match_input(VALID), simulations=20_000, seed=8)
    return replace(config, odds=odds, market_anchor=engine.MarketAnchorParams(market_weight=0.7))


def test_simulation_without_odds_uses_only_the_model():
    config = _with_odds({})
    result = simulate_match(config)
    model_lambda, model_mu, _ = expected_goals(config)
    assert not result["market_anchoring"]["active"]
    assert result["model"]["lambda"] == pytest.approx(model_lambda, abs=1e-6)
    assert result["components"]["mercato"] is None
    assert result["components"]["modello"] == result["components"]["finale"]


def test_simulation_with_odds_reports_market_model_and_final_probabilities():
    odds = {"1": 1.85, "X": 3.40, "2": 4.20, "Over 2.5 gol": 1.80, "Under 2.5 gol": 2.00}
    result = simulate_match(_with_odds(odds))
    anchoring = result["market_anchoring"]
    assert anchoring["active"]
    assert 0.8 <= anchoring["correction_home"] <= 1.2
    components = result["components"]
    assert set(components) == {"finale", "modello", "mercato"}
    assert components["finale"]["1"] == result["markets"]["1x2"]["1"]["percentage"]
    for source in components.values():
        assert source["1"] + source["X"] + source["2"] == pytest.approx(100.0, abs=0.02)
    # Corner e cartellini non dipendono dai gol attesi: identici nelle tre fonti.
    assert components["mercato"]["Over 9.5 corner"] == components["modello"]["Over 9.5 corner"]
    row = {item["market"]: item for item in result["financial"]["markets"]}["1"]
    assert row["market_only_probability_pct"] == components["mercato"]["1"]
    assert row["model_only_probability_pct"] == components["modello"]["1"]


def test_value_is_suspicious_when_model_and_market_diverge():
    # Quote che danno l'ospite nettamente favorito contro input favorevoli alla casa.
    result = simulate_match(_with_odds({"1": 6.0, "X": 4.2, "2": 1.55}))
    rows = {item["market"]: item for item in result["financial"]["markets"]}
    assert rows["1"]["model_market_gap_pct"] > 10.0
    assert rows["1"]["is_value"] and rows["1"]["suspicious_value"]
    assert not rows["2"]["suspicious_value"]


def test_market_anchor_defaults_when_the_file_has_no_section(tmp_path):
    path = tmp_path / "goal_model.json"
    path.write_text(json.dumps({"modello_attivo": "legacy", "parametri": {}}), encoding="utf-8")
    assert engine.load_market_anchor(path) == engine.MarketAnchorParams()
    assert engine.load_market_anchor(tmp_path / "assente.json") == engine.MarketAnchorParams()
    with pytest.raises(ValueError):
        replace(_with_odds({}), market_anchor=engine.MarketAnchorParams(devig_method="altro"))


def test_draw_is_never_flagged_as_value_but_keeps_its_ev():
    # Quote del pareggio molto alte: EV positivo ma nessun VALORE sulla X.
    result = simulate_match(_with_odds({"1": 2.6, "X": 9.0, "2": 2.9}))
    rows = {item["market"]: item for item in result["financial"]["markets"]}
    assert rows["X"]["ev_pct"] > 0
    assert rows["X"]["value_excluded"] and not rows["X"]["is_value"] and not rows["X"]["suspicious_value"]
    assert "X" not in {item["market"] for item in result["financial"]["value_bets"]}
    assert all("X" not in combo["legs"] for combo in result["smart_combo"]["candidates"])
    allowed = replace(engine.MarketAnchorParams(market_weight=0.7), no_value_markets=())
    rows = {item["market"]: item for item in simulate_match(
        replace(_with_odds({"1": 2.6, "X": 9.0, "2": 2.9}), market_anchor=allowed)
    )["financial"]["markets"]}
    assert rows["X"]["is_value"]


def test_no_value_markets_is_read_from_the_config_file(tmp_path):
    path = tmp_path / "goal_model.json"
    path.write_text(json.dumps({"ancoraggio_mercato": {"parametri": {"no_value_markets": ["X", "X 1T"]}}}), encoding="utf-8")
    assert engine.load_market_anchor(path).no_value_markets == ("X", "X 1T")
