"""Fase AK, stadi 3-8: motore a eventi (stato della partita, azioni a passi, tiri e gol, corner, falli e cartellini)."""

import copy
import dataclasses

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


# ------------------------------------------------------------------------------------------------------- stadi 6-8


def test_parametri_di_corner_falli_e_cartellini():
    assert PARAMS.corners[0] == pytest.approx(1.047, abs=0.01) and PARAMS.fouls == pytest.approx(12.52, abs=0.01)
    assert PARAMS.referee_source == "football_data Premier League" and PARAMS.referee_k[1] > 50
    assert ee.load("I1").referee_source == "statsbomb_2015_16 Serie A"
    assert ee.load(None).referee_source == "mediana delle stime"
    # Uomo in meno: meno tiri, corner e falli; uomo in più: più tiri.
    assert PARAMS.men["tiri"][0] < 1 < PARAMS.men["tiri"][2] and PARAMS.men["falli"][0] < 1
    assert ee.men_factor(PARAMS, "tiri", np.array([-1, 0, 1])).tolist() == list(PARAMS.men["tiri"])
    assert ee.men_factor(PARAMS, "sconosciuta", np.array([1])).tolist() == [1.0]


def test_profili_dei_conteggi_normalizzati():
    weight = np.asarray(PARAMS.state_minutes) / np.sum(PARAMS.state_minutes)
    profile = ee.count_profile(PARAMS, PARAMS.state_fouls, PARAMS.band_fouls, 5)
    assert weight @ profile.sum(axis=1) == pytest.approx(1.0)
    ratio = ee.ratio_profile(PARAMS, PARAMS.state_yellow, PARAMS.band_yellow, PARAMS.state_fouls, PARAMS.band_fouls, 5)
    assert np.sum(weight[:, None] * profile * ratio) == pytest.approx(1.0)
    tables = ee.build_count_tables(PARAMS, 5)
    # Più gialli per fallo a fine partita e per chi è avanti di un gol.
    assert tables.yellow[2, -1] > tables.yellow[2, 0] and tables.yellow[3, 5] > tables.yellow[2, 5]


def test_medie_di_corner_falli_e_cartellini():
    out = run(dc_scores())
    stats = ee.summary(out)
    for side in ("home", "away"):
        assert stats[f"falli_{side}"] == pytest.approx(PARAMS.fouls, rel=0.05)
        cards = stats[f"gialli_{side}"] + stats[f"doppie_{side}"]
        assert cards == pytest.approx(PARAMS.yellow_per_foul * stats[f"falli_{side}"], rel=0.05)
        assert stats[f"corner_cross_{side}"] == pytest.approx(PARAMS.corners[0], rel=0.1)
        assert stats[f"corner_altro_{side}"] == pytest.approx(PARAMS.corners[1], rel=0.1)
        ratio = out[f"corners_by_origin_{side}"][:, 0].sum() / out[f"saved_{side}"].sum()
        assert ratio == pytest.approx(PARAMS.corner_per_saved, rel=0.03)
        assert (out[f"corners_by_origin_{side}"][:, 0] <= out[f"saved_{side}"].sum(axis=1)).all()
        assert (out[f"corners_first_{side}"] <= out[f"corners_{side}"]).all()
        assert (out[f"yellows_first_{side}"] <= out[f"yellows_{side}"]).all()
        # Seconda gialla solo per chi è già ammonito; rossi = diretti + doppie.
        assert (out[f"double_yellows_{side}"] <= out[f"yellows_{side}"]).all()
        assert (out[f"reds_{side}"] >= out[f"double_yellows_{side}"]).all()
        assert np.isnan(out[f"first_red_minute_{side}"][out[f"reds_{side}"] == 0]).all()
    total_corners = stats["corner_home"] + stats["corner_away"]
    assert 9.5 < total_corners < 12.5
    assert 2.5 < stats["gialli_home"] + stats["gialli_away"] < 4.0
    # Gialli più frequenti nel secondo tempo (fasce stimate).
    assert stats["gialli_1t_home"] < 0.45 * stats["gialli_home"]


def test_stato_del_punteggio_su_corner_e_falli():
    out = run(dc_scores())
    steps = out["state_steps_home"]
    behind, ahead = steps[:, :2].sum(axis=1) >= 9, steps[:, 3:].sum(axis=1) >= 9
    play = out["corners_by_origin_home"][:, 1:].sum(axis=1)
    assert play[behind].mean() > play[ahead].mean()
    assert out["fouls_home"][behind].mean() < out["fouls_home"][ahead].mean()


def test_espulsione_toglie_tiri_e_corner():
    params = dataclasses.replace(PARAMS, straight_red_per_foul=0.02)
    level = (np.ones(N, int), np.ones(N, int))
    out = ee.simulate(np.random.default_rng(4), N, ee.TeamInput(1.3), ee.TeamInput(1.3), params, scores=level)
    early = (out["first_red_minute_home"] < 30) & (out["reds_away"] == 0)
    clean = (out["reds_home"] == 0) & (out["reds_away"] == 0)
    misses = out["shots_home"].sum(axis=1) - out["goals_by_type_home"].sum(axis=1)
    assert early.sum() > 300
    assert misses[early].mean() < 0.9 * misses[clean].mean()
    assert out["corners_home"][early].mean() < out["corners_home"][clean].mean()
    assert out["corners_away"][early].mean() > out["corners_away"][clean].mean()


