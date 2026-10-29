"""Pagina Oggi, fase Z: selezione del giorno, «Incolla quote», raccolta The Odds API, «I miei mercati», combo builder.

Tutto passa dall'archivio unico della giornata (``day_archive``), tenuto in ``st.session_state["day_archive"]``: le
altre parti dell'app (pagina Partita, scheda, registro, multiple, Excel) leggono le stesse voci.
"""

from __future__ import annotations

from datetime import date, datetime
import time

import pandas as pd
import streamlit as st

import day_archive
from datasources.stats import FieldValue

ARCHIVE_KEY = "day_archive"


def archive() -> dict:
    return st.session_state.setdefault(ARCHIVE_KEY, {})


def entry_for(home: str | None, away: str | None, day: date | None = None) -> dict | None:
    if not home or not away:
        return None
    key = day_archive.find(archive(), home, away, day)
    return archive()[key] if key else None


def odds_fields(entry: dict) -> dict:
    """Campi quota del blocco (1X2 e Over/Under 2.5) dalle quote consolidate dell'archivio, con fonte e ora."""
    from eurobet import GOAL_ANCHOR_KEYS

    fields = {}
    consolidated = day_archive.consolidated(entry)
    reads = {quote.mercato: quote.ora_lettura for quote in day_archive.quotes_of(entry)}
    for key in GOAL_ANCHOR_KEYS:
        item = consolidated.get(key)
        if item is None:
            continue
        when = reads.get(key)
        fields[key] = FieldValue(item.quota, f"quote della giornata · {item.riferimento}",
                                 datetime.fromisoformat(when) if when else None,
                                 note=" · ".join(f"{name} {value:.2f}" for name, value in sorted(item.quote.items())))
    return fields


# --- 1. Selezione del giorno --------------------------------------------------------------------------------

def render_selection(events: pd.DataFrame | None) -> None:
    """Caselle «Seleziona» e «Da giocare» per le partite trovate; la selezione resta tra una competizione e l'altra."""
    from today import TodayMatch

    store = archive()
    listed = []
    if events is not None and not events.empty:
        for row in events.itertuples():
            commence = pd.Timestamp(row.commence_time).to_pydatetime()
            match = TodayMatch(row.event_id, row.sport, row.competition, commence, row.home_team, row.away_team)
            listed.append(day_archive.add_match(store, match))
    st.markdown(f"**{day_archive.counter_text(store)}**")
    columns = st.columns(2)
    if columns[0].button("Seleziona tutte della competizione", key="sel_all", disabled=not listed):
        skipped = day_archive.select_all(store, listed)
        if skipped:
            st.session_state["selection_warning"] = (f"Limite raggiunto: {len(skipped)} partite non selezionate "
                                                     f"({day_archive.counter_text(store)}).")
        st.rerun()
    if columns[1].button("Deseleziona tutte", key="sel_none"):
        day_archive.deselect_all(store)
        st.rerun()
    warning = st.session_state.pop("selection_warning", None)
    if warning:
        st.warning(warning)
    shown = list(dict.fromkeys([*listed, *(entry["key"] for entry in day_archive.selected(store))]))
    if not shown:
        return
    table = pd.DataFrame([{
        "Ora": store[key].get("commence", "")[11:16], "Competizione": store[key].get("competition", ""),
        "Partita": f"{store[key]['home']} - {store[key]['away']}", "Seleziona": bool(store[key].get("selected")),
        "Da giocare": bool(store[key].get("to_play")), "Quote": len([q for q in store[key]["quotes"] if q.get("mercato")]),
    } for key in shown])
    edited = st.data_editor(table, hide_index=True, width="stretch", key=f"selection_{len(shown)}_{hash(tuple(shown))}",
                            disabled=["Ora", "Competizione", "Partita", "Quote"],
                            column_config={"Seleziona": st.column_config.CheckboxColumn(width="small"),
                                           "Da giocare": st.column_config.CheckboxColumn(width="small")})
    messages = []
    changed = False
    for key, (_, row) in zip(shown, edited.iterrows()):
        entry = store[key]
        if bool(row["Seleziona"]) != bool(entry.get("selected")):
            message = day_archive.set_selection(store, key, selected=bool(row["Seleziona"]))
            changed = changed or message is None
            messages += [message] if message else []
        if bool(row["Da giocare"]) != bool(entry.get("to_play")):
            message = day_archive.set_selection(store, key, to_play=bool(row["Da giocare"]))
            changed = changed or message is None
            messages += [message] if message else []
    if messages:
        st.session_state["selection_warning"] = " ".join(messages)
    if changed or messages:
        st.rerun()
    st.caption("Solo le partite selezionate entrano in Prepara, Analizza tutte e raccolta quote; le altre restano qui "
               "senza consumare tempo né crediti. «Da giocare»: quote del livello B e combo builder.")


