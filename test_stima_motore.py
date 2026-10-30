"""Fase AK, stadio 2: stima del motore a eventi (dati sintetici, nessuna rete) e coerenza dei file di configurazione."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import referee_stats
import tactical_dictionary
from tools import stima_motore as stima

ROOT = Path(__file__).resolve().parent


def _shot(**fields):
    return {"m": 10, "p": 1, "s": "h", "xg": 0.1, "g": False, "t": "Open Play", "b": "Right Foot", "pp": "Regular Play",
            "o": "Off T", "area": True, "c": "centro", "cross": False, **fields}


def test_tipo_di_tiro_con_precedenza():
    assert stima.shot_type(_shot(t="Penalty", pp="From Corner")) == "rigore"
    assert stima.shot_type(_shot(t="Free Kick", area=False)) == "palla_inattiva"
    assert stima.shot_type(_shot(pp="From Corner", b="Head", cross=True)) == "palla_inattiva"
    assert stima.shot_type(_shot(pp="From Free Kick")) == "azione"  # possesso nato da una punizione qualsiasi
    assert stima.shot_type(_shot(pp="From Counter", area=False)) == "transizione"
    assert stima.shot_type(_shot(area=False)) == "fuori_area"
    assert stima.shot_type(_shot(b="Head", cross=True)) == "testa_da_cross"
    assert stima.shot_type(_shot(b="Head")) == "azione"


def _match():
    return {"id": 1, "shots": [_shot(m=20, g=True), _shot(m=20, s="a"), _shot(m=50, p=2, s="a", g=True),
                               _shot(m=80, p=2, s="a")],
            "own_goals": [{"minute": 70, "period": 2, "h_a": "h"}], "corners": [{"m": 85, "p": 2, "s": "a", "o": "tiro"}],
            "fouls": [{"m": 10, "p": 1, "s": "a", "card": "Yellow Card"}], "cards": [], "last_minute": {1: 46, 2: 93}}


def test_stato_di_partita_ricostruito_dai_gol():
    cells = stima.state_cells(_match())
    assert [side for _, _, side in stima.goal_times(_match())] == ["h", "a", "h"]
    minutes = cells.groupby("side")["esposizione"].sum()
    assert minutes["h"] == pytest.approx(47 + 49) and minutes["a"] == pytest.approx(47 + 49)
    home = cells[cells["side"] == "h"].set_index(["fascia", "stato"])
    away = cells[cells["side"] == "a"].set_index(["fascia", "stato"])
    assert home.loc[("0-30", 0), "tiri"] == 1  # il tiro che segna conta prima del gol
    assert away.loc[("0-30", 0), "tiri"] == 1  # anche il tiro avversario dello stesso minuto: prima del gol
    assert away.loc[("0-30", -1), "tiri"] == 0 and away.loc[("0-30", -1), "esposizione"] == pytest.approx(9.5)
    assert away.loc[("75-90", -1), "tiri"] == 1 and away.loc[("75-90", -1), "corner"] == 1
    assert away.loc[("0-30", 0), "gialli"] == 1
    assert home.loc[("30-60", 1), "esposizione"] == pytest.approx(17 + 5.5)  # 30-47 nel primo tempo e 45-50.5 nel secondo
    assert cells["stato"].between(-2, 2).all()


def test_effetti_dello_stato_ritrovati_su_dati_simulati():
    rng = np.random.default_rng(3)
    truth = {-2: 1.4, -1: 1.2, 0: 1.0, 1: 0.7, 2: 0.5}
    bands = {"0-30": 1.0, "30-60": 1.1, "60-75": 1.2, "75-90": 1.3}
    rows = []
    for match in range(3000):
        base = rng.gamma(4, 0.25 / 4)
        for band, factor in bands.items():
            for state in rng.choice(list(truth), size=2, replace=False):
                exposure = float(rng.uniform(3, 15))
                rows.append({"match": match, "side": "h", "fascia": band, "stato": int(state), "esposizione": exposure,
                             "tiri": rng.poisson(base * factor * truth[int(state)] * exposure)})
    states, fitted_bands = stima.fit_state_effects(pd.DataFrame(rows), "tiri")
    for state, value in truth.items():
        assert states[state] == pytest.approx(value, rel=0.08)
    assert fitted_bands["75-90"] == pytest.approx(1.3, rel=0.08)


def test_regressione_di_poisson_ritrova_il_beta():
    rng = np.random.default_rng(5)
    n = 6000
    score = rng.choice([-1.0, 0.0, 1.0], n)
    other = rng.normal(size=n)
    offset = np.log(rng.uniform(0.7, 1.4, n))
    y = rng.poisson(np.exp(0.8 + 0.2 * score - 0.1 * other + offset))
    beta, se = stima.poisson_fit(y.astype(float), np.column_stack([np.ones(n), other, score]), offset, np.arange(n) // 2)
    assert beta[2] == pytest.approx(0.2, abs=3 * se[2]) and beta[1] == pytest.approx(-0.1, abs=3 * se[1])
    assert 0.005 < se[2] < 0.05


def test_arbitri_shrinkage_stimato_e_verifica_fuori_campione():
    rng = np.random.default_rng(9)
    effects = rng.normal(0, 2.0, 30)  # tau² = 4, sigma² = 16 → k = 4
    rows = [{"league": "L", "season": season, "referee": f"A{ref}", "fouls": 24 + effects[ref] + rng.normal(0, 4.0)}
            for season in range(5) for ref in range(30) for _ in range(20)]
    data = pd.DataFrame(rows)
    parts = referee_stats.estimate(data, {"falli": "fouls"})["L"]["falli"]
    assert parts["stimabile"] and parts["k"] == pytest.approx(4.0, rel=0.35)
    assert parts["quota_varianza_arbitro"] == pytest.approx(0.2, abs=0.06)
    assert parts["fuori_campione"]["miglioramento_pct"] > 10
    flat = data.assign(fouls=24 + rng.normal(0, 4.0, len(data)))
    assert referee_stats.estimate(flat, {"falli": "fouls"})["L"]["falli"]["quota_varianza_arbitro"] < 0.02


def test_shrinkage_arbitro_verso_la_media():
    history = pd.DataFrame({"referee": ["A"] * 5, "y": [2.0] * 5})
    assert referee_stats.shrunk_effect(history, "A", 5.0) == pytest.approx(1.0)
    assert referee_stats.shrunk_effect(history, "B", 5.0) == 0.0
    assert referee_stats.shrunk_effect(history, "A", None) == 0.0


def test_dizionario_stimato_coerente():
    dictionary = tactical_dictionary.load()
    assert dictionary["stima"]["strumento"] == "python -m tools.stima_motore"
    for term, spec in dictionary["termini"].items():
        for effect in spec["effetti"]:
            if effect["beta"] is None:
                assert effect.get("motivo"), (term, effect["tasso"])  # mai null senza motivo
                continue
            low, high = effect["intervallo"]
            assert effect["n"] > 0 and "StatsBomb" in effect["fonte"]
            if low <= 0 <= high:
                assert effect["beta"] == 0.0  # non distinguibile da zero → nessun effetto
            else:
                assert low <= effect["beta"] <= high


def test_motore_eventi_config():
    config = json.loads((ROOT / "config" / "motore_eventi.json").read_text(encoding="utf-8"))
    assert "Bundesliga" not in config["xg_per_tipo"] and config["campionati"]["Bundesliga"].startswith("comune")
    common = config["xg_per_tipo"]["comune"]
    assert set(common) == set(stima.SHOT_TYPES)
    assert sum(row["quota"] for row in common.values()) == pytest.approx(1.0)
    assert common["rigore"]["gol_per_tiro"] > common["azione"]["gol_per_tiro"] > common["fuori_area"]["gol_per_tiro"]
    states = config["stato_partita"]["quantita"]["tiri"]["stato"]
    assert states["0"]["moltiplicatore"] == pytest.approx(1.0)
    assert states["-1"]["moltiplicatore"] > 1.0 > states["1"]["moltiplicatore"]
    assert all(not row["attiva"] for row in config["incroci"].values())


def test_motivo_nelle_righe_del_profilo():
    dictionary = tactical_dictionary.load()
    _, rows, _ = tactical_dictionary.apply_profile({"possesso": "palla a terra"}, dictionary)
    by_rate = {row["tasso"]: row for row in rows}
    assert by_rate["quota_possesso"]["moltiplicatore"] == pytest.approx(math.exp(0.1153), rel=0.05)
    assert "non distinguibile da zero" in by_rate["tiri_transizione"]["stato"]
    assert by_rate["tiri_transizione"]["moltiplicatore"] == 1.0
