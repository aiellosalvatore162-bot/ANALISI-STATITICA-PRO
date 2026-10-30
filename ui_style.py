"""Riquadro «Stile» (fase AH): come il motore legge ciascuna squadra, da dove viene ogni numero, cosa del report è stato assorbito."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import match_context
import style_profile
from ui_lineup import player_store


def style_store(league: str | None):
    """Archivio di stile del campionato (una volta al giorno, cache su disco); ``None`` se non disponibile."""
    if not league:
        return None
    try:
        from ui_data import source_cache

        return style_profile.load_store(league, date.today(), source_cache())
    except Exception:
        return None


def build_context(analysis) -> dict | None:
    """Contesto della partita (cache nell'analisi: si ricalcola solo se cambia il report)."""
    if analysis.config is None:
        return None
    config = analysis.config
    sheets = st.session_state.get("tactical_sheets", [])
    stamp = (id(analysis.extras), len(sheets), id(analysis.claude), bool(analysis.lineup))
    cached = st.session_state.setdefault("style_context", {}).get(analysis.match.label)
    if cached and cached[0] == stamp:
        analysis.context = cached[1]
        return cached[1]
    store = style_store(config.league)
    context = match_context.match_context(
        config.home.name, config.away.name, analysis.match.commence_time.date(), league=config.league, style_store=store,
        player_store=player_store(), sheets=sheets, extras=analysis.extras,
        response=analysis.claude, elo=(config.home.elo, config.away.elo), calendar_rest=config.rest_days)
    st.session_state["style_context"][analysis.match.label] = (stamp, context)
    analysis.context = context
    return context


def _numbers(side: dict) -> pd.DataFrame:
    rows = []
    style = side.get("stile") or {}
    if style.get("forma_reale"):
        item = style["forma_reale"]
        rows.append({"Numero": "forma reale (xG−xGA, centrata)", "Valore": item["valore"], "Partite": item["campione"], "Da dove": item["fonte"],
                     "Avviso": item.get("avviso") or ""})
    for name, item in (style.get("parametri") or {}).items():
        rows.append({"Numero": f"{name}: {style_profile.PARAMS[name][1]}", "Valore": item["valore"], "Partite": item["campione"],
                     "Da dove": item["fonte"], "Avviso": item.get("avviso") or ""})
    return pd.DataFrame(rows)


def render_context(context: dict) -> None:
    left, right = st.columns(2)
    for column, key in ((left, "casa"), (right, "ospite")):
        side = context[key]
        with column:
            labels = side.get("etichette") or {}
            st.markdown(f"**{side['squadra']}** · forma: {labels.get('forma', 'n/d')} · territorio: {labels.get('territorio', 'n/d')} · "
                        f"{labels.get('pressing', 'n/d')}")
            numbers = _numbers(side)
            if len(numbers):
                st.dataframe(numbers, hide_index=True, width="stretch", column_config={"Valore": st.column_config.NumberColumn(format="%.3f")})
            else:
                st.caption("Nessun numero di stile misurato (dati non disponibili): il motore usa le sue medie.")
            if side.get("profilo"):
                st.markdown("Profilo dell'Analista come prior dei numeri misurati:")
                st.dataframe(pd.DataFrame(side["profilo"])[["campo", "categoria", "parametro", "dato", "campione", "prior", "peso_dati", "valore", "origine"]],
                             hide_index=True, width="stretch")
            if side.get("adattabilita"):
                info = side["adattabilita"]
                st.caption(f"Adattabilità {info['livello']}: incroci attenuati a ×{info['attenuazione_incroci']:g}"
                           + (f"; contro questo avversario si sposta verso «{info['sposta_verso']}»: {info['testo']}" if info["sposta_verso"] else "."))
            if side.get("reazioni"):
                st.caption(f"Reazioni (regole di stato per la AK): in svantaggio ×{side['reazioni']['se_in_svantaggio']:.2f}, "
                           f"in vantaggio ×{side['reazioni']['se_in_vantaggio']:.2f}.")
            if side.get("cambio_allenatore"):
                info = side["cambio_allenatore"]
                st.caption(f"Allenatore nuovo dal {info['dal']}: gare precedenti a peso {info['peso_partite_precedenti']:g} "
                           f"finché ne servono {info['partite_per_fidarsi']} col nuovo.")
    incroci = context["incroci"]
    st.markdown("**Incroci di stile applicati a questa partita**")
    if incroci["note"]:
        for note in incroci["note"]:
            st.caption(f"• {note}")
        st.caption("Fattori: " + ", ".join(f"{key} ×{value:.3f}" for key, value in incroci["fattori"].items() if abs(value - 1.0) > 1e-9) or "nessuno")
    else:
        st.caption("Nessun incrocio applicato (regole spente, non verificate o profili mancanti).")
    rest = context["riposo"]
    st.caption("Riposo: " + ", ".join(f"{side} {item['giorni']} giorni ({item['origine']})" for side, item in rest.items() if item) or "Riposo: non noto.")
    turnover = {side: item for side, item in context["turnover"].items() if item}
    if turnover:
        st.caption("Turnover: " + ", ".join(f"{side} {'probabile' if flag else 'no'} ({source})" for side, (flag, source) in turnover.items()))
    absorbed = pd.DataFrame(match_context.absorbed_rows(context))
    if len(absorbed):
        st.markdown("**Cosa del report è entrato nel motore e cosa è solo informativo**")
        st.dataframe(absorbed, hide_index=True, width="stretch")
    st.caption(context["spiegazioni"]["nota"] + ".")
    for message in context["avvisi"][:6]:
        st.caption(message)


def render_styles(analyses) -> None:
    ready = [analysis for analysis in analyses if analysis.ok]
    if not ready:
        return
    st.subheader("Stile")
    st.caption("Come il motore legge ogni squadra. Il report dell'Analista è facoltativo: senza, restano i numeri misurati.")
    compact = []
    contexts = {}
    for analysis in ready:
        context = build_context(analysis)
        if context is None:
            continue
        contexts[analysis.match.label] = context
        home, away = context["casa"].get("etichette") or {}, context["ospite"].get("etichette") or {}
        compact.append({"Partita": analysis.match.label,
                        "Forma": f"{home.get('forma', 'n/d')} / {away.get('forma', 'n/d')}",
                        "Territorio": f"{home.get('territorio', 'n/d')} / {away.get('territorio', 'n/d')}",
                        "Pressing": f"{home.get('pressing', 'n/d')} / {away.get('pressing', 'n/d')}"})
    if compact:
        st.dataframe(pd.DataFrame(compact), hide_index=True, width="stretch")      # clic sull'intestazione per ordinare
    for label, context in contexts.items():
        with st.expander(f"Stile · {label}", expanded=False):
            render_context(context)
