"""Sezione Streamlit «Quote del giorno» (The Odds API) e contatore dei crediti.

Ogni scarico che costa crediti mostra prima il costo massimo e chiede una
conferma; le risposte restano in cache 30 minuti (``config/odds_api.json``),
quindi ripetere la stessa richiesta è gratuito.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from datasources.builder import DataProvider
from datasources.oddsapi import (
    MARKET_LABELS, SOURCE, BudgetExceeded, OddsApi, OddsApiError, competition_label, events_frame, is_european_soccer,
    league_overview, merged_quotes_frame, odds_api_key, planned_cost, preselect, quote_rows, reference_quotes, sheet_odds,
)
from datasources.sources import COMPETITIONS, CUP_COMPETITIONS, football_data_org_key
from ui_data import _use_block, source_cache


@st.cache_resource(show_spinner=False)
def odds_client() -> OddsApi:
    return OddsApi(source_cache(), odds_api_key())


def render_credits(api: OddsApi | None = None) -> None:
    """Crediti rimasti (ultima intestazione x-requests-remaining) e spesa di oggi rispetto al budget."""
    api = api or odds_client()
    if not api.configured:
        st.caption(f"{SOURCE}: chiave ODDS_API_KEY non configurata in .streamlit/secrets.toml.")
        return
    usage = api.usage()
    remaining = "—" if usage["remaining"] is None else str(usage["remaining"])
    updated = f" (agg. {usage['updated'].astimezone():%d/%m %H:%M})" if usage["updated"] else " (nessuna chiamata registrata)"
    st.caption(f"**Crediti {SOURCE}**: rimasti {remaining}{updated} · oggi spesi {usage['spent_today']} "
               f"su {usage['budget']} di budget giornaliero")


def _run(call, label: str):
    """Esegue una chiamata mostrando avvisi ed errori; ``None`` se non riuscita."""
    try:
        result = call()
    except BudgetExceeded as exc:
        st.error(str(exc))
        return None
    except OddsApiError as exc:
        st.warning(f"{label}: {exc}")
        return None
    for warning in result.warnings:
        st.warning(warning)
    return result


def _confirmed(cost: int, cached: int, key: str) -> bool:
    if cost == 0:
        st.caption("Costo: 0 crediti" + (f" (tutto in cache, {cached} risposte)" if cached else "") + ".")
        return True
    st.caption(f"Costo massimo: **{cost} crediti**" + (f" ({cached} risposte già in cache, gratis)" if cached else "") + ".")
    return st.checkbox(f"Confermo la spesa di {cost} crediti", key=f"{key}_{cost}")


def render_odds() -> None:
    api = odds_client()
    render_credits(api)
    if not api.configured:
        st.info("Aggiungi ODDS_API_KEY in .streamlit/secrets.toml per usare le quote automatiche. "
                "Le altre modalità di input funzionano senza.")
        return
    sports = _run(api.sports, "Elenco competizioni")
    if sports is None:
        return
    labels = {sport["key"]: competition_label(sport["key"], sport.get("title"))
              for sport in sports.payload if sport.get("active") and is_european_soccer(sport)}
    defaults = [key for key in api.settings.get("competizioni_predefinite", []) if key in labels]
    columns = st.columns([3, 1])
    chosen = columns[0].multiselect("Competizioni", list(labels), defaults, format_func=labels.get, key="odds_sports",
                                    help="Top 5, coppe europee e gli altri campionati europei attivi in The Odds API.")
    day = columns[1].date_input("Giorno", value=date.today(), key="odds_day")

    st.markdown("**1 · Elenco partite** (gratuito)")
    if st.button("Cerca le partite del giorno", key="odds_events_button", disabled=not chosen):
        frames = []
        for sport in chosen:
            result = _run(lambda: api.events(sport, day), labels[sport])
            if result is not None:
                frames.append(events_frame(result.payload, sport))
        st.session_state["odds_events"] = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        st.session_state["odds_events_day"] = day
    events = st.session_state.get("odds_events")
    if events is None:
        return
    if events.empty:
        st.info("Nessuna partita nel giorno scelto per queste competizioni.")
        return
    st.caption(f"{len(events)} partite il {st.session_state['odds_events_day']:%d/%m/%Y}.")

    st.markdown("**2 · Quote 1X2 e Over/Under per campionato** (servono per l'ancoraggio e la preselezione)")
    leagues = sorted(events["sport"].unique())
    calls = [(f"/sports/{sport}/odds", api.league_params(), api.league_cost()) for sport in leagues]
    cost, cached = planned_cost(api, calls)
    st.caption(f"Una chiamata per campionato ({len(leagues)}), regione {api.region}, mercati "
               f"{api.league_params()['markets']}: {api.league_cost()} crediti ciascuna.")
    if _confirmed(cost, cached, "odds_confirm_league") and st.button("Scarica le quote per campionato", key="odds_league_button"):
        for sport in leagues:
            result = _run(lambda: api.league_odds(sport), labels.get(sport, sport))
            if result is not None:
                st.session_state.setdefault("odds_league", {})[sport] = (result.payload, result.fetched_at)
    league_data = st.session_state.get("odds_league", {})
    league_events = {event["id"]: (event, fetched) for sport in leagues if sport in league_data
                     for event in league_data[sport][0] for fetched in [league_data[sport][1]]}
    overview = league_overview([league_events[event_id][0] for event_id in events["event_id"] if event_id in league_events])
    if overview.empty:
        return
    shown = overview.assign(
        Ora=overview["commence_time"].dt.strftime("%d/%m %H:%M") + " UTC",
        Partita=overview["home_team"] + " - " + overview["away_team"],
        Disaccordo=(overview["disaccordo"] * 100).round(1),
    )[["Ora", "competition", "Partita", "1", "X", "2", "Over 2.5 gol", "Under 2.5 gol", "riferimento", "bookmaker", "Disaccordo"]]
    st.dataframe(shown.rename(columns={"competition": "Competizione", "riferimento": "Riferimento", "bookmaker": "Bookmaker",
                                       "Disaccordo": "Disaccordo %"}), hide_index=True, width="stretch")
    st.caption("Riferimento = Pinnacle se quota tutti gli esiti della linea, altrimenti la mediana dei bookmaker. "
               "Disaccordo = media di (quota massima / minima − 1) sull'1X2: preselezione del sistema.")

    st.markdown("**3 · Mercati aggiuntivi per le partite preselezionate** (Goal/No Goal, linee gol, corner, cartellini, primo tempo)")
    names = dict(zip(overview["event_id"], overview["home_team"] + " - " + overview["away_team"]))
    limit = int(api.settings.get("max_partite_mirate", 10))
    selected = st.multiselect(f"Partite (massimo {limit}; proposta del sistema: più disaccordo tra bookmaker)", list(names),
                              preselect(overview, limit), format_func=names.get, max_selections=limit, key="odds_selected")
    markets = st.multiselect("Mercati", list(api.settings.get("mercati_evento", [])), api.settings.get("mercati_evento", []),
                             format_func=lambda key: MARKET_LABELS.get(key, key), key="odds_markets")
    sport_of = dict(zip(overview["event_id"], overview["sport"]))
    calls = [(f"/sports/{sport_of[event_id]}/events/{event_id}/odds", api.event_params(markets), api.event_cost(markets))
             for event_id in selected]
    cost, cached = planned_cost(api, calls)
    st.caption("Costo per partita = mercati restituiti × regioni: si pagano solo i mercati che i bookmaker quotano davvero.")
    if selected and markets and _confirmed(cost, cached, "odds_confirm_event") and st.button("Scarica i mercati aggiuntivi", key="odds_event_button"):
        for event_id in selected:
            result = _run(lambda: api.event_odds(sport_of[event_id], event_id, markets), names[event_id])
            if result is not None:
                st.session_state.setdefault("odds_event", {})[event_id] = (result.payload, result.fetched_at)

    st.markdown("**4 · Partita da simulare**")
    event_id = st.selectbox("Partita", list(names), format_func=names.get, key="odds_match")
    extra = st.session_state.get("odds_event", {}).get(event_id)
    league_event, league_fetched = league_events[event_id]
    frame = merged_quotes_frame([league_event, extra[0] if extra else None])
    quotes = reference_quotes(frame, api.settings.get("riferimento"))
    fetched = max(value for value in (league_fetched, extra[1] if extra else None) if value is not None)
    eurobet_state = st.session_state.setdefault("odds_eurobet", {}).setdefault(event_id, {})
    table = quote_rows(quotes, eurobet_state)
    edited = st.data_editor(
        table, hide_index=True, width="stretch", key=f"odds_editor_{event_id}",
        disabled=[column for column in table.columns if column != "Quota Eurobet"],
        column_config={"Quota Eurobet": st.column_config.NumberColumn(min_value=1.01, step=0.01, format="%.2f"),
                       "Eurobet vs riferimento": st.column_config.NumberColumn(format="percent")},
    )
    eurobet = {row["Mercato"]: float(row["Quota Eurobet"]) for _, row in edited.iterrows()
               if pd.notna(row["Quota Eurobet"]) and float(row["Quota Eurobet"]) > 1.0}
    st.session_state["odds_eurobet"][event_id] = eurobet
    st.caption("Quote Eurobet inseribili a mano nella colonna dedicata per il confronto. Linee corner e cartellini: "
               "la regola di conteggio dei cartellini del bookmaker può differire da quella Eurobet (giallo 1, rosso 2).")
    use_eurobet = st.checkbox("Nel blocco usa la quota Eurobet dove l'ho inserita (EV sulle quote che giochi)", key="odds_use_eurobet")
    if st.button("Compila il blocco con i dati automatici e queste quote", type="primary", key="odds_build"):
        row = overview[overview["event_id"] == event_id].iloc[0]
        label = row["competition"]
        competition = label if label in COMPETITIONS or label in CUP_COMPETITIONS else None
        with st.spinner("Scarico e calcolo i dati delle squadre…"):
            provider = DataProvider(source_cache(), football_data_key=football_data_org_key())
            sheet = provider.build(row["home_team"], row["away_team"], match_date=row["commence_time"].date(), competition=competition)
        sheet.odds = sheet_odds(quotes, fetched, eurobet, use_eurobet)
        sheet.competition = sheet.competition or label
        _use_block(sheet)

    st.markdown("**5 · Quote di chiusura** (facoltativo)")
    st.caption("Ogni scarico per campionato salva un'istantanea; per il registro vale l'ultima prima del calcio d'inizio. "
               "Per una chiusura più vicina al via, riscarica poco prima della partita (ignora la cache).")
    closing = st.multiselect("Campionati", leagues, format_func=lambda key: labels.get(key, key), key="odds_closing")
    cost = api.league_cost() * len(closing)
    if closing and _confirmed(cost, 0, "odds_confirm_closing") and st.button("Scarica ora le quote di chiusura", key="odds_closing_button"):
        for sport in closing:
            result = _run(lambda: api.league_odds(sport, force=True), labels.get(sport, sport))
            if result is not None:
                st.session_state.setdefault("odds_league", {})[sport] = (result.payload, result.fetched_at)
        st.success("Istantanee salvate: la pagina Prestazioni le usa come quote di chiusura.")
