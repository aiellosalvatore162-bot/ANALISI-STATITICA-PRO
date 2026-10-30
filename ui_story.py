"""Riquadro «Vedi come andrà» (fase AK, stadio 15): andamento della partita dai percorsi del motore a eventi, con il motore
attivo sempre dichiarato. Logica in ``match_story.py``."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import match_story

CACHE_KEY = "match_story_cache"


def _signature(result: dict) -> tuple:
    model = result.get("model") or {}
    teams = result.get("input") or {}
    return (model.get("lambda"), model.get("mu"), model.get("seed"), (teams.get("home") or {}).get("name"),
            (teams.get("away") or {}).get("name"), result.get("markets", {}).get("corners", {}).get("mean"),
            result.get("markets", {}).get("cards", {}).get("mean"))


def render_story(result: dict, config) -> None:
    with st.expander("Vedi come andrà", expanded=False):
        settings = config.event_engine if config is not None else None
        st.caption(match_story.engine_label(settings) if settings is not None else "Configurazione non disponibile.")
        active = bool((result.get("event_engine") or {}).get("active"))
        cache = st.session_state.setdefault(CACHE_KEY, {})
        signature = _signature(result)
        cached = cache.get(signature)
        if not active and cached is None:
            st.write("L'andamento si calcola con il motore a eventi sugli stessi gol attesi, corner e cartellini (circa 2-4 "
                     "secondi).")
            if not st.button("Mostra l'andamento", key="story_run"):
                return
        try:
            with st.spinner("Simulo l'andamento minuto per minuto..."):
                data = match_story.story(result, config, cached)
        except Exception as exc:   # il riquadro non deve mai bloccare la pagina
            st.warning(f"Andamento non disponibile: {exc}")
            return
        if data.get("errore"):
            st.warning(data["errore"])
            return
        if not active:
            cache[signature] = data["dettagli"]
        timeline = data["andamento"]
        for line in data["frasi"]:
            st.markdown(f"- {line}")
        st.markdown("**Per fasce di minuti** (medie per partita)")
        st.dataframe(pd.DataFrame(match_story.band_table(timeline, result)), hide_index=True, use_container_width=True)
        left, right = st.columns([2, 1])
        with left:
            st.markdown("**Momenti probabili dei gol** (probabilità di almeno un gol in ogni tratto di 5 minuti, %)")
            moments = pd.DataFrame(match_story.goal_moments(timeline)).set_index("Minuti")
            st.bar_chart(moments, height=220)
        with right:
            st.markdown("**Primo gol**")
            st.dataframe(pd.DataFrame(match_story.first_goal_rows(timeline)), hide_index=True, use_container_width=True)
        st.caption(f"{timeline['simulazioni']:,} partite simulate dal motore a eventi ({data.get('parametri') or 'parametri comuni'}). "
                   "Solo presentazione: queste medie non cambiano probabilità, EV o registro.".replace(",", "."))
