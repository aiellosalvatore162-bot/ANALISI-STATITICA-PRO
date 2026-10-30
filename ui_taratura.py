"""Fase AM: interfaccia della taratura (solo presentazione): stato per mercato e tabella «dichiarato contro uscito»."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import taratura

LABEL_HELP = {
    "verificata": "abbastanza partite e scarto piccolo tra previsto e uscito",
    "poco verificata": "poche partite (soprattutto sopra l'80%) o scarto medio",
    "non affidabile": "scarto grande tra previsto e uscito",
}


def cell_label(market: str, pct: float | None) -> str | None:
    return taratura.load().label(market, pct)


def table_rows(market: str) -> list[dict]:
    """Righe in italiano semplice: «Quando dice 60-70%, è uscito il 65,4% delle volte (su 130 partite)»."""
    names = {"sotto 50": "sotto il 50%", "oltre 80": "oltre l'80%"}
    return [{"Fascia dichiarata": names.get(row["fascia"], f"{row['fascia']}%"),
             "Dichiarato (media)": f"{row['dichiarato']:.1%}", "Uscito davvero": f"{row['uscito']:.1%}",
             "Partite": row["n"], "Giudizio": row.get("etichetta") or "—"} for row in taratura.load().table(market)]


def render_calibration(result: dict | None = None) -> None:
    tar = taratura.load()
    with st.expander("Calibrazione: dichiarato contro uscito", expanded=False):
        if not tar.attiva:
            st.info("Taratura non attiva: le percentuali sono quelle grezze del modello.")
            return
        st.caption(f"Se l'app dice 70%, su molte partite deve uscire circa 7 volte su 10. Misurato nello storico "
                   f"(5 campionati, dati passati soltanto), aggiornato al {tar.data}.")
        summary = [{"Mercato": key, "Taratura": tar.status(key), "Partite": item.get("casi"),
                    "Scarto prima": item.get("scarto_prima"), "Scarto dopo": item.get("scarto_dopo")}
                   for key, item in tar.mercati.items() if item.get("stato") != "derivato"]
        market = st.selectbox("Mercato", [row["Mercato"] for row in summary], key="taratura_market")
        st.write(f"**{market}**: {tar.status(market)}")
        rows = table_rows(market)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True)
        if result:
            value = result.get("components", {}).get("finale", {}).get(market)
            if value is not None:
                st.write(f"Ora per questa partita: {value:.1f}% → {cell_label(market, value)}")
        st.caption(" · ".join(f"{name}: {text}" for name, text in LABEL_HELP.items()))
        st.dataframe(pd.DataFrame(summary), hide_index=True)
