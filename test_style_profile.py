"""Fase AD: profilo di stile, shrinkage, winsorizzazione, forma reale nel motore, banco senza fughe dal futuro."""

from dataclasses import replace
import io

import numpy as np
import pandas as pd
import pytest
from openpyxl import load_workbook

import engine
import style_profile as sp
from match_memory import day_workbook
from parser import parse_match_input
from test_engine import VALID
from tools import backtest_wf

PROXY = {"a_tiri_in_porta": 0.30, "b_altri_tiri": 0.06}
TEAMS = ["Alfa", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]


def raw_matches(seed: int = 3, rounds: int = 6) -> pd.DataFrame:
    """Campionato sintetico: ogni coppia gioca in casa e in trasferta più volte, una giornata ogni 7 giorni."""
    rng = np.random.default_rng(seed)
    rows, day = [], pd.Timestamp("2025-08-01")
    for _ in range(rounds):
        for home in TEAMS:
            for away in TEAMS:
                if home == away:
                    continue
                shots_h, shots_a = rng.integers(6, 20), rng.integers(5, 16)
                rows.append({
                    "league": "I1", "season": "2526", "date": day, "home_team": home, "away_team": away,
                    "home_goals": int(rng.poisson(1.5)), "away_goals": int(rng.poisson(1.1)),
                    "home_shots": shots_h, "away_shots": shots_a, "home_sot": shots_h // 3, "away_sot": shots_a // 3,
                    "home_fouls": rng.integers(8, 16), "away_fouls": rng.integers(8, 16),
                    "home_corners": rng.integers(3, 9), "away_corners": rng.integers(2, 8),
                    "home_yellows": rng.integers(0, 4), "away_yellows": rng.integers(0, 4),
                })
                day += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


@pytest.fixture()
def store():
    return sp.StyleStore(sp.build_table(raw_matches(), None, PROXY))


def test_profile_documents_value_sample_and_source(store):
    profile = sp.get_style_params("Alfa", "2026-02-01", True, store)
    assert profile["campionato"] == "I1" and profile["campo"] == "home"
    real = profile["forma_reale"]
    assert real["campione"] == 8 and "proxy dai tiri" in real["fonte"] and "shrinkage 8/(8+6)" in real["fonte"]
    for name in sp.MATCH_PARAMS:
        item = profile["parametri"][name]
        assert set(item) == {"valore", "campione", "fonte", "avviso"} and item["campione"] <= 8
    assert profile["parametri"]["cross"]["valore"] is None        # non disponibile: dichiarato, mai inventato
    assert profile["parametri"]["tiri_concessi"]["valore"] is not None
    assert profile["parametri"]["ppda"]["valore"] is None         # senza Understat il PPDA non esiste: mai inventato
    assert "insufficiente" in profile["parametri"]["ppda"]["fonte"]


def test_shrinkage_is_n_over_n_plus_k_towards_the_league(store):
    when = pd.Timestamp("2026-02-01")
    key = sp.canonical_key("Alfa")
    value = sp._team_param(store, "I1", key, "home", when, "tiri_concessi")
    league_mean = store.league_stats("I1", "home", "tiri_concessi", when)[0]
    dates, group = store._teams[("I1", key, "home")]
    end = int(np.searchsorted(dates, np.datetime64(when), side="left"))
    last = group["tiri_concessi"].to_numpy(float)[end - 8:end]
    weights = 0.5 ** (np.arange(7, -1, -1) / store.config["emivita_gare"])
    k = store.config["shrinkage_k"]["blocco_pressing"]
    team_mean = float(np.average(np.clip(last, *store.league_stats("I1", "home", "tiri_concessi", when)[1:3]), weights=weights))
    assert value.campione == 8
    assert value.valore == pytest.approx((8 * team_mean + k * league_mean) / (8 + k))
    # finestra di 3 gare: il peso della squadra scende a 3/(3+k)
    short = sp.StyleStore(store.table, config=dict(store.config, finestra_gare=3))
    small = sp._team_param(short, "I1", key, "home", when, "tiri_concessi")
    low, high = short.league_stats("I1", "home", "tiri_concessi", when)[1:3]
    last3 = np.clip(last[-3:], low, high)
    mean3 = float(np.average(last3, weights=0.5 ** (np.arange(2, -1, -1) / store.config["emivita_gare"])))
    assert small.campione == 3 and small.valore == pytest.approx((3 * mean3 + k * league_mean) / (3 + k))


def test_profile_never_uses_matches_on_or_after_the_date(store):
    when = pd.Timestamp("2026-02-01")
    before = sp.get_style_params("Beta", when, False, store)
    altered = store.table.copy()
    future = altered["date"] >= when
    altered.loc[future, ["xg_diff", "tiri_concessi", "falli_fatti", "quota_tiri"]] = 999.0
    other = sp.StyleStore(altered)
    after = sp.get_style_params("Beta", when, False, other)
    assert after["forma_reale"]["valore"] == pytest.approx(before["forma_reale"]["valore"])
    assert after["parametri"]["tiri_concessi"]["valore"] == pytest.approx(before["parametri"]["tiri_concessi"]["valore"])


