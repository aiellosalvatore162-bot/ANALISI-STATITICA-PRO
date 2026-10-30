"""Fase AK, stadi 3-5: motore a eventi (stato della partita, azioni a passi, tiri e gol), solo simulazioni."""

import copy

import numpy as np
import pytest

import event_engine as ee
import tactical_dictionary

PARAMS = ee.load("E0")
N = 30_000


def dc_scores(n=N, seed=2, lam=1.6, mu=1.1):
    rng = np.random.default_rng(seed)
    return rng.poisson(lam, n), rng.poisson(mu, n)


def run(scores=None, home=None, away=None, seed=1, **kwargs):
    home = home or ee.TeamInput(1.6, first_share=0.45)
    away = away or ee.TeamInput(1.1, first_share=0.44)
    return ee.simulate(np.random.default_rng(seed), N, home, away, PARAMS, scores=scores, **kwargs)


def test_parametri_per_campionato_e_comune():
    assert PARAMS.source == "Premier League"
    assert ee.load("SP1").source == "La Liga" and ee.load("Serie A").source == "Serie A"
    bundesliga = ee.load("D1")
    assert bundesliga.source == "comune" and "Leverkusen" in bundesliga.note
    assert ee.load("Eredivisie").note == "parametri comune (Eredivisie non stimato)"
    assert ee.load(None).source == "comune"
    assert PARAMS.state_shots[ee.STATES.index(0)] == 1.0 and len(PARAMS.shots) == len(ee.SHOT_TYPES)


def test_stato_della_partita():
    with pytest.raises(ValueError, match="deve dividere 15"):
        ee.MatchState(10, 4)
    state = ee.MatchState(3, 5)
    state.add(np.array([0, 3, 1]), np.array([0, 0, 2]))
    assert state.state_index(True).tolist() == [2, 4, 1] and state.state_index(False).tolist() == [2, 0, 3]
    state.step = 9
    assert state.minute == 45 and not state.first_half and state.band == 1
    assert [ee._band_index(m) for m in (0, 29, 30, 60, 74, 75, 89)] == [0, 0, 1, 2, 2, 3, 3]


def test_tabelle_normalizzate_sulle_medie_stimate():
    tables = ee.build_tables(PARAMS, 1.0, np.ones(6), 5)
    weight = np.asarray(PARAMS.state_minutes) / np.sum(PARAMS.state_minutes)
    per_match = np.einsum("s,kst->k", weight, tables.shots)
    assert per_match == pytest.approx(PARAMS.shots, rel=1e-9)
    # Rigori senza effetti di stato e fascia; chi è sotto tira di più e meglio di chi è avanti.
    assert np.ptp(tables.shots[ee.PENALTY]) == 0 and np.ptp(tables.conversion[ee.PENALTY]) == 0
    azione = ee.SHOT_TYPES.index("azione")
    assert (tables.shots[azione, 1] > tables.shots[azione, 3]).all()
    assert (tables.conversion[azione, 1] > tables.conversion[azione, 3]).all()
    # Più tiri a fine partita che all'inizio (fasce stimate).
    assert tables.shots[azione, 2, -1] > tables.shots[azione, 2, 0]


def test_quota_del_primo_tempo_tarata():
    tables = ee.build_tables(PARAMS, 1.0, np.ones(6), 5, first_share=0.42)
    neutral = tables.goals[:, ee.STATES.index(0), :].sum(axis=0)
    assert neutral[:9].sum() / neutral.sum() == pytest.approx(0.42)
    plain = ee.build_tables(PARAMS, 1.0, np.ones(6), 5)
    assert neutral.sum() == pytest.approx(plain.goals[:, ee.STATES.index(0), :].sum())


def test_modo_punteggi_conserva_i_punteggi_dixon_coles():
    scores = dc_scores()
    out = run(scores)
    assert (out["goals_home"] == scores[0]).all() and (out["goals_away"] == scores[1]).all()
    assert (out["goals_by_type_home"].sum(axis=1) == scores[0]).all()
    assert (out["first_home"] <= out["goals_home"]).all() and (out["first_away"] <= out["goals_away"]).all()
    for side in ("home", "away"):
        assert (out[f"shots_{side}"] >= out[f"goals_by_type_{side}"]).all()
        assert (out[f"saved_{side}"] <= out[f"shots_{side}"] - out[f"goals_by_type_{side}"]).all()
    assert out["state_steps_home"].sum(axis=1).tolist() == [18] * N
    scored = (scores[0] + scores[1]) > 0
    assert ((out["first_goal_team"] > 0) == scored).all() and np.isnan(out["first_goal_minute"][~scored]).all()
    # Quota di gol nel primo tempo vicina a quella tarata (gli stati la spostano di poco).
    assert out["first_home"].sum() / scores[0].sum() == pytest.approx(0.45, abs=0.02)
    again = run(scores)
    assert (again["shots_home"] == out["shots_home"]).all()


