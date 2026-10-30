"""Fase AM: taratura per mercato."""
import numpy as np

import engine
import taratura
from engine import config_from_input, simulate_match
from parser import parse_match_input
from taratura import Taratura
from tools import taratura_check as tc

from test_parser import VALID

CFG = tc.DEFAULTS | {"soglia_isotonica_casi": 10**9}


def _synthetic(shift_season=None):
    rng = np.random.default_rng(1)
    seasons = np.repeat(["2021", "2122", "2223", "2324"], 800)
    p = rng.uniform(0.2, 0.9, len(seasons))
    y = (rng.uniform(size=len(seasons)) < np.clip(p * 0.9, 0, 1)).astype(float)
    if shift_season:
        y[seasons == shift_season] = 1 - y[seasons == shift_season]
    return p, y, seasons


def test_walk_forward_non_usa_dati_futuri():
    p, y, seasons = _synthetic()
    p2, y2, _ = _synthetic(shift_season="2223")
    first, _ = tc.walk_forward(p, y, seasons, CFG)
    second, _ = tc.walk_forward(p2, y2, seasons, CFG)
    until = np.isin(seasons, ["2021", "2122", "2223"])
    assert np.allclose(first[until], second[until])    # cambiare gli esiti di una stagione non tocca la sua correzione né le precedenti
    assert not np.allclose(first[seasons == "2324"], second[seasons == "2324"])


def test_mappe_monotone_e_con_limite():
    p, y, _ = _synthetic()
    for cfg in (CFG, CFG | {"soglia_isotonica_casi": 100}):
        mapping = tc.fit_map(p, y, cfg)
        grid = np.linspace(0.01, 0.99, 99)
        out = tc.apply_map(grid, mapping, cfg["limite_correzione_pp"])
        raw = np.array([engine.recalibrate(100 * v, mapping) / 100 for v in grid])
        assert np.all(np.diff(raw) >= -1e-9)
        assert np.all(np.abs(out - grid) <= cfg["limite_correzione_pp"] / 100 + 1e-9)
    assert tc.fit_map(p[:50], y[:50], CFG) is None     # pochi casi: nessuna taratura


def test_file_di_configurazione_coerente():
    loaded = taratura.load()
    assert loaded.attiva and loaded.mercati
    for key, item in loaded.mercati.items():
        mapping = item.get("mappa")
        if mapping and mapping["metodo"] == "isotonica":
            assert np.all(np.diff(mapping["y"]) >= -1e-9), key
        if mapping and mapping["metodo"] == "platt":
            assert mapping["b"] > 0, key
        assert loaded.status(key).startswith(("tarato (", "non tarato", "derivato"))


def _fake():
    shrink = {"metodo": "platt", "a": 0.0, "b": 0.8}
    markets = {key: {"mappa": shrink, "metodo": "platt", "casi": 100} for key in
               ("1", "X", "2", "Over 2.5 gol", "1 + Over 2.5", "Over 1.5 gol")}
    return Taratura(attiva=True, parametri={"limite_correzione_pp": 15.0}, mercati=markets)


def test_1x2_somma_100_e_complementari_dopo_la_taratura():
    pct = {"1": 52.0, "X": 25.0, "2": 23.0, "1X": 77.0, "X2": 48.0, "12": 75.0, "Over 2.5 gol": 61.0,
           "Under 2.5 gol": 39.0, "Over 1.5 gol": 83.0, "Under 1.5 gol": 17.0, "1 + Over 2.5": 40.0,
           "Esatti 1-0/0-1/0-0": 17.0}
    out, changed, _ = _fake().apply(pct)
    assert abs(out["1"] + out["X"] + out["2"] - 100) < 0.05
    assert out["Over 2.5 gol"] != pct["Over 2.5 gol"]
    assert abs(out["Over 2.5 gol"] + out["Under 2.5 gol"] - 100) < 0.01
    assert "Under 2.5 gol" in changed


def test_combo_non_supera_le_componenti():
    t = Taratura(attiva=True, parametri={"limite_correzione_pp": 15.0}, mercati={
        "1 + Over 2.5": {"mappa": {"metodo": "platt", "a": 2.0, "b": 1.0}, "metodo": "platt", "casi": 10}})
    out, _, _ = t.apply({"1": 30.0, "Over 2.5 gol": 55.0, "1 + Over 2.5": 25.0})
    assert out["1 + Over 2.5"] <= min(out["1"], out["Over 2.5 gol"])


def test_correzione_esorbitante_limitata_con_avviso():
    t = Taratura(attiva=True, parametri={"limite_correzione_pp": 5.0}, mercati={
        "Goal": {"mappa": {"metodo": "platt", "a": 2.0, "b": 1.0}, "metodo": "platt", "casi": 10}})
    out, _, warnings = t.apply({"Goal": 50.0})
    assert out["Goal"] == 55.0 and warnings


def test_simulazione_mostra_percentuali_tarate_e_coerenti():
    result = simulate_match(config_from_input(parse_match_input(VALID), simulations=4000, seed=5))
    assert result["taratura"]["attiva"]
    one = result["markets"]["1x2"]
    assert abs(sum(m["percentage"] for m in one.values()) - 100) < 0.2
    ou = result["markets"]["over_under"]
    assert abs(ou["Over_2.5"]["percentage"] + ou["Under_2.5"]["percentage"] - 100) < 0.2
    # nessuna sovrapposizione: un mercato tarato non passa anche dalla ricalibrazione della fase P
    again = simulate_match(config_from_input(parse_match_input(VALID), simulations=4000, seed=5))
    assert again["markets"]["1x2"] == one


def test_etichette_e_stato():
    loaded = taratura.load()
    assert loaded.status("Zzz") == "non tarato"
    label = loaded.label("Over 2.5 gol", 65.0)
    assert label in ("verificata", "poco verificata", "non affidabile")
    assert loaded.table("Over 2.5 gol")
