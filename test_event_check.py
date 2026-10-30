"""Fase AK, stadio 14: logica del banco fuori campione (``tools.event_check``) su dati sintetici."""

import numpy as np
import pandas as pd
import pytest

from tools import event_check as ec


def _rows():
    return pd.DataFrame({
        "home_goals": [2, 0, 1], "away_goals": [1, 0, 3], "home_ht_goals": [1, 0, 0], "away_ht_goals": [1, 0, 2],
        "home_corners": [6, 3, 2], "away_corners": [4, 3, 9], "home_yellows": [2, 1, 3], "away_yellows": [1, 0, 2],
        "home_reds": [0, 0, 1], "away_reds": [0, 0, 0]})


def test_esiti_reali_dei_mercati():
    observed = ec.observed_events(_rows())
    assert observed["1X2 1T"].tolist() == [1, 1, 2] and observed["1X2 2T"].tolist() == [0, 1, 1]
    assert observed["Over 9.5 corner"].tolist() == [1, 0, 1]
    assert observed["Casa Over 4.5 corner"].tolist() == [1, 0, 0]
    # Punti con la regola Eurobet: 3 gialli + 1 rosso = 5 per la casa nella terza partita.
    assert observed["Casa Over 2.5 cartellini"].tolist() == [0, 0, 1] and observed["1X2 cartellini"].tolist() == [0, 0, 0]
    assert observed["Over 2.5 gol & Over 9.5 corner"].tolist() == [1, 0, 1]
    assert observed["2 & 1 corner"].tolist() == [0, 0, 0] and observed["Under 2.5 gol & Under 9.5 corner"].tolist() == [0, 1, 0]
    assert set(observed) == {key for group in ec.GROUPS for key in ec._market_keys(group)}


def test_probabilita_dai_campioni_compressi():
    bits = {"Over 2.5 gol": np.array([1, 1, 0, 0], bool), "Over 9.5 corner": np.array([1, 0, 1, 0], bool)}
    result = {"sample_size": 4, "event_samples": {key: np.packbits(value) for key, value in bits.items()}}
    assert ec._mask(result, "Over 2.5 gol & Over 9.5 corner").tolist() == [True, False, False, False]


def test_confronto_appaiato_e_medie_per_gruppo():
    observed = {key: np.array([0, 1] * 50) if key not in ("1X2 1T", "1X2 2T", "1X2 corner", "1X2 cartellini")
                else np.array([0, 1, 2, 0] * 25) for group in ec.GROUPS for key in ec._market_keys(group)}
    flat = {key: [np.array([0.5, 0.5]) if len(value) == 100 and key not in ("1X2 1T", "1X2 2T", "1X2 corner", "1X2 cartellini")
                  else np.array([1 / 3] * 3)] * 100 for key, value in observed.items()}
    sharp = {key: [np.array([0.4, 0.6]) if i % 2 else np.array([0.6, 0.4]) for i in range(100)]
             if len(values[0]) == 2 else values for key, values in flat.items()}
    before, after = ec.score(flat, observed), ec.score(sharp, observed)
    assert before["Over 9.5 corner"]["log_loss"] == pytest.approx(np.log(2))
    mean, error = ec.paired(before, after, "media corner")
    assert mean < 0 and error == pytest.approx(0.0, abs=1e-12)
    assert after["media"]["log_loss"] < before["media"]["log_loss"]


def test_risultati_parziali_e_ripresa(tmp_path):
    output = {"position": 3, "estrazione": {"gh": 1.0}, "avvisi": [],
              **{variant: {"probabilita": {"Over 9.5 corner": np.array([0.4, 0.6])}, "secondi": 1.5, "simulazioni": 20000,
                           "medie": (9.8, 4.1)} for variant in ec.VARIANTS}}
    line = ec._to_json(output, "2021-09-12|Roma|Lazio")
    (tmp_path / "I1.jsonl").write_text(line + "\n" + line[:40] + "\n", encoding="utf-8")   # seconda riga troncata
    done = ec.load_partial("I1", tmp_path)
    assert list(done) == ["2021-09-12|Roma|Lazio"]
    back = done["2021-09-12|Roma|Lazio"]
    assert back["motore a eventi"]["probabilita"]["Over 9.5 corner"].tolist() == [0.4, 0.6]
    assert back["motore attuale"]["medie"] == (9.8, 4.1) and ec.load_partial("E0", tmp_path) == {}
    assert ec.row_key({"date": "2021-09-12 20:45", "home_team": "Roma", "away_team": "Lazio"}) == "2021-09-12|Roma|Lazio"