# --- 4. Incolla quote --------------------------------------------------------------------------------------

def read_pages(text: str, bookmaker: str, today: date | None = None):
    """Pagine, formato e abbinamento alle partite selezionate (senza scrivere nulla nell'archivio)."""
    from quotes.pages import Target, assign_pages, split_pages

    pages = split_pages(text, today)
    targets = [Target(entry["key"], entry["home"], entry["away"],
                      datetime.fromisoformat(entry["commence"]) if entry.get("commence") else None)
               for entry in day_archive.selected(archive())]
    return pages, assign_pages(pages, targets)


def apply_pages(pages, assignments, choices: dict[int, str], bookmaker: str) -> list[dict]:
    """Quote delle pagine abbinate (o scelte a mano se ambigue) nell'archivio; riepilogo per partita."""
    from my_markets import FAMILIES
    from quotes.adapters import eurobet as eurobet_adapter, generico

    store = archive()
    summary = []
    for assignment in assignments:
        key = assignment.key or choices.get(assignment.index)
        page = pages[assignment.index]
        if not key or page.format == "sconosciuto":
            continue
        entry = store[key]
        label = f"{entry['home']} - {entry['away']}"
        if page.format == "eurobet":
            quotes, paste = eurobet_adapter.from_text(page.body, label)
            unknown, book = list(paste.unknown_sections), eurobet_adapter.BOOKMAKER
        else:
            quotes, unknown, book = generico.from_text(page.body, label, bookmaker), [], bookmaker.strip()
        day_archive.add_page(store, key, text=page.body, title=page.title, bookmaker=book, page_format=page.format)
        counts = day_archive.add_quotes(store, key, quotes)
        have = set(day_archive.engine_odds(entry))
        wanted = {market for _, keys in FAMILIES for market in keys}
        summary.append({"Partita": label, "Bookmaker": book, "Mercati letti": len([q for q in quotes if q.mercato]),
                        "Sospese": len([q for q in quotes if q.quota is None]),
                        "Non simulate": len([q for q in quotes if q.mercato is None]),
                        "I miei mercati mancanti": len(wanted - have), "Sezioni sconosciute": ", ".join(unknown),
                        "Conflitti": counts["conflitti"]})
    return summary


