"""Ricerca rapida, frequenza storica recente e schedine salvate (fase X), per la pagina «Oggi».

Le schedine stanno in ``st.session_state["saved_slips"]`` (dizionari ``slips.Slip.to_dict``) e finiscono
nell'Excel della giornata.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from multiples import Multiple
from quick_search import EXAMPLES, PRESETS, build, parse_query
from recent_form import recent_frequency
from slips import STATUSES, Slip, make_slip, registry_like, update_from_results


def _slips() -> list[dict]:
    return st.session_state.setdefault("saved_slips", [])


def save_slip(name: str, legs, dates: dict) -> Slip:
    slip = make_slip(name, legs, dates)
    st.session_state["saved_slips"] = [item for item in _slips() if item["name"] != slip.name] + [slip.to_dict()]
    return slip


def render_save_slip(legs, dates: dict, key: str, default: str) -> None:
    """Campo nome + «Salva come schedina»."""
    columns = st.columns([3, 1])
    name = columns[0].text_input("Nome della schedina", value=default, key=f"{key}_slip_name")
    if columns[1].button("Salva come schedina", key=f"{key}_slip_save", width="stretch"):
        slip = save_slip(name, legs, dates)
        st.success(f"Schedina «{slip.name}» salvata: la trovi in «Schedine salvate» e nell'Excel della giornata.")


# --- Frequenza storica recente ------------------------------------------------------------------------

def _recent_matches(competition: str) -> pd.DataFrame | None:
    """Risultati recenti del campionato (football-data.co.uk, cache); ``None`` se non coperto o non raggiungibile."""
    from datasources.builder import DataProvider
    from datasources.sources import COMPETITIONS
    from ui_data import source_cache

    cache = st.session_state.setdefault("recent_matches", {})
    if competition not in cache:
        if competition not in COMPETITIONS:
            cache[competition] = None
        else:
            try:
                cache[competition] = DataProvider(source_cache()).league_matches(competition).data
            except Exception:  # fonte remota: si degrada senza bloccare la pagina
                cache[competition] = None
    return cache[competition]


def frequency_text(analysis, selection: str) -> tuple[str, str]:
    """(forma breve per la tabella, frase completa) della frequenza storica recente."""
    matches = _recent_matches(analysis.match.competition)
    if matches is None or matches.empty:
        return "—", "storico non disponibile per questa competizione"
    frequency = recent_frequency(selection, analysis.match.home, analysis.match.away, matches,
                                 as_of=analysis.match.commence_time.date())
    if frequency is None:
        return "—", "storico solo per i mercati che non dipendono da casa/ospite"
    if frequency.total == 0:
        return "—", frequency.sentence()
    return f"{frequency.hits} su {frequency.total}" + (" ⚠" if frequency.small else ""), frequency.sentence()


# --- Ricerca rapida ---------------------------------------------------------------------------------------

def _set_query(text: str) -> None:
    st.session_state["quick_query"] = text


def render_quick_search(analyses, settings: dict) -> None:
    st.subheader("Ricerca rapida")
    st.caption("Scrivi cosa cerchi, ad esempio «dammi 6 over 2.5 per stasera»: numero di partite, mercato e linea, soglia "
               "(«sopra il 70%», «sicure» = 75%) e fascia oraria (oggi, pomeriggio, stasera). Regole sul testo, senza AI.")
    columns = st.columns(len(PRESETS))
    for column, preset in zip(columns, PRESETS):
        column.button(preset, key=f"quick_preset_{preset}", on_click=_set_query, args=(preset,), width="stretch")
    text = st.text_input("Ricerca rapida", key="quick_query", placeholder="es. 3 multigol casa sopra il 70%",
                         label_visibility="collapsed")
    if not text.strip():
        return
    query = parse_query(text)
    if query is None:
        st.warning("Frase non capita. Esempi validi:\n" + "\n".join(f"- {example}" for example in EXAMPLES))
        return
    matches = [{"id": str(index), "label": analysis.match.label, "kickoff": analysis.match.commence_time.astimezone(),
                "result": analysis.result, "odds": analysis.odds} for index, analysis in enumerate(analyses) if analysis.ok]
    proposal = build(query, matches, trap_ev=float(st.session_state.get("today_trap", settings["trappola_ev"])))
    st.markdown(f"**{query.describe()}**")
    for note in proposal.notes:
        st.caption(note)
    if proposal.traps:
        st.caption(f"Trappole escluse (EV sotto la soglia): " + ", ".join(f"{leg.match} {leg.label}" for leg in proposal.traps))
    if not proposal.legs:
        st.info("Nessuna partita soddisfa la richiesta.")
        return
    rows, sentences = [], []
    for leg in proposal.legs:
        analysis = analyses[int(leg.match_id)]
        short, sentence = frequency_text(analysis, leg.selections[0])
        sentences.append(f"{leg.match}: {sentence}")
        rows.append({"Partita": leg.match, "Ora": f"{analysis.match.commence_time.astimezone():%H:%M}", "Gamba": leg.label,
                     "Prob. simulatore %": round(leg.probability * 100, 1), "Quota": leg.odds,
                     "EV %": round(leg.ev * 100, 1) if leg.ev is not None else None, "Storico recente": short})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Storico recente = quante volte è uscito nelle ultime partite delle due squadre (football-data.co.uk): è un "
               "conteggio dei risultati reali, NON la probabilità del modello. ⚠ = campione piccolo.")
    with st.expander("Storico recente gamba per gamba", expanded=False):
        st.markdown("\n".join(f"- {sentence}" for sentence in sentences))
    multiple = Multiple(query.describe(), proposal.legs)
    odds = f"{multiple.odds:.2f}" if multiple.odds else "— (manca qualche quota)"
    st.markdown(f"Schedina: probabilità **{multiple.probability:.1%}** · quota **{odds}** · {multiple.sentence()}"
                + (f" · EV {multiple.ev:+.1%}" if multiple.ev is not None else ""))
    if any(leg.ev is not None and leg.ev < 0 for leg in proposal.legs):
        st.warning("Alcune gambe hanno EV negativo (sopra la soglia trappola): " + ", ".join(
            f"{leg.match} {leg.label} {leg.ev:+.1%}" for leg in proposal.legs if leg.ev is not None and leg.ev < 0))
    dates = {str(index): analysis.match.commence_time.astimezone().date() for index, analysis in enumerate(analyses)}
    render_save_slip(proposal.legs, dates, "quick", f"{query.describe()} {date.today():%d/%m}")


# --- Schedine salvate --------------------------------------------------------------------------------------

def render_slips() -> None:
    from datasources.sources import COMPETITIONS
    from performance import collect_results
    from ui_performance import _fetch_season

    slips = [Slip.from_dict(item) for item in _slips()]
    with st.expander(f"Schedine salvate ({len(slips)})", expanded=False):
        if not slips:
            st.caption("Nessuna schedina: salvala dalla ricerca rapida o dal costruttore di multiple con un nome.")
            return
        st.dataframe(pd.DataFrame([{"Schedina": slip.name, "Creata": slip.created[:16].replace("T", " "),
                                    "Stato": slip.state, "Gambe vinte": slip.score(), "Quota": slip.odds} for slip in slips]),
                     hide_index=True, width="stretch")
        names = [slip.name for slip in slips]
        chosen = st.selectbox("Schedina", names, key="slip_chosen")
        slip = slips[names.index(chosen)]
        st.markdown(f"**{slip.name}** · {slip.state} · {slip.score()}")
        table = pd.DataFrame([{"Partita": leg["match"], "Data": leg.get("date"), "Gamba": leg["selection"], "Quota": leg.get("odds"),
                               "Stato": leg["status"], "Note": leg.get("note", "")} for leg in slip.legs])
        edited = st.data_editor(table, hide_index=True, width="stretch", key=f"slip_editor_{slip.id}",
                                disabled=["Partita", "Data", "Gamba", "Quota", "Note"],
                                column_config={"Stato": st.column_config.SelectboxColumn("Stato", options=list(STATUSES))})
        manual = [status for status in edited["Stato"]]
        if manual != [leg["status"] for leg in slip.legs]:
            for leg, status in zip(slip.legs, manual):
                if status != leg["status"]:
                    leg["status"], leg["note"] = status, "esito inserito a mano"
            _replace(slip)
            st.rerun()
        columns = st.columns(2)
        if columns[0].button("Cerca esiti (punteggi gratuiti)", key=f"slip_results_{slip.id}",
                             help="Risultati di football-data.co.uk (campionati coperti, nessun credito). Le coppe restano a mano."):
            with st.spinner("Scarico i risultati da football-data.co.uk…"):
                results, warnings = collect_results(registry_like(slip), _fetch_season, COMPETITIONS)
            changed = update_from_results(slip, results) if not results.empty else 0
            _replace(slip)
            st.session_state["slip_report"] = f"{changed} gambe aggiornate." + "".join(f" {warning}" for warning in warnings)
            st.rerun()
        if st.session_state.get("slip_report"):
            st.caption(st.session_state.pop("slip_report"))
        if columns[1].button("Elimina la schedina", key=f"slip_delete_{slip.id}"):
            st.session_state["saved_slips"] = [item for item in _slips() if item["name"] != slip.name]
            st.rerun()


def _replace(slip: Slip) -> None:
    st.session_state["saved_slips"] = [slip.to_dict() if item["name"] == slip.name else item for item in _slips()]
