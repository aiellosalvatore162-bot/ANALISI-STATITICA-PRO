"""Sezione Streamlit «Risultati esatti»: tabella, gruppo minimo, gruppo personale con quota, coerenza e correlazione."""

from __future__ import annotations

import streamlit as st

from dashboard import heatmap

from exact_scores import (
    UNCERTAINTY_NOTE, coherence, coherence_summary, correlation, group_probability, group_selection, group_value,
    minimum_group, score_table,
)


def _historical_note() -> str | None:
    """Sintesi della verifica storica (``python -m tools.baseline --risultati-esatti``), se presente."""
    import json
    from datetime import date

    from engine import GOAL_MODEL_PATH

    try:
        section = json.loads(GOAL_MODEL_PATH.read_text(encoding="utf-8")).get("risultati_esatti")
    except (OSError, ValueError):
        return None
    if not section:
        return None
    rows = section.get("copertura_gruppo_minimo", {}).get("fuori_campione", [])
    coverage = " · ".join(f"{row['copertura_nominale']:.0%} → {row['frequenza_reale']:.0%}" for row in rows)
    return (f"Verifica storica ({section['partite_fuori_campione']} partite fuori campione, {date.fromisoformat(section['data']):%d/%m/%Y}): "
            f"gruppo minimo, copertura prevista → realizzata: {coverage}. Risultato più probabile: previsto "
            f"{section['risultato_piu_probabile']['prevista']:.1%}, realizzato {section['risultato_piu_probabile']['reale']:.1%}.")


def _eurobet_exact() -> dict[str, float]:
    """Quote Eurobet incollate dei risultati esatti e dei gruppi per la partita simulata."""
    from ui_eurobet import find_paste

    config = st.session_state.get("result_config")
    paste = find_paste(config.home.name, config.away.name) if config is not None else None
    return paste.exact() if paste is not None else {}


def render_exact_scores(result: dict) -> tuple[list[str], list[str]]:
    """Mostra la sezione e restituisce (gruppo minimo, il mio gruppo) per la mappa di calore."""
    st.subheader("Risultati esatti")
    distribution = result["exact_scores"]["finale"]
    st.warning(UNCERTAINTY_NOTE)
    note = _historical_note()
    if note:
        st.caption(note)
    heat = st.empty()  # mappa di calore, disegnata a fine sezione quando i gruppi sono noti
    table = score_table(distribution)
    st.caption(f"{result['model']['simulation_count']:,} simulazioni · {len(table)} risultati diversi. "
               "Quota equa = 1 / probabilità.".replace(",", "."))
    st.dataframe(table.head(20), hide_index=True, width="stretch")
    if len(table) > 20:
        with st.expander(f"Tutti i {len(table)} risultati"):
            st.dataframe(table, hide_index=True, width="stretch")

    st.markdown("**Gruppo minimo**", help="Il minor numero di risultati, dai più probabili, che insieme raggiunge la copertura scelta.")
    coverage = st.slider("Copertura desiderata %", 40, 90, 70, 5, key="exact_coverage")
    chosen, probability = minimum_group(distribution, coverage / 100.0)
    columns = st.columns(3)
    columns[0].metric("Risultati necessari", len(chosen))
    columns[1].metric("Probabilità del gruppo", f"{probability:.1%}")
    columns[2].metric("Quota equa del gruppo", f"{1 / probability:.2f}" if probability else "—", help="1 / probabilità: la quota senza margine.")
    st.caption("Gruppo: " + group_selection(chosen).replace("/", ", "))

    st.markdown("**Il mio gruppo**")
    picked = st.multiselect("Risultati del gruppo", list(table["Risultato"]), key="exact_group_scores", placeholder="Scegli i risultati",
                            help="Es. 1-0, 2-0, 2-1, 1-1: vince se il risultato finale è uno di questi.")
    eurobet = _eurobet_exact()
    if eurobet:
        groups = {selection: price for selection, price in eurobet.items() if "/" in selection}
        st.caption(f"Quote Eurobet incollate: {len(eurobet) - len(groups)} risultati esatti e {len(groups)} gruppi"
                   + (" (" + " · ".join(f"{selection} {price:.2f}" for selection, price in groups.items()) + ")" if groups else "")
                   + ". Scegli gli stessi risultati per usarne la quota.")
    if picked and eurobet.get(group_selection(picked)):
        price = eurobet[group_selection(picked)]
        if st.button(f"Usa la quota Eurobet {price:.2f} per {group_selection(picked)}", key="exact_use_eurobet"):
            st.session_state["exact_group_odds"] = float(price)
    initial = {} if "exact_group_odds" in st.session_state else {"value": 0.0}
    offered = st.number_input("Quota offerta (es. Eurobet) per questa combinazione", min_value=0.0, step=0.05,
                              format="%.2f", key="exact_group_odds", help="0 = nessuna quota.", **initial)
    if not picked:
        st.session_state.pop("exact_group", None)
        heat.html(heatmap(result, chosen, []))
        return chosen, []
    selection = group_selection(picked)
    probability = group_probability(distribution, picked)
    value = group_value(probability, offered or None)
    columns = st.columns(3)
    columns[0].metric("Probabilità del gruppo", f"{probability:.1%}")
    columns[1].metric("Quota equa", f"{value['fair_odds']:.2f}" if value["fair_odds"] else "—")
    columns[2].metric("Valore atteso (EV)", f"{value['ev']:+.1%}" if value["ev"] is not None else "—",
                      help="Guadagno medio per 1 € puntato alla quota offerta. Negativo = non conviene.")
    if value["ev"] is not None and value["ev"] < 0:
        st.error(f"EV negativo: alla quota {offered:.2f} il gruppo vale meno di quanto rischi (quota equa {value['fair_odds']:.2f}).")
    elif value["ev"] is not None:
        st.success("EV positivo sul modello: ricorda l'incertezza alta dei risultati esatti prima di giocarlo.")
    spread = [(label, result["exact_scores"].get(component)) for label, component in
              (("solo modello", "modello"), ("solo mercato", "mercato"))]
    shown = [f"{label} {group_probability(values, picked):.1%}" for label, values in spread if values]
    if shown:
        st.caption("Stessa probabilità con le singole componenti: " + " · ".join(shown) + ". Più sono lontane, più è incerta.")
    st.session_state["exact_group"] = {"selection": selection, "odds": offered if offered > 1.0 else None}
    heat.html(heatmap(result, chosen, picked))

    st.markdown("**Coerenza con gli altri mercati**")
    table = coherence(distribution, picked)
    st.info(coherence_summary(table))
    st.dataframe(table, hide_index=True, width="stretch")

    st.markdown("**In schedina con altri mercati**")
    finale = result["components"]["finale"]
    legs = st.multiselect("Altri mercati che vuoi combinare con il gruppo", sorted(finale), key="exact_group_legs",
                          placeholder="Scegli i mercati")
    if legs:
        joint = correlation(distribution, picked, legs, finale)
        st.dataframe(joint, hide_index=True, width="stretch")
        redundant = joint[joint["Giudizio"].str.startswith("ridondante")]["Mercato"].tolist()
        if redundant:
            st.warning("Correlazione: " + ", ".join(redundant) + " contiene già tutto il gruppo. In schedina la "
                       "probabilità resta quella del solo gruppo: una quota combinata calcolata come prodotto la "
                       "sopravvaluta, e molti bookmaker non accettano combinazioni correlate.")
        st.caption("Probabilità congiunta sul campione simulato, non il prodotto delle probabilità (come nel Combo Builder).")
    return chosen, picked