def test_arbitro_ristretto_verso_la_media():
    strict = ee.RefereeInput(matches=40, fouls=26.0, yellows=4.6, league_fouls=21.5, league_yellows=3.6, name="Severo")
    fouls, yellows, warnings = strict.factors((20.0, 80.0))
    assert fouls == pytest.approx(1 + 40 / 60 * (26 / 21.5 - 1)) and yellows == pytest.approx(1 + 40 / 120 * (4.6 / 3.6 - 1))
    assert not warnings
    assert ee.RefereeInput(10, fouls=30.0).factors((20.0, 80.0))[0] == 1.0
    assert "mancante" in ee.RefereeInput(10, fouls=30.0).factors((20.0, 80.0))[2][0]
    assert ee.RefereeInput(10, yellows=5.0, league_yellows=3.0).factors((20.0, None))[1] == 1.0
    base, harsh = run(dc_scores()), run(dc_scores(), referee=strict)
    assert harsh["fouls_home"].mean() / base["fouls_home"].mean() == pytest.approx(fouls, rel=0.03)
    cards = lambda o: (o["yellows_home"] + o["double_yellows_home"]).mean()
    assert cards(harsh) / cards(base) == pytest.approx(yellows, rel=0.05)
    assert any(row["voce"] == "arbitro" and "Severo" in row["nota"] for row in harsh["ledger"])


def test_dizionario_su_falli_e_corner_da_cross():
    base = run(dc_scores())
    pressing = run(dc_scores(), home=ee.TeamInput(1.6, {"pressing": "alto", "fasce_cross": "alto"}, 0.45))
    terms = tactical_dictionary.load()["termini"]
    beta = {e["tasso"]: e["beta"] for term in ("pressing", "fasce_cross") for e in terms[term]["effetti"]}
    assert pressing["fouls_home"].mean() / base["fouls_home"].mean() == pytest.approx(np.exp(beta["falli_fatti"]), rel=0.02)
    cross = pressing["corners_by_origin_home"][:, 1].mean() / base["corners_by_origin_home"][:, 1].mean()
    assert cross == pytest.approx(np.exp(beta["corner_fasce"]), rel=0.04)
    other = pressing["corners_by_origin_home"][:, 2].mean() / base["corners_by_origin_home"][:, 2].mean()
    assert other == pytest.approx(1.0, abs=0.03)
    assert pressing["fouls_away"].mean() == pytest.approx(base["fouls_away"].mean(), rel=0.02)


def test_corsie_e_scale():
    home = ee.TeamInput(1.6, first_share=0.45, module="3-4-3", corner_scale=1.2, foul_scale=0.9)
    away = ee.TeamInput(1.1, first_share=0.44, module="4-4")
    off = run(dc_scores(), home=home, away=away)
    assert next(r for r in off["ledger"] if r["voce"] == "corsie")["valore"] == {"casa": 1.0, "ospite": 1.0}
    base = run(dc_scores())
    assert off["corners_by_origin_home"][:, 2].mean() / base["corners_by_origin_home"][:, 2].mean() == pytest.approx(1.2, rel=0.03)
    assert off["fouls_home"].mean() / base["fouls_home"].mean() == pytest.approx(0.9, rel=0.02)
    # La scala dei falli non cambia i gialli attesi (li fissa card_scale).
    cards = lambda o: (o["yellows_home"] + o["double_yellows_home"]).mean()
    assert cards(off) == pytest.approx(cards(base), rel=0.05)
    on = run(dc_scores(), home=home, away=ee.TeamInput(1.1, module="5-3-2"), lanes=True)
    lanes = next(r for r in on["ledger"] if r["voce"] == "corsie")["valore"]
    assert lanes["casa"] == pytest.approx(ee.wide_factor("3-4-3", "5-3-2"), abs=1e-4) and lanes["casa"] != 1.0
    assert ee.wide_factor(None, None) == pytest.approx(1.0)
    bad = run(dc_scores(), home=home, away=away, lanes=True)
    assert any("non valido" in w for w in bad["warnings"])


def test_punti_cartellini_con_la_regola_del_bookmaker():
    import engine
    sample = {"yellows_home": np.array([2, 1]), "reds_home": np.array([1, 0]), "double_yellows_home": np.array([1, 0]),
              "yellows_away": np.array([0, 3]), "reds_away": np.array([0, 1]), "double_yellows_away": np.array([0, 0])}
    eurobet = engine.CardRule()
    assert ee.card_points(sample, eurobet).tolist() == [4, 6]
    assert ee.card_points(sample, eurobet, "home").tolist() == [4, 1]
    only_red = engine.CardRule(double_yellow="solo_rosso", double_yellow_share=0.5)
    assert ee.card_points(sample, only_red, "home").tolist() == [3, 1]


def test_modo_libero_con_conteggi():
    out = run()
    assert out["goals_home"].mean() == pytest.approx(1.6, abs=0.04)
    assert out["fouls_home"].mean() == pytest.approx(PARAMS.fouls, rel=0.05)