def test_winsorization_warns_only_when_an_outlier_is_clipped(store):
    when = pd.Timestamp("2026-02-01")
    clean = sp.get_style_params("Gamma", when, True, store)
    assert not any("falli_fatti" in message for message in clean["avvisi"])
    table = store.table.copy()
    mask = (table["key"] == sp.canonical_key("Gamma")) & (table["venue"] == "home") & (table["date"] < when)
    last = table[mask].sort_values("date").index[-1]
    table.loc[last, "falli_fatti"] = 500.0                      # dato sbagliato
    other = sp.StyleStore(table)
    bad = sp.get_style_params("Gamma", when, True, other)
    item = bad["parametri"]["falli_fatti"]
    _, _, high, _ = other.league_stats("I1", "home", "falli_fatti", when)
    assert item["avviso"] and "percentile" in item["avviso"] and any("falli_fatti" in m for m in bad["avvisi"])
    assert item["valore"] < high + 1                            # riportato al limite, non 500
    assert item["valore"] < 20


def test_component_can_be_switched_off(store):
    config = dict(store.config, componenti={**store.config["componenti"], "aggressivita": False})
    off = sp.StyleStore(store.table, config=config)
    profile = sp.get_style_params("Alfa", "2026-02-01", True, off)
    assert profile["parametri"]["falli_fatti"]["valore"] is None
    assert "spenta" in profile["parametri"]["falli_fatti"]["fonte"]
    assert profile["parametri"]["tiri_concessi"]["valore"] is not None


def test_unknown_team_is_reported_not_invented(store):
    profile = sp.get_style_params("Squadra Inesistente", "2026-02-01", True, store)
    assert profile["forma_reale"] is None and "Nessuna gara" in profile["avvisi"][0]


# --- Motore ----------------------------------------------------------------------------------------------------------

def _config(**changes):
    base = engine.config_from_input(parse_match_input(VALID), simulations=2000)
    goal = replace(base.goal_params, form_weight=0.2)
    return replace(base, goal_params=goal, **changes)


STYLE = {"home": {"forma_reale": 0.5, "n_gare": 4}, "away": {"forma_reale": -0.3, "n_gare": 8}}


def test_real_form_replaces_the_wdl_covariate_and_is_in_the_ledger():
    model = engine.StyleModelParams(True, 0.3, 6.0)
    on = _config(style=STYLE, style_model=model)
    lam, mu, ledger = engine.expected_goals(on)
    assert ledger["forma_reale"]["usata"] and ledger["forma_reale"]["phi"] == 0.3
    assert "forma reale" in ledger["formula"]
    # AL POSTO della forma W-D-L: cambiare la stringa W-D-L non cambia nulla
    flipped = replace(on, home=replace(on.home, form="L-L-L-L-L"), away=replace(on.away, form="W-W-W-W-W"))
    assert engine.expected_goals(flipped)[:2] == pytest.approx((lam, mu))
    # opzione spenta o stile mancante: come prima, con la forma W-D-L
    off = _config(style=STYLE, style_model=engine.StyleModelParams(False))
    no_style = _config(style=None, style_model=model)
    reference = engine.expected_goals(_config())
    assert engine.expected_goals(off)[:2] == pytest.approx(reference[:2])
    assert engine.expected_goals(no_style)[:2] == pytest.approx(reference[:2])
    assert no_style and engine.expected_goals(no_style)[2]["forma_reale"]["usata"] is False
    # una forma reale migliore in casa alza i gol attesi della casa e abbassa quelli dell'ospite
    plain = _config(style={"home": {"forma_reale": 0.0, "n_gare": 8}, "away": {"forma_reale": 0.0, "n_gare": 8}}, style_model=model)
    lam0, mu0, _ = engine.expected_goals(plain)
    assert lam > lam0 and mu < mu0


def test_xg_weight_rises_with_few_matches():
    base = _config(style_model=engine.StyleModelParams(True, 0.0, 6.0))
    poor = replace(base, style={"home": {"forma_reale": 0.0, "n_gare": 1}, "away": {"forma_reale": 0.0, "n_gare": 1}})
    rich = replace(base, style={"home": {"forma_reale": 0.0, "n_gare": 30}, "away": {"forma_reale": 0.0, "n_gare": 30}})
    ledger = engine.expected_goals(poor)[2]["forma_reale"]["quota_xg_attacco"]
    assert ledger["casa"] > engine.expected_goals(rich)[2]["forma_reale"]["quota_xg_attacco"]["casa"] - 1e-12
    assert engine.expected_goals(poor)[:2] != pytest.approx(engine.expected_goals(rich)[:2])