def test_modo_libero_riscala_sui_gol_attesi():
    out = run()
    assert out["goals_home"].mean() == pytest.approx(1.6, abs=0.04)
    assert out["goals_away"].mean() == pytest.approx(1.1, abs=0.04)
    assert out["xg_home"].mean() == pytest.approx(out["goals_home"].mean(), rel=0.08)
    assert any(row["voce"] == "modo" and row["valore"] == "libero" for row in out["ledger"])


def test_chi_e_sotto_tira_di_piu():
    out = run(dc_scores())
    steps = out["state_steps_home"]
    # Partite in cui la casa è stata soprattutto sotto contro partite in cui è stata soprattutto avanti, a parità di gol.
    behind = steps[:, :2].sum(axis=1) >= 9
    ahead = steps[:, 3:].sum(axis=1) >= 9
    level = out["goals_home"] == out["goals_away"]
    shots = out["shots_home"].sum(axis=1) - out["goals_by_type_home"].sum(axis=1)
    assert shots[behind & level].mean() > shots[ahead & level].mean()


def test_buon_senso_partita_media():
    out = run(home=ee.TeamInput(1.35), away=ee.TeamInput(1.35))
    stats = ee.summary(out)
    assert 22 < stats["tiri_home"] + stats["tiri_away"] < 30
    assert stats["tiri_azione_home"] > stats["tiri_testa_da_cross_home"] > stats["tiri_rigore_home"]
    assert 0.05 < stats["nessun_gol"] < 0.09
    assert 25 < stats["minuto_primo_gol"] < 40
    assert out["possession_home"] == 0.5


def test_dizionario_sposta_solo_il_tipo_dichiarato():
    base = run(dc_scores())
    crossing = run(dc_scores(), home=ee.TeamInput(1.6, {"fasce_cross": "alto"}, 0.45))
    k = ee.SHOT_TYPES.index("testa_da_cross")
    ratio = crossing["shots_home"].mean(axis=0) / base["shots_home"].mean(axis=0)
    beta = next(e["beta"] for e in tactical_dictionary.load()["termini"]["fasce_cross"]["effetti"] if e["tasso"] == "tiri_da_cross")
    assert ratio[k] > 1.05
    others = [i for i in range(6) if i != k]
    # I gol restano gli stessi (Dixon-Coles): gli altri tipi cambiano di poco, il cross sale circa di exp(beta).
    assert ratio[k] == pytest.approx(np.exp(beta), rel=0.06)
    assert np.all(np.abs(ratio[others] - 1) < 0.04)
    assert crossing["dictionary_rows"]["casa"] and not crossing["warnings"]


def test_tiri_concessi_spostano_l_avversario():
    dictionary = copy.deepcopy(tactical_dictionary.load())
    for effect in dictionary["termini"]["altezza_linea"]["effetti"]:
        if effect["tasso"] == "tiri_transizione_concessi":
            effect["beta"] = 0.3
    own, _, _ = tactical_dictionary.apply_profile({"altezza_linea": "alta"}, dictionary)
    types = ee.type_multipliers({}, own, False)
    assert types[ee.SHOT_TYPES.index("transizione")] == pytest.approx(np.exp(0.3))
    assert np.delete(types, ee.SHOT_TYPES.index("transizione")) == pytest.approx(np.ones(5))
    # Blocco basso dell'avversario: conta solo «tiri_contro_blocco_basso» della squadra.
    assert ee._low_block({"altezza_linea": "bassa"}, dictionary) and not ee._low_block({"altezza_linea": "alta"}, dictionary)
    low = ee.type_multipliers({"tiri_contro_blocco_basso": 1.2}, {}, True)
    assert low[ee.SHOT_TYPES.index("azione")] == pytest.approx(1.2) and low[ee.SHOT_TYPES.index("rigore")] == 1.0


def test_possesso_e_avvisi():
    out = run(dc_scores(), home=ee.TeamInput(1.6, {"possesso": "palla a terra", "boh": "x"}),
              away=ee.TeamInput(1.1, {"possesso": "diretto"}))
    assert out["possession_home"] > 0.55
    assert any("boh" in warning and warning.startswith("casa") for warning in out["warnings"])


def test_punteggi_di_lunghezza_sbagliata():
    with pytest.raises(ValueError, match="uno per simulazione"):
        run((np.zeros(5, int), np.zeros(5, int)))


@pytest.mark.parametrize("step", [1, 3, 15])
def test_altri_passi(step):
    scores = dc_scores()
    out = run(scores, step_minutes=step)
    assert (out["goals_home"] == scores[0]).all() and out["state_steps_home"].sum(axis=1)[0] == 90 // step
