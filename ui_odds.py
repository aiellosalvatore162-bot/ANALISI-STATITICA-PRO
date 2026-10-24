"""Sezione Streamlit «Quote del giorno» (The Odds API) e contatore dei crediti.

Ogni scarico che costa crediti mostra prima il costo massimo e chiede una
conferma; le risposte restano in cache 30 minuti (``config/odds_api.json``),
quindi ripetere la stessa richiesta è gratuito. Il budget è mensile: avviso
giallo all'80%, seconda conferma oltre il 95%. Le quote si scaricano solo per
le competizioni con partite nel giorno (elenco eventi gratuito) e i mercati
mirati seguono il profilo scelto (default «risparmio»: corner e cartellini).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from datasources.builder import DataProvider
from datasources.oddsapi import (
    MARKET_LABELS, SOURCE, BudgetExceeded, OddsApi, OddsApiError, competition_label, day_cost, is_european_soccer,
    league_overview, merged_quotes_frame, odds_api_key, planned_cost, preselect, quote_rows, reference_quotes, sheet_odds,
)
from datasources.sources import COMPETITIONS, CUP_COMPETITIONS, football_data_org_key
from eurobet import GOAL_ANCHOR_KEYS, skip_event_markets
from ui_data import _use_block, source_cache
from ui_eurobet import find_paste, render_paste, save_sharp


@st.cache_resource(show_spinner=False)
def odds_client() -> OddsApi:
    return OddsApi(source_cache(), odds_api_key())


def render_credits(api: OddsApi | None = None) -> None:
    """Crediti rimasti nel mese, giorni rimanenti e budget suggerito oggi; avviso giallo dall'80% del budget."""
    api = api or odds_client()
    if not api.configured:
        st.caption(f"{SOURCE}: chiave ODDS_API_KEY non configurata in .streamlit/secrets.toml.")
        return
    usage = api.usage()
    api_left = "—" if usage["remaining"] is None else str(usage["remaining"])
    updated = f"agg. {usage['updated'].astimezone():%d/%m %H:%M}" if usage["updated"] else "nessuna chiamata registrata"
    st.caption(f"**Crediti {SOURCE}** · rimasti nel mese **{usage['left']}** · giorni rimanenti nel mese "
               f"{usage['days_left']} · budget suggerito oggi **{usage['suggested_today']}** "
               f"({usage['play_days_left']} giorni di gioco stimati) · spesi oggi {usage['spent_today']}, "
               f"nel mese {usage['spent_month']} su {usage['budget']} · crediti dell'API {api_left} ({updated})")
    if usage["share"] >= float(api.settings.get("soglia_avviso", 0.8)):
        st.warning(f"Budget mensile al {usage['share']:.0%}: spesi {usage['spent_month']} crediti su {usage['budget']}. "
                   f"Oltre il {float(api.settings.get('soglia_conferma', 0.95)):.0%} ogni scarico chiede una seconda conferma.")


def _run(call, label: str):
    """Esegue una chiamata mostrando avvisi ed errori; ``None`` se non riuscita (anche per budget)."""
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


def _approve(api: OddsApi, cost: int, cached: int, key: str) -> dict | None:
    """Mostra il costo e chiede la conferma; restituisce gli argomenti per le chiamate o ``None`` se non approvato.

    Oltre il 95% del budget mensile serve una seconda conferma (``allow_high``); oltre il budget il download è bloccato.
    """
    if cost == 0:
        st.caption("Costo: 0 crediti" + (f" (tutto in cache, {cached} risposte)" if cached else "") + ".")
        return {"allow_high": False}
    usage = api.usage()
    level = api.budget_level(cost, usage)
    st.caption(f"Costo massimo: **{cost} crediti**" + (f" ({cached} risposte già in cache, gratis)" if cached else "")
               + f" · dopo: {usage['spent_month'] + cost} su {usage['budget']} del mese "
               f"(suggeriti oggi {usage['suggested_today']}).")
    if level == "blocco":
        st.error(f"Download bloccato: supera il budget mensile ({usage['spent_month']} + {cost} su {usage['budget']}) "
                 f"o i crediti rimasti dell'API. Riduci partite o mercati, oppure alza «budget_mensile» in config/odds_api.json.")
        return None
    if cost > usage["suggested_today"]:
        st.caption(f"Più del budget suggerito per oggi ({usage['suggested_today']} crediti).")
    if not st.checkbox(f"Confermo la spesa di {cost} crediti", key=f"{key}_{cost}"):
        return None
    if level == "conferma":
        st.warning(f"Con questo download si supera il {float(api.settings.get('soglia_conferma', 0.95)):.0%} del budget mensile.")
        if not st.checkbox("Confermo di superare la soglia del budget mensile", key=f"{key}_{cost}_alta"):
            return None
        return {"allow_high": True}
    return {"allow_high": False}


