"""Fase AN: pagina «Dati aggiunti» (solo presentazione): cosa è stato importato, quando, da quale fonte, quanto copre."""
from __future__ import annotations

import pandas as pd
import streamlit as st

import data_import


def render_imported() -> None:
    st.subheader("Dati aggiunti")
    st.caption("Dati portati da te o scaricati da Claude in chat, importati con `python -m tools.importa_dati <file>`. "
               "Dove c'è un dato importato per una squadra prevale sulla stima da indicatori approssimati; il motore usa solo "
               "righe con data precedente alla partita. Modelli CSV in `data/import/modelli/`.")
    log = data_import.registry()
    if not log:
        st.info("Nessun dato importato finora.")
        return
    st.dataframe(pd.DataFrame([{"Data": item["data"], "Tipo": data_import.KINDS[item["tipo"]].label if item["tipo"] in data_import.KINDS else item["tipo"],
                                "File": item["file"], "Fonte": item["fonte"], "Importate": item["importate"],
                                "Scartate": item["scartate"], "Squadre": item["squadre"],
                                "Campionati": ", ".join(item.get("campionati") or []) or "—"} for item in reversed(log)]),
                 hide_index=True, width="stretch")
    st.markdown("**Copertura attuale**")
    rows = []
    for name, kind in data_import.KINDS.items():
        stored = data_import.load_rows(name)
        teams = {row[c] for row in stored for c in kind.team_columns}
        leagues = {row["campionato"] for row in stored if row.get("campionato")}
        rows.append({"Tipo": kind.label, "Righe": len(stored), "Squadre": len(teams), "Campionati": ", ".join(sorted(leagues)) or "—",
                     "Letto dal motore": ", ".join(kind.used_by_engine) or "solo consultazione"})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    problems = [(item["file"], reason) for item in log for reason in item.get("motivi", [])]
    if problems:
        with st.expander(f"Righe scartate e motivi ({len(problems)})"):
            st.dataframe(pd.DataFrame(problems, columns=["File", "Motivo"]), hide_index=True, width="stretch")