def render_paste_box() -> None:
    from quotes.pages import STATUS_AMBIGUOUS, STATUS_MATCHED

    st.subheader("Incolla quote")
    st.caption("Una o più pagine di qualunque bookmaker, una dopo l'altra: ogni pagina comincia con «Casa - Ospite» e la "
               "riga «gg/mm hh:mm». Formato Eurobet (un token per riga) o generico (1, X, 2, OVER 2.5, GG… con la quota). "
               "Le pagine si abbinano alle partite selezionate; le ambigue si scelgono qui, mai in silenzio.")
    columns = st.columns([4, 1])
    text = columns[0].text_area("Pagine di quote", key="paste_all", height=160)
    bookmaker = columns[1].text_input("Bookmaker (formato generico)", key="paste_bookmaker")
    if not text.strip():
        return
    started = time.perf_counter()
    pages, assignments = read_pages(text, bookmaker)
    if not pages:
        st.warning("Nessuna pagina riconosciuta: manca il titolo «Casa - Ospite» seguito dalla riga «gg/mm hh:mm».")
        return
    store = archive()
    labels = {entry["key"]: f"{entry['home']} - {entry['away']}" for entry in day_archive.selected(store)}
    rows, choices = [], {}
    for assignment, page in zip(assignments, pages):
        rows.append({"Titolo letto": page.title, "Data": page.when.strftime("%d/%m %H:%M") if page.when else page.date_text,
                     "Formato": page.format, "Esito": assignment.status,
                     "Partita": labels.get(assignment.key, ""), "Nota": "; ".join([assignment.message, *page.warnings]).strip("; ")})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    for assignment in assignments:
        if assignment.status == STATUS_AMBIGUOUS:
            options = ["— scegli —", *assignment.candidates]
            choice = st.selectbox(f"Pagina «{assignment.title}»: quale partita?", options, key=f"ambiguous_{assignment.index}",
                                  format_func=lambda key: labels.get(key, key))
            if choice != options[0]:
                choices[assignment.index] = choice
    unknown = [page.title for page in pages if page.format == "sconosciuto"]
    if unknown:
        st.warning("Formato non riconosciuto (non letto, mai indovinato): " + ", ".join(unknown))
    if any(page.format == "generico" for page in pages) and not bookmaker.strip():
        st.info("Ci sono pagine in formato generico: indica il nome del bookmaker.")
    ready = sum(1 for a in assignments if a.status == STATUS_MATCHED) + len(choices)
    st.caption(f"Lettura in {time.perf_counter() - started:.2f} s.")
    if st.button(f"Salva le quote ({ready} pagine)", key="paste_apply", disabled=not ready, type="primary"):
        st.session_state["paste_summary"] = apply_pages(pages, assignments, choices, bookmaker)
        st.session_state["paste_all"] = ""
        st.rerun()


def render_paste_summary() -> None:
    summary = st.session_state.get("paste_summary")
    if summary:
        st.markdown("**Ultimo incolla, per partita**")
        st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch")
    render_conflicts()


def render_conflicts() -> None:
    """Conflitti: una quota diversa da quella salvata cambia solo dopo conferma."""
    store = archive()
    pending = [(key, index, item) for key, entry in store.items() for index, item in enumerate(entry.get("pending", []))]
    if not pending:
        return
    st.warning(f"{len(pending)} quote diverse da quelle già salvate: cambiano solo se confermi.")
    st.dataframe(pd.DataFrame([{"Partita": f"{store[key]['home']} - {store[key]['away']}", "Mercato": item.get("mercato") or item["selezione"],
                                "Bookmaker": item["bookmaker"], "Attuale": item["attuale"], "Nuova": item["quota"],
                                "Fonte": item["fonte"]} for key, _, item in pending]), hide_index=True, width="stretch")
    columns = st.columns(2)
    if columns[0].button("Conferma le nuove quote", key="pending_accept"):
        for key in {key for key, _, _ in pending}:
            day_archive.resolve_pending(store, key, accept=True)
        st.rerun()
    if columns[1].button("Tieni le quote salvate", key="pending_discard"):
        for key in {key for key, _, _ in pending}:
            day_archive.resolve_pending(store, key, accept=False)
        st.rerun()


# --- 6. Raccolta The Odds API --------------------------------------------------------------------------------