# --- Banco walk-forward -----------------------------------------------------------------------------------------------

def _bench_frame(n: int = 900, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.Timestamp("2024-08-01") + pd.to_timedelta(np.sort(rng.integers(0, 600, n)), unit="D")
    home, away = rng.normal(0, 0.4, n), rng.normal(0, 0.4, n)
    return pd.DataFrame({"date": dates, "home_forma_reale": home, "away_forma_reale": away,
                         "home_goals": rng.poisson(1.5, n), "away_goals": rng.poisson(1.1, n)})


def test_walkforward_phi_ignores_the_future():
    features = _bench_frame()
    lam, mu = np.full(len(features), 1.5), np.full(len(features), 1.1)
    phi, history = backtest_wf.walkforward_phi(features, lam, mu, 0.01)
    cut = pd.Timestamp("2025-06-01")
    changed = features.copy()
    future = changed["date"] >= cut
    changed.loc[future, "home_goals"] = 9                      # il futuro cambia radicalmente
    changed.loc[future, "away_goals"] = 0
    phi_changed, _ = backtest_wf.walkforward_phi(changed, lam, mu, 0.01)
    before = (features["date"] < pd.Timestamp(cut.year, cut.month, 1)).to_numpy()
    assert np.allclose(phi[before], phi_changed[before])        # i mesi già passati non vedono il futuro
    assert not np.allclose(phi[~before], phi_changed[~before])  # il futuro invece sì, dal mese dopo
    assert all(value == 0.0 for month, value in history.items() if month < "2024-09")   # pochi dati: phi = 0


def test_forma_reale_columns_use_only_past_matches(store):
    matches = pd.DataFrame({"league": ["I1"], "date": [pd.Timestamp("2026-01-10")], "home_team": ["Alfa"], "away_team": ["Beta"]})
    columns = sp.forma_reale_columns(store, matches)
    table = store.table.copy()
    table.loc[table["date"] >= pd.Timestamp("2026-01-10"), "xg_diff"] = 50.0
    again = sp.forma_reale_columns(sp.StyleStore(table), matches)
    assert columns.loc[0, "home_forma_reale"] == pytest.approx(again.loc[0, "home_forma_reale"])
    assert columns.loc[0, "home_forma_n"] == 8


def test_market_table_has_all_markets_and_valid_probabilities():
    rng = np.random.default_rng(1)
    n = 60
    features = pd.DataFrame({
        "home_goals": rng.poisson(1.5, n), "away_goals": rng.poisson(1.1, n),
        "home_ht_goals": rng.poisson(0.7, n), "away_ht_goals": rng.poisson(0.5, n),
        "home_corners": rng.integers(2, 9, n), "away_corners": rng.integers(2, 8, n),
        "home_yellows": rng.integers(0, 4, n), "away_yellows": rng.integers(0, 4, n)})
    features["home_ht_goals"] = np.minimum(features["home_ht_goals"], features["home_goals"])
    features["away_ht_goals"] = np.minimum(features["away_ht_goals"], features["away_goals"])
    prediction = {"lambda": np.full(n, 1.5), "mu": np.full(n, 1.1), "corner_home": np.full(n, 5.5),
                  "corner_away": np.full(n, 4.5), "cards": np.full(n, 4.0)}
    table = backtest_wf.market_table(features, prediction)
    for name in ("1X2", "Over 2.5 gol", "GG", "1X2 1T", "Over 0.5 2T", "Corner Over 9.5", "Gialli Over 3.5",
                 "Casa Over 1.5 gol", "Corner Casa Over 4.5", "Over 2.5 + GG"):
        probability, outcome, mask = table[name]
        assert probability.shape[0] == n and np.allclose(probability.sum(axis=1), 1.0) and mask.all()
        assert set(np.unique(outcome)) <= {0, 1, 2}
    # combo ≤ ciascuna componente
    assert (table["Over 2.5 + GG"][0][:, 1] <= table["GG"][0][:, 1] + 1e-12).all()


# --- Foglio «Stile» ---------------------------------------------------------------------------------------------------

def test_style_sheet_in_the_day_excel(store):
    profiles = [sp.get_style_params("Alfa", "2026-02-01", True, store), sp.get_style_params("Beta", "2026-02-01", False, store)]
    rows = sp.sheet_rows(profiles)
    assert {row["Squadra"] for row in rows} == {"Alfa", "Beta"} and {row["Campo"] for row in rows} == {"casa", "trasferta"}
    assert {"forma_reale", "ppda", "cross"} <= {row["Parametro"] for row in rows}
    sheet = load_workbook(io.BytesIO(day_workbook([], [], style_rows=rows)))["Stile"]
    values = list(sheet.iter_rows(values_only=True))
    assert list(values[0]) == list(sp.SHEET_COLUMNS) and len(values) == len(rows) + 1
