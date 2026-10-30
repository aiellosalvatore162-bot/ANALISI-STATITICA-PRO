"""Fase P (motore v2): forze Dixon-Coles, opzioni del motore, ricalibrazione, assenze e marcatori (senza rete)."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

import absences
import engine
import ratings
import scorers
from engine import ModelV2Params, config_from_input, simulate_match
from parser import parse_match_input
from test_engine import VALID
from tools import recalibration_check, v2common
from tools.player_check import new_probability


def _season(seed=0, days=700, decay_noise=False):
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(16)]
    attack, defence = rng.normal(0, 0.3, 16), rng.normal(0, 0.3, 16)
    rows = []
    for day in range(0, days, 4):
        order = rng.permutation(16)
        for k in range(0, 16, 2):
            i, j = order[k], order[k + 1]
            rows.append({"date": pd.Timestamp("2024-08-01") + pd.Timedelta(days=day), "home_team": teams[i],
                         "away_team": teams[j], "home_goals": rng.poisson(np.exp(0.1 + 0.25 + attack[i] - defence[j])),
                         "away_goals": rng.poisson(np.exp(0.1 + attack[j] - defence[i]))})
    return pd.DataFrame(rows), teams, attack, defence


def test_schedule_strengths_recover_attack_defence_and_home_advantage():
    matches, teams, attack, defence = _season()
    fitted = ratings.fit(matches, "2026-08-01", ratings.StrengthParams(decay_per_day=0.0))
    estimated = np.array([fitted.attack[team] for team in teams])
    assert np.corrcoef(estimated, attack)[0, 1] > 0.9
    assert np.corrcoef([fitted.defence[team] for team in teams], defence)[0, 1] > 0.9
    assert fitted.home == pytest.approx(0.25, abs=0.08)
    assert abs(estimated.mean()) < 1e-9
    home, away = fitted.rates("T0", "T1")
    assert home > 0 and away > 0 and fitted.ratios("sconosciuta") == (1.0, 1.0)
    # Solo partite precedenti alla data; con meno di 20 partite nessuna stima.
    assert ratings.fit(matches, "2024-08-05") is None


def test_schedule_strengths_use_xg_and_shrink_teams_with_few_matches():
    matches, *_ = _season(seed=1, days=200)
    matches["home_xg"], matches["away_xg"] = 1.5, 1.0
    only_xg = ratings.fit(matches, "2026-01-01", ratings.StrengthParams(decay_per_day=0.0, goal_weight=0.0))
    # Con xG tutti uguali le forze sono nulle e la casa vale log(1.5/1.0).
    assert max(abs(value) for value in only_xg.attack.values()) < 1e-6
    assert only_xg.home == pytest.approx(np.log(1.5), abs=1e-6)
    newcomer = pd.concat([matches, pd.DataFrame([{"date": pd.Timestamp("2025-02-10"), "home_team": "Nuova",
                                                  "away_team": "T0", "home_goals": 6, "away_goals": 0}])])
    loose = ratings.fit(newcomer, "2026-01-01", ratings.StrengthParams(decay_per_day=0.0, prior_matches=0.0))
    shrunk = ratings.fit(newcomer, "2026-01-01", ratings.StrengthParams(decay_per_day=0.0, prior_matches=5.0))
    assert 0 < shrunk.attack["Nuova"] < loose.attack["Nuova"]


def test_split_anchor_matches_the_single_weight_and_separates_total_and_supremacy():
    params = engine.DEFAULT_MARKET_ANCHOR
    single = engine.anchor_goal_rates(1.8, 1.0, 1.6, 1.1, params)
    split = engine.anchor_goal_rates_split(1.8, 1.0, 1.6, 1.1, params, params.market_weight, params.market_weight)
    assert split[0] == pytest.approx(single[0]) and split[1] == pytest.approx(single[1])
    total_only = engine.anchor_goal_rates_split(1.8, 1.0, 1.6, 1.1, params, 0.5, 1.0)
    # Supremazia tutta dal mercato: il rapporto λ/μ resta quello del mercato.
    assert total_only[0] / total_only[1] == pytest.approx(1.6 / 1.1)


def test_v2_options_are_off_unless_switched_on():
    config = config_from_input(parse_match_input(VALID), simulations=4000, seed=5)
    assert config.v2.rest_active is False and config.v2.uncertainty_active is False
    base = engine.final_goal_rates(config)[:2]
    rested = replace(config, rest_days=(7, 3), v2=replace(config.v2, rest_active=True, rest_per_day=0.1, rest_short=0.05))
    lam, mu = engine.final_goal_rates(rested)[:2]
    factor = engine.rest_factor((7, 3), rested.v2)
    assert factor == pytest.approx(np.exp(0.1 * 4 / 7 + 0.05))
    assert lam == pytest.approx(base[0] * factor) and mu == pytest.approx(base[1] / factor)
    assert engine.rest_factor((7, 3), config.v2) == 1.0
    weighted = replace(config, league="I1", odds={"1": 2.0, "X": 3.4, "2": 3.8},
                       v2=replace(config.v2, league_weights_active=True, league_weights={"I1": (0.6, 1.0)}))
    assert engine.final_goal_rates(weighted)[2]["anchoring"]["league_weights"]["totale"] == 0.6


def test_parameter_uncertainty_keeps_the_means_and_widens_the_spread():
    config = config_from_input(parse_match_input(VALID), simulations=40_000, seed=8)
    plain = simulate_match(config)
    wide = simulate_match(replace(config, v2=replace(config.v2, uncertainty_active=True, sigma_goals=0.25,
                                                     sigma_corners=0.25, sigma_cards=0.25)))
    for key in ("lambda", "mu"):
        assert wide["model"][key] == plain["model"][key]
    plain_goals = np.array(plain["dashboard"]["goals_distribution"]["home"])
    wide_goals = np.array(wide["dashboard"]["goals_distribution"]["home"])
    goals = np.arange(len(plain_goals))
    mean = lambda dist: (goals * dist).sum() / dist.sum()
    var = lambda dist: (goals ** 2 * dist).sum() / dist.sum() - mean(dist) ** 2
    assert mean(wide_goals) == pytest.approx(mean(plain_goals), rel=0.03)
    assert var(wide_goals) > var(plain_goals) * 1.03


def test_recalibration_maps_keep_complements_and_reach_the_ev():
    mapping = {"metodo": "platt", "a": 0.2, "b": 1.0}
    params = ModelV2Params(recalibration_active=True, recalibration={"Over 2.5 gol": mapping,
                                                                     "Esatti": {"metodo": "isotonica", "x": [0, 1], "y": [0, 1]}})
    out, changed = engine.apply_recalibration({"Over 2.5 gol": 50.0, "Under 2.5 gol": 50.0, "1": 40.0}, params)
    assert changed == ["Over 2.5 gol"] and out["Over 2.5 gol"] == pytest.approx(100 / (1 + np.exp(-0.2)), abs=0.01)
    assert out["Over 2.5 gol"] + out["Under 2.5 gol"] == pytest.approx(100.0) and out["1"] == 40.0
    assert engine.apply_recalibration({"Over 2.5 gol": 50.0}, ModelV2Params())[1] == []
    config = config_from_input(parse_match_input(VALID), simulations=4000, seed=5)
    on = replace(config, odds={"Over 2.5 gol": 2.0}, v2=replace(config.v2, taratura=None, recalibration_active=True,
                                                                  recalibration={"Over 2.5 gol": mapping}))
    result = simulate_match(on)
    row = next(item for item in result["financial"]["markets"] if item["market"] == "Over 2.5 gol")
    assert row["simulated_probability_pct"] == pytest.approx(result["components"]["finale"]["Over 2.5 gol"], abs=0.01)
    assert result["recalibrated"] == ["Over 2.5 gol"]


def test_value_thresholds_block_the_green_below_the_typical_error():
    config = config_from_input(parse_match_input(VALID), simulations=4000, seed=5)
    result = simulate_match(replace(config, odds={"1": 50.0}))
    assert next(item for item in result["financial"]["markets"] if item["market"] == "1")["is_value"]
    strict = replace(config, odds={"1": 50.0}, v2=replace(config.v2, thresholds_active=True))
    import today

    original = today.ev_threshold
    try:
        today.ev_threshold = lambda selection, settings=None: 10_000.0
        row = next(item for item in simulate_match(strict)["financial"]["markets"] if item["market"] == "1")
    finally:
        today.ev_threshold = original
    assert row["ev_threshold_pct"] == 10_000.0 and not row["is_value"]


def test_platt_and_isotonic_maps_and_the_strict_rule():
    rng = np.random.default_rng(3)
    p = rng.uniform(0.05, 0.95, 4000)
    y = (rng.uniform(size=4000) < np.clip(p * 1.2, 0, 1)).astype(float)
    a, b = recalibration_check.fit_platt(p, y)
    calibrated = recalibration_check.apply_platt(p, a, b)
    assert abs(calibrated.mean() - y.mean()) < 0.01
    xs, ys = recalibration_check.fit_isotonic(p, y)
    assert all(later >= earlier for earlier, later in zip(ys, ys[1:]))
    better = v2common.strict((recalibration_check.binary_loss(p, y), 0.05),
                             (recalibration_check.binary_loss(calibrated, y), 0.01))
    assert better["tenuta"] and better["differenza"] < 0
    same = v2common.strict((np.ones(10), 0.01), (np.ones(10), 0.01))
    assert not same["tenuta"]


def test_absence_factor_nets_out_the_substitute_and_is_bounded():
    squad = [absences.SquadPlayer("Bomber", "attaccante", 900, 6.0, 1.0),
             absences.SquadPlayer("Riserva", "attaccante", 200, 0.6, 0.1),
             absences.SquadPlayer("Terzino", "difensore", 900, 0.5, 0.5),
             absences.SquadPlayer("Regista", "centrocampista", 900, 1.5, 2.0)]
    factor, details = absences.absence_factor(squad, ["bomber"], team_games=10)
    production = (7.0 + 0.7 + 1.0 + 3.5) / 10
    # Riserve dello stesso ruolo sotto 270 minuti: sostituto = riferimento di campionato per l'attaccante.
    expected_share = (0.7 - absences.LEAGUE_ROLE_RATE["attaccante"]) / production
    assert details[0]["Giocatore"] == "Bomber" and details[0]["Quota persa"] == pytest.approx(expected_share, abs=1e-3)
    assert factor == pytest.approx(max(1 - expected_share, 0.85))
    bench = [*squad, absences.SquadPlayer("Riserva 2", "attaccante", 200, 0.4, 0.1)]
    # Con 400 minuti di riserve il sostituto è la loro media per 90: (0.7 + 0.5) / 400 · 90.
    assert absences.substitute_rate(bench, "attaccante") == pytest.approx(1.2 / 400 * 90)
    lost_all, _ = absences.absence_factor(squad, ["Bomber", "Regista", "Terzino"], team_games=10)
    assert lost_all == 0.85
    assert absences.absence_factor(squad, ["Sconosciuto"], 10)[1][0]["Quota persa"] is None
    assert absences.role_of("F S") == "attaccante" and absences.role_of("D M S") == "difensore"
    assert absences.role_of("DMC") == "centrocampista" and absences.role_of("GK") is None


def test_scorers_v2_shrink_defenders_with_few_minutes_and_give_penalties_to_the_taker():
    params = scorers.ScorerParams(role_share={"difensore": 0.03, "centrocampista": 0.09, "attaccante": 0.2},
                                  prior_xg=10.0, penalty_share=0.08)
    lucky = scorers.Player("Difensore", 120, 3, 0.9, 1, "D S", npxg=0.9)
    team_npxg90 = 1.5
    share = scorers.share_v2(lucky, team_npxg90, params, taker=None)
    old = scorers.share(lucky, team_npxg90)
    assert share < 0.1 < old
    striker = scorers.Player("Punta", 2000, 25, 14.0, 12, "F S", npxg=11.0, penalty_goals=4)
    assert scorers.penalty_taker([lucky, striker]) == "Punta"
    with_penalties = scorers.share_v2(striker, team_npxg90, params, taker="Punta")
    without = scorers.share_v2(striker, team_npxg90, params, taker=None)
    assert with_penalties - without == pytest.approx(0.08, abs=1e-9)


def test_player_check_probability_uses_poisson_thinning():
    rows = pd.DataFrame({"role": ["attaccante"], "npxg": [5.0], "taker": [False], "team_npxg": [15.0], "team_games": [10],
                         "minutes": [900.0], "apps": [10], "lambda_team": [1.5]})
    theta = np.array([0.03, 0.09, 0.2, 2.0, 0.0])
    share = (5.0 + 2.0 * 0.2) / (1.5 * 10 + 2.0)
    assert new_probability(rows, theta)[0] == pytest.approx(1 - np.exp(-1.5 * share))