def render_day_summary(summary: dict, *, title: str = "Costo previsto della giornata") -> None:
    """Riepilogo prima di uno scarico multiplo (es. «Analizza tutte»): competizioni, partite mirate, crediti totali."""
    names = ", ".join(competition_label(sport) for sport in summary["competitions"]) or "nessuna"
    markets = ", ".join(MARKET_LABELS.get(market, market) for market in summary["markets"])
    st.info(f"**{title}**: {len(summary['competitions'])} competizioni con partite ({names}) · "
            f"quote per campionato {summary['league']} crediti · {summary['targeted']} partite mirate × fino a "
            f"{summary['per_event']} ({markets}) = {summary['event']} crediti · punteggi del giorno dopo circa "
            f"{summary['scores']} · **totale fino a {summary['total']} crediti** (oggi {summary['today']}).")


def _profile_choice(api: OddsApi) -> list[str]:
    """Profilo dei mercati mirati: «risparmio» di default, «completo» o una scelta personalizzata."""
    profiles = api.profiles
    default = str(api.settings.get("profilo_mirato", "risparmio"))
    options = list(profiles) + ["personalizzato"]
    describe = lambda name: (f"{name.capitalize()}: " + ", ".join(MARKET_LABELS.get(m, m) for m in profiles[name])
                             + f" (fino a {api.event_cost(profiles[name])} crediti a partita)") if name in profiles \
        else "Personalizzato: scegli i mercati"
    profile = st.radio("Profilo mercati mirati", options, index=options.index(default) if default in options else 0,
                       format_func=describe, key="odds_profile")
    if profile in profiles:
        return profiles[profile]
    every = list(dict.fromkeys(market for markets in profiles.values() for market in markets))
    return st.multiselect("Mercati", every, profiles.get(default, []), format_func=lambda key: MARKET_LABELS.get(key, key),
                          key="odds_markets")


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
        found, _, warnings = api.sports_with_matches(chosen, day)
        for warning in warnings:
            st.warning(warning)
        st.session_state["odds_events"] = found
        st.session_state["odds_events_day"] = day
    events = st.session_state.get("odds_events")
    if events is None:
        return
    if events.empty:
        st.info("Nessuna partita nel giorno scelto per queste competizioni.")
        return
    leagues = sorted(events["sport"].unique())
    idle = [labels.get(sport, sport) for sport in chosen if sport not in leagues]
    st.caption(f"{len(events)} partite il {st.session_state['odds_events_day']:%d/%m/%Y} in {len(leagues)} competizioni"
               + (f"; senza partite (nessuna quota scaricata): {', '.join(idle)}" if idle else "") + ".")
    limit = int(api.settings.get("max_partite_mirate", 10))
    markets = _profile_choice(api)
    render_day_summary(day_cost(api, leagues, min(limit, len(events)), markets))

    st.markdown("**2 · Quote 1X2 e Over/Under per campionato** (servono per l'ancoraggio e la preselezione)")
    calls = [(f"/sports/{sport}/odds", api.league_params(), api.league_cost()) for sport in leagues]
    cost, cached = planned_cost(api, calls)
    st.caption(f"Una chiamata per ciascuna delle {len(leagues)} competizioni con partite nel giorno, regione {api.region}, "
               f"mercati {api.league_params()['markets']}: {api.league_cost()} crediti ciascuna.")
    approved = _approve(api, cost, cached, "odds_confirm_league")
    if approved is not None and st.button("Scarica le quote per campionato", key="odds_league_button"):
        for sport in leagues:
            result = _run(lambda: api.league_odds(sport, **approved), labels.get(sport, sport))
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

    st.markdown("**3 · Mercati aggiuntivi per le partite preselezionate** (profilo scelto sopra)")
    names = dict(zip(overview["event_id"], overview["home_team"] + " - " + overview["away_team"]))
    selected = st.multiselect(f"Partite (massimo {limit}; proposta del sistema: più disaccordo tra bookmaker)", list(names),
                              preselect(overview, limit), format_func=names.get, max_selections=limit, key="odds_selected")
    sport_of = dict(zip(overview["event_id"], overview["sport"]))
    teams_of = dict(zip(overview["event_id"], zip(overview["home_team"], overview["away_team"])))
    # Con la scala Eurobet di corner o cartellini già incollata, quei mercati non si scaricano (risparmio crediti).
    event_markets = {event_id: skip_event_markets(find_paste(*teams_of[event_id]), markets) for event_id in selected}
    saved = [names[event_id] for event_id in selected if len(event_markets[event_id]) < len(markets)]
    calls = [(f"/sports/{sport_of[event_id]}/events/{event_id}/odds", api.event_params(event_markets[event_id]),
              api.event_cost(event_markets[event_id])) for event_id in selected if event_markets[event_id]]
    cost, cached = planned_cost(api, calls)
    st.caption(f"Mercati: {', '.join(MARKET_LABELS.get(m, m) for m in markets) or 'nessuno'}. Costo per partita = mercati "
               "restituiti × regioni: si pagano solo i mercati che i bookmaker quotano davvero.")
    if saved:
        st.caption("Quote Eurobet di corner/cartellini già incollate (non si scaricano dall'API): " + ", ".join(saved) + ".")
    approved = _approve(api, cost, cached, "odds_confirm_event") if calls else None
    if approved is not None and st.button("Scarica i mercati aggiuntivi", key="odds_event_button"):
        for event_id in selected:
            if not event_markets[event_id]:
                continue
            result = _run(lambda: api.event_odds(sport_of[event_id], event_id, event_markets[event_id], **approved),
                          names[event_id])
            if result is not None:
                st.session_state.setdefault("odds_event", {})[event_id] = (result.payload, result.fetched_at)

    st.markdown("**4 · Partita da simulare**")
    event_id = st.selectbox("Partita", list(names), format_func=names.get, key="odds_match")
    extra = st.session_state.get("odds_event", {}).get(event_id)
    league_event, league_fetched = league_events[event_id]
    frame = merged_quotes_frame([league_event, extra[0] if extra else None])
    quotes = reference_quotes(frame, api.settings.get("riferimento"))
    fetched = max(value for value in (league_fetched, extra[1] if extra else None) if value is not None)
    home_team, away_team = teams_of[event_id]
    with st.expander("Incolla quote Eurobet di questa partita", expanded=bool(find_paste(home_team, away_team))):
        paste = render_paste(home_team, away_team, f"odds_paste_{event_id}")
    eurobet_state = st.session_state.setdefault("odds_eurobet", {}).setdefault(event_id, {})
    if paste is not None:
        # Le quote incollate riempiono la colonna Eurobet dove è ancora vuota.
        for market, price in paste.odds().items():
            if market in quotes:
                eurobet_state.setdefault(market, price)
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
        # Quota sharp per l'ancoraggio dei gol, anche quando il blocco usa le quote Eurobet.
        sharp = {key: quotes[key].price for key in GOAL_ANCHOR_KEYS if key in quotes}
        reference = quotes["1"].reference if "1" in quotes else SOURCE
        for name_pair in {(home_team, away_team), (sheet.home, sheet.away)}:
            save_sharp(*name_pair, sharp, reference)
        _use_block(sheet)

    st.markdown("**5 · Quote di chiusura** (facoltativo)")
    st.caption("Ogni scarico per campionato salva un'istantanea; per il registro vale l'ultima prima del calcio d'inizio. "
               "Per una chiusura più vicina al via, riscarica poco prima della partita (ignora la cache).")
    closing = st.multiselect("Campionati", leagues, format_func=lambda key: labels.get(key, key), key="odds_closing")
    cost = api.league_cost() * len(closing)
    approved = _approve(api, cost, 0, "odds_confirm_closing") if closing else None
    if approved is not None and st.button("Scarica ora le quote di chiusura", key="odds_closing_button"):
        for sport in closing:
            result = _run(lambda: api.league_odds(sport, force=True, **approved), labels.get(sport, sport))
            if result is not None:
                st.session_state.setdefault("odds_league", {})[sport] = (result.payload, result.fetched_at)
        st.success("Istantanee salvate: la pagina Prestazioni le usa come quote di chiusura.")