def render_collection(api) -> None:
    from quotes.collect import collect, ledger_rows, plan_level_a, plan_level_b, preconto

    st.subheader("Raccolta quote The Odds API (a crediti)")
    store = archive()
    chosen, playing = day_archive.selected(store), day_archive.to_play(store)
    if not chosen:
        st.caption("Seleziona le partite per vedere il costo.")
        return
    if not api.configured:
        st.info("Serve ODDS_API_KEY in .streamlit/secrets.toml per raccogliere le quote dall'API.")
        return
    for level, plan, label in (("A", plan_level_a(api, chosen), f"Livello A · 1X2 e U/O goal per le {len(chosen)} selezionate"),
                               ("B", plan_level_b(api, playing), f"Livello B · corner e cartellini per le {len(playing)} «Da giocare»")):
        check = preconto(api, plan)
        st.markdown(f"**{label}**: {check['chiamate']} chiamate, {check['stimati']} crediti stimati · oggi {check['speso_oggi']} "
                    f"spesi su un tetto di {check['tetto_giorno']} · residui del mese {check['residui_mese']}")
        if not check["consentito"]:
            st.error(f"Non parte nulla: {check['motivo']}.")
        confirm = st.checkbox(f"Confermo il costo del livello {level} ({check['stimati']} crediti)", key=f"confirm_level_{level}")
        if st.button(f"Raccogli livello {level}", key=f"collect_{level}", disabled=not (confirm and check["consentito"] and plan.calls)):
            outcome = collect(api, plan, store, confirmed=True)
            missing = st.session_state.setdefault("not_collected", {})
            missing[level] = plan.not_offered + outcome["non_raccolte"]
            st.session_state["collect_message"] = (f"Livello {level}: {outcome['eseguite']} chiamate, {outcome['reali']} crediti reali.")
            st.rerun()
    message = st.session_state.pop("collect_message", None)
    if message:
        st.success(message)
    missing = [row for rows in st.session_state.get("not_collected", {}).values() for row in rows]
    if missing:
        with st.expander(f"Quote non raccolte ({len(missing)})", expanded=False):
            st.dataframe(pd.DataFrame(missing), hide_index=True, width="stretch")
    ledger = ledger_rows(api)
    if ledger:
        with st.expander("Registro crediti della raccolta", expanded=False):
            st.dataframe(pd.DataFrame(ledger), hide_index=True, width="stretch")


# --- 8. I miei mercati e 9. combo builder -----------------------------------------------------------------

def my_market_rows(analyses) -> list[dict]:
    from my_markets import day_rows

    items = []
    for analysis in analyses:
        if not analysis.ok:
            continue
        entry = entry_for(analysis.match.home, analysis.match.away, analysis.match.commence_time.date())
        items.append((analysis.match.label, analysis.result, day_archive.consolidated(entry) if entry else {}))
    return day_rows(items)


def render_my_markets(analyses) -> None:
    rows = my_market_rows(analyses)
    if not rows:
        return
    st.subheader("I miei mercati")
    st.caption("Probabilità del simulatore per tutte le partite analizzate; quota, bookmaker, quota equa ed EV solo se la "
               "quota è stata raccolta o incollata. Clic sull'intestazione per ordinare.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Prob %": st.column_config.NumberColumn(format="%.1f"),
                                "Quota": st.column_config.NumberColumn(format="%.2f"),
                                "Quota equa": st.column_config.NumberColumn(format="%.2f")})


def render_combo(analyses) -> None:
    import combo

    playing = [(index, analysis) for index, analysis in enumerate(analyses)
               if analysis.ok and (analysis.result or {}).get("event_samples")]
    st.subheader("Combo builder")
    if not playing:
        st.caption("Per le partite «Da giocare» analizzate qui si combinano più selezioni della stessa partita.")
        return
    labels = {index: analysis.match.label for index, analysis in playing}
    index = st.selectbox("Partita", list(labels), format_func=labels.get, key="combo_match")
    result = dict(playing)[index].result
    legs = st.multiselect("Selezioni (stessa partita)", combo.available(result), key=f"combo_legs_{index}",
                          placeholder="es. Over 2.5 gol e Goal")
    price = st.number_input("Quota del bookmaker (facoltativa)", min_value=0.0, step=0.05, key=f"combo_odds_{index}")
    if len(legs) < 2:
        return
    data = combo.evaluate(result, legs, price if price > 1.0 else None)
    columns = st.columns(4)
    columns[0].metric("Probabilità congiunta", f"{data['congiunta']:.1%}")
    columns[1].metric("Quota equa", f"{data['quota_equa']:.2f}" if data["quota_equa"] else "—")
    columns[2].metric("Prodotto delle marginali (solo confronto)", f"{data['prodotto']:.1%}")
    columns[3].metric("EV con la quota", f"{data['ev']:+.1%}" if data["ev"] is not None else "—")
    st.caption(f"Congiunta = simulazioni in cui tutte le selezioni sono vere ({data['simulazioni']:,} run, stessi della "
               "partita). Il prodotto delle marginali ignora la correlazione: è solo un confronto.".replace(",", "."))
