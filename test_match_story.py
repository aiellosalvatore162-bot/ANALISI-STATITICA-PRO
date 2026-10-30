"""Fase AK, stadio 15: «Vedi come andrà» (``match_story``) e somme per passo del motore a eventi."""

import dataclasses

import numpy as np
import pytest

import engine
import event_engine as ee
import match_story
from test_event_engine import _engine_config


def test_somme_per_fascia_uguali_ai_totali():
    params = ee.load("I1")
    rng = np.random.default_rng(3)
    n = 20_000
    sample = ee.simulate_adaptive(rng, ee.TeamInput(1.6, first_share=0.45), ee.TeamInput(1.1, first_share=0.45), params,
                                  maximum=n, batch=10_000, minimum=n, scores=(rng.poisson(1.6, n), rng.poisson(1.1, n)))
    timeline = ee.timeline_summary(sample)
    bands = timeline["fasce"]
    assert [row["fascia"] for row in bands] == ["0-15", "15-30", "30-45", "45-60", "60-75", "75-90"]
    assert sum(row["corners_home"] for row in bands) == pytest.approx(sample["corners_home"].mean(), abs=1e-3)
    assert sum(row["goals_away"] for row in bands) == pytest.approx(sample["goals_away"].mean(), abs=1e-3)
    assert sum(row["yellows_home"] for row in bands) == pytest.approx(
        (sample["yellows_home"] + sample["double_yellows_home"]).mean(), abs=1e-3)
    assert sum(row["shots_away"] for row in bands) == pytest.approx(sample["shots_away"].sum(axis=1).mean(), abs=1e-3)
    assert sum(timeline["primo_gol"].values()) == pytest.approx(1.0, abs=1e-3)
    assert len(timeline["gol_nel_passo"]["probabilita"]) == 18 and 0 < timeline["almeno_un_rosso"] < 1


def test_etichetta_del_motore_attivo():
    off = engine.EventEngineParams()
    assert "motore attuale" in match_story.engine_label(off) and "illustrativo" in match_story.engine_label(off)
    corner = engine.EventEngineParams(active=True, markets=("corner",))
    label = match_story.engine_label(corner)
    assert "motore a eventi per corner" in label and "cartellini dal motore attuale" in label
    full = match_story.engine_label(engine.EventEngineParams(active=True))
    assert "gol del primo e secondo tempo, corner, cartellini" in full and "dal motore attuale" not in full


def test_andamento_illustrativo_con_motore_spento():
    config = dataclasses.replace(_engine_config(), simulations=5_000)
    result = engine.simulate_match(config)
    assert result["event_engine"] == {"active": False}
    details = match_story.illustrative_run(config, simulations=5_000)
    data = match_story.story(result, config, cached=details)
    assert data["illustrativo"] and data["errore"] is None and "illustrativo" in data["motore"]
    # Stesse medie del motore attuale (vincolo di coerenza): i corner del racconto sono quelli della simulazione.
    total = sum(row["corners_home"] + row["corners_away"] for row in data["andamento"]["fasce"])
    assert total == pytest.approx(result["markets"]["corners"]["mean"], rel=0.05)
    assert len(data["frasi"]) == 4 and data["frasi"][0].startswith("Primo gol: più probabile tra il")
    table = match_story.band_table(data["andamento"], result)
    assert len(table) == 6 and table[0]["Minuti"] == "0-15'"
    assert match_story.goal_moments(data["andamento"])[0]["Minuti"] == "0-5'"


def test_andamento_dagli_stessi_percorsi_con_motore_acceso():
    config = _engine_config(active=True, batch=5_000, minimum=10_000, pilot=5_000, markets=("corner",))
    result = engine.simulate_match(dataclasses.replace(config, simulations=10_000))
    data = match_story.story(result, config)
    assert not data["illustrativo"] and data["andamento"] is result["event_engine"]["andamento"]
    assert "motore a eventi per corner" in data["motore"]


def test_errore_spiegato_senza_configurazione():
    data = match_story.story({"event_engine": {"active": False}}, None)
    assert data["errore"] and "riesegui" in data["errore"]
