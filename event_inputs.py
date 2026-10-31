"""Fase AO: ingressi del motore a eventi da tutti i dati dell'app (``MatchConfig.event_inputs``).

Nessun dato resta «solo consultabile»: formazione e assenti (tiri e qualità dei tiri), stile misurato o importato
(termini del dizionario tattico), scheda tattica (profilo qualitativo, solo dove manca la misura), modulo (corsie), arbitro
(falli). Ogni effetto viene da una stima su dati (``tools.ao_giocatori``, ``tools.ao_corsie``, ``tools.stima_motore``,
``referee_stats``): qui non c'è nessun numero scelto a mano. Ogni riga della scheda dice dato, valore, effetto, fonte e
intervallo; un dato mancante è dichiarato («dato mancante, importalo in data/import/»), mai inventato.

Formato del risultato (``build``):
    {"home": {"profile", "module", "shot_scale", "quality_scale", "type_scale", "corner_cross_scale"}, "away": {...},
     "formazione": {"home": {"attack", "defense"}, "away": {...}} | None, "arbitro": {...} | None, "schede": [righe]}
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parent
PLAYERS_PATH = ROOT / "config" / "giocatori.json"
EVENTS_PATH = ROOT / "config" / "motore_eventi.json"
ROLES = ("POR", "DIF", "CEN")
SIDES = (("home", "casa"), ("away", "ospite"))
MISSING = "dato mancante, importalo in data/import/"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fmt_ci(item: Mapping[str, Any]) -> str:
    low, high = item.get("ic95") or (None, None)
    return f"{item['stima']:+.3f} (IC 95% {low:+.3f} … {high:+.3f})" if low is not None else f"{item['stima']:+.3f}"


# ------------------------------------------------------------------------------------------------ stadio 2: giocatori


def lineup_scales(lineup: Mapping[str, Any] | None, cfg: Mapping[str, Any] | None = None
                  ) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]] | None, list[dict]]:
    """Da ``lineup.get_lineup_params``: (scale per lato, fattori sui gol per λ/μ, righe della scheda).

    tiri casa = rapporto_tiri_casa^γ_t · exp(Σ δ_t,ruolo · (mancanti_ospite,ruolo − media)); qualità (npxG/tiro) uguale con γ_q, δ_q.
    Sui gol (prima dell'ancoraggio, al posto del fattore della fase AL): attacco = tiri·qualità della propria formazione,
    difesa = exp(Σ (δ_t+δ_q)·mancanti propri) sui gol dell'avversario."""
    cfg = (cfg if cfg is not None else _load(PLAYERS_PATH)).get("motore_eventi")
    scales = {"home": {}, "away": {}}
    if not lineup or not cfg:
        reason = "coefficienti non stimati (python -m tools.ao_giocatori --salva)" if lineup else "formazione non disponibile"
        return scales, None, [{"dato": "giocatori e formazione", "lato": "—", "valore": "—", "effetto": "nessuno", "fonte": reason}]
    sides = {"home": lineup.get("casa") or {}, "away": lineup.get("ospite") or {}}
    if not all(side.get("disponibile") and side.get("eventi") for side in sides.values()):
        return scales, None, [{"dato": "giocatori e formazione", "lato": "—", "valore": "—", "effetto": "nessuno",
                               "fonte": "formazione non disponibile per entrambe le squadre (Understat)"}]
    rows, goals = [], {}
    # quote mancanti centrate sulla media del campione di stima (ogni giornata ruota in media un quarto dei reparti)
    center = {r: float((cfg.get("media_mancanti") or {}).get(r, 0.0)) for r in ROLES}
    for side, label in SIDES:
        own, other = sides[side]["eventi"], sides["away" if side == "home" else "home"]["eventi"]
        log_parts = {}
        for key, ratio in (("tiri", own["rapporto_tiri"]), ("qualita", own["rapporto_qualita"])):
            block = cfg[key]
            attack = block["attacco"]["stima"] * math.log(max(float(ratio), 1e-6))
            defense = sum(block[f"difesa_{r}"]["stima"] * (float(other["quota_minuti_mancanti"].get(r, 0.0)) - center[r])
                          for r in ROLES)
            log_parts[key] = (attack, defense)
        scales[side] = {"shot_scale": math.exp(sum(log_parts["tiri"])), "quality_scale": math.exp(sum(log_parts["qualita"]))}
        own_defense = sum((cfg["tiri"][f"difesa_{r}"]["stima"] + cfg["qualita"][f"difesa_{r}"]["stima"])
                          * (float(own["quota_minuti_mancanti"].get(r, 0.0)) - center[r]) for r in ROLES)
        goals[side] = {"attack": math.exp(log_parts["tiri"][0] + log_parts["qualita"][0]), "defense": math.exp(own_defense)}
        rows += [
            {"dato": "formazione: tiri", "lato": label, "valore": f"XI atteso/XI tipo {own['rapporto_tiri']:.3f}",
             "effetto": f"×{scales[side]['shot_scale']:.3f} sui tiri non su rigore",
             "fonte": f"esponente {_fmt_ci(cfg['tiri']['attacco'])}; reparti mancanti dell'avversario {other['quota_minuti_mancanti']}"},
            {"dato": "formazione: qualità", "lato": label, "valore": f"npxG/tiro XI atteso/XI tipo {own['rapporto_qualita']:.3f}",
             "effetto": f"×{scales[side]['quality_scale']:.3f} sulla conversione",
             "fonte": f"esponente {_fmt_ci(cfg['qualita']['attacco'])}"},
        ]
    rows.append({"dato": "difesa e portiere", "lato": "entrambi", "valore": "quota minuti mancanti POR/DIF/CEN",
                 "effetto": "; ".join(f"{r}: tiri {_fmt_ci(cfg['tiri'][f'difesa_{r}'])}, qualità {_fmt_ci(cfg['qualita'][f'difesa_{r}'])}"
                                      for r in ROLES),
                 "fonte": f"Understat {cfg.get('partite', '?')} partite ({cfg.get('data', '')}), tools.ao_giocatori"})
    return scales, goals, rows


# ------------------------------------------------------------------------------------------------ stadio 3: corsie


def lane_scales(home_module: str | None, away_module: str | None, cfg: Mapping[str, Any] | None = None,
                wides: Mapping[str, Mapping[str, float]] | None = None) -> tuple[dict[str, dict[str, Any]], list[dict]]:
    """Corsie dei moduli: cross, corner da cross e tiri di testa da cross, stimati in ``motore_eventi.corsie``.

    log y = β_fasce,y·(larghi propri − media) + β_scontro,y·(larghi propri − larghi difensivi avversari − media), per
    y = cross / corner da cross / testa da cross (``tools.ao_corsie``). Senza stima o senza moduli restano 1, dichiarato."""
    cfg = (cfg if cfg is not None else _load(EVENTS_PATH)).get("corsie")
    out = {"home": {}, "away": {}}
    if not cfg or not cfg.get("attive"):
        return out, [{"dato": "moduli e corsie", "lato": "—", "valore": f"{home_module or '—'} / {away_module or '—'}",
                      "effetto": "nessuno", "fonte": "corsie non stimate o spente (python -m tools.ao_corsie --salva)"}]
    if not wides and (not home_module or not away_module):
        return out, [{"dato": "moduli e corsie", "lato": "—", "valore": f"{home_module or '—'} / {away_module or '—'}",
                      "effetto": "nessuno", "fonte": "modulo mancante (scheda tattica o " + MISSING + ")"}]
    import formation

    # ``wides``: larghi già contati dalle posizioni dei titolari (verifica storica), altrimenti dal modulo della scheda
    wides = wides or {"home": formation.wide_players(home_module), "away": formation.wide_players(away_module)}
    rows = []
    for side, label in SIDES:
        own, other = (home_module, away_module) if side == "home" else (away_module, home_module)
        wide = wides[side]
        duel = wide["attacco"] - wides["away" if side == "home" else "home"]["difesa"]

        def factor(outcome: str) -> float:
            block = cfg[outcome]
            return math.exp(block["fasce"]["stima"] * (wide["attacco"] - cfg["media_larghi"])
                            + block["scontro"]["stima"] * (duel - cfg["media_scontro"]))

        cross, corner, head = factor("cross"), factor("corner_da_cross"), factor("testa_da_cross")
        out[side] = {"type_scale": {"testa_da_cross": head}, "corner_cross_scale": corner, "cross": cross}
        rows.append({"dato": "moduli e corsie", "lato": label,
                     "valore": f"{own} (larghi {wide['attacco']:.0f}, scontro {duel:+.0f}) contro {other}",
                     "effetto": f"cross ×{cross:.3f}, corner da cross ×{corner:.3f}, tiri di testa da cross ×{head:.3f}",
                     "fonte": (f"corner: fasce {_fmt_ci(cfg['corner_da_cross']['fasce'])}, scontro "
                               f"{_fmt_ci(cfg['corner_da_cross']['scontro'])}; {cfg.get('fonte', '')}")})
    return out, rows


# ------------------------------------------------------------------------------------------------ stadio 4: stile


def _label(value: float, cuts: tuple[float, float], labels: tuple[str, str, str]) -> str:
    return labels[0] if value < cuts[0] else labels[2] if value > cuts[1] else labels[1]


def style_terms(style: Mapping[str, Any] | None, imported: Mapping[str, Any] | None, sheet_terms: Mapping[str, Any] | None,
                league_cuts: Mapping[str, tuple[float, float]] | None = None,
                cfg: Mapping[str, Any] | None = None) -> tuple[dict[str, Any], list[dict]]:
    """Termini del dizionario per una squadra: dato importato > misura (Understat) > scheda tattica (qualitativa).

    I beta del dizionario sono stimati sui terzili di stagione (StatsBomb): il dato misurato si porta allo stesso terzile
    (soglie del campionato in ``league_cuts`` per le misure Understat, soglie StatsBomb in ``motore_eventi.soglie_stile``
    per i valori importati). Termini senza indicatore restano quelli della scheda o neutri, dichiarati."""
    cfg = cfg if cfg is not None else _load(EVENTS_PATH)
    cuts = cfg.get("soglie_stile") or {}
    terms: dict[str, Any] = {}
    rows: list[dict] = []
    params = (style or {}).get("parametri") or {}
    imported = imported or {}
    sheet_terms = dict(sheet_terms or {})

    def take(term: str, value: str, source: str, measure: str) -> None:
        terms[term] = value
        rows.append({"dato": f"stile: {term}", "valore": value, "fonte": f"{source} ({measure})"})

    # possesso: possesso importato > quota di tiri (proxy, terzile nel campionato) > scheda
    if imported.get("possesso") is not None and cuts.get("possesso"):
        take("possesso", _label(float(imported["possesso"]) / 100.0, tuple(cuts["possesso"]), ("diretto", "misto", "palla_a_terra")),
             "importato", f"possesso {float(imported['possesso']):.1f}%")
    elif (params.get("quota_tiri") or {}).get("valore") is not None and (league_cuts or {}).get("quota_tiri"):
        value = float(params["quota_tiri"]["valore"])
        take("possesso", _label(value, tuple(league_cuts["quota_tiri"]), ("diretto", "misto", "palla_a_terra")),
             "misurato, proxy quota di tiri", f"{value:.3f}, terzile del campionato")
    # pressing: PPDA importato > PPDA Understat (basso PPDA = pressing alto), terzili del campionato
    ppda = imported.get("ppda") if imported.get("ppda") is not None else (params.get("ppda") or {}).get("valore")
    if ppda is not None and (league_cuts or {}).get("ppda"):
        take("pressing", _label(float(ppda), tuple(league_cuts["ppda"]), ("alto", "medio", "basso")),
             "importato" if imported.get("ppda") is not None else "misurato (Understat)", f"PPDA {float(ppda):.1f}")
    # cross per partita: solo importato (nessuna fonte gratuita), soglie StatsBomb
    if imported.get("cross") is not None and cuts.get("cross"):
        take("fasce_cross", _label(float(imported["cross"]), tuple(cuts["cross"]), ("basso", "medio", "alto")),
             "importato", f"{float(imported['cross']):.1f} cross per partita")
    for term, raw in sheet_terms.items():
        if term not in terms:
            terms[term] = raw
            rows.append({"dato": f"stile: {term}", "valore": raw, "fonte": "scheda tattica (qualitativo, nessuna misura)"})
        elif str(raw) != str(terms[term]):
            rows.append({"dato": f"stile: {term}", "valore": raw, "fonte": f"scheda tattica: NON usata, prevale il dato ({terms[term]})"})
    for term, reason in (("marcatura", "difesa a uomo/zona: " + MISSING), ("recuperi_alti", "recuperi alti: " + MISSING),
                         ("reazione_svantaggio", "reazioni allo svantaggio: effetto medio dello stato di partita, per squadra " + MISSING),
                         ("reazione_vantaggio", "reazioni al vantaggio: effetto medio dello stato di partita, per squadra " + MISSING)):
        if term not in terms:
            rows.append({"dato": f"stile: {term}", "valore": "—", "fonte": reason})
    return terms, rows


def league_cuts(store: Any, league: str | None, when: Any, days: int = 365) -> dict[str, tuple[float, float]]:
    """Terzili delle medie di squadra nel campionato (ultimi ``days`` giorni prima della partita) per quota_tiri e ppda."""
    if store is None or league is None:
        return {}
    import pandas as pd

    when = pd.Timestamp(when).normalize()
    table = store.table
    window = table[(table["league"] == league) & (table["date"] < when) & (table["date"] >= when - pd.Timedelta(days=days))]
    out = {}
    for column in ("quota_tiri", "ppda"):
        if column not in window:
            continue
        means = window.groupby("key")[column].mean().dropna()
        if len(means) >= 6:
            out[column] = (float(np.percentile(means, 100 / 3)), float(np.percentile(means, 200 / 3)))
    return out


# ------------------------------------------------------------------------------------------------ stadio 5: arbitro


def referee(extra: Mapping[str, Any] | None, cfg: Mapping[str, Any] | None = None) -> tuple[dict[str, Any] | None, list[dict]]:
    """Arbitro per i falli del motore a eventi: partite e medie grezze (football-data) con la media della stessa competizione;
    lo shrinkage k è quello stimato (``referee_stats``) e lo applica ``event_engine.RefereeInput.factors``."""
    if not extra or not extra.get("partite"):
        return None, [{"dato": "arbitro", "lato": "—", "valore": (extra or {}).get("nome") or "non indicato",
                       "effetto": "nessuno sui falli (gialli: già nella media attuale)",
                       "fonte": "arbitro senza storico (football-data.co.uk ha gli arbitri solo per Premier e Scozia)"}]
    data = {"matches": int(extra["partite"]), "fouls": extra.get("falli_medi"), "yellows": extra.get("gialli_medi"),
            "league_fouls": extra.get("media_falli_competizione"), "league_yellows": extra.get("media_gialli_competizione"),
            "name": extra.get("nome") or ""}
    return data, [{"dato": "arbitro", "lato": "—", "valore": f"{data['name']}: {data['matches']} partite, "
                   f"{(data['fouls'] or 0):.1f} falli e {(data['yellows'] or 0):.2f} gialli di media",
                   "effetto": "falli e gialli per fallo del motore a eventi (shrinkage k stimato); gialli riportati alla media attuale",
                   "fonte": "football-data.co.uk; k da referee_stats (config/motore_eventi.json → arbitri)"}]


# ------------------------------------------------------------------------------------------------ insieme


def build(*, lineup: Mapping[str, Any] | None = None, styles: Mapping[str, Any] | None = None,
          imported: Mapping[str, Any] | None = None, sheets: Mapping[str, Any] | None = None,
          modules: Mapping[str, str | None] | None = None, referee_extra: Mapping[str, Any] | None = None,
          cuts: Mapping[str, tuple[float, float]] | None = None,
          wides: Mapping[str, Mapping[str, float]] | None = None) -> dict[str, Any]:
    """Tutti gli ingressi per ``MatchConfig.event_inputs``; ogni argomento è facoltativo (dato assente = neutro dichiarato)."""
    styles, imported, sheets, modules = styles or {}, imported or {}, sheets or {}, modules or {}
    out: dict[str, Any] = {"home": {}, "away": {}, "schede": []}
    scales, goals, rows = lineup_scales(lineup)
    out["formazione"] = goals
    out["schede"] += rows
    lanes, rows = lane_scales(modules.get("home"), modules.get("away"), wides=wides)
    out["schede"] += rows
    for side, label in SIDES:
        terms, rows = style_terms(styles.get(side), imported.get(side), sheets.get(side), cuts)
        out["schede"] += [{**row, "lato": label, "effetto": "termine del dizionario tattico (beta stimati)"} for row in rows]
        entry = {"profile": terms, "module": modules.get(side), **scales.get(side, {})}
        entry.update(lanes.get(side, {}))
        out[side] = entry
    out["arbitro"], rows = referee(referee_extra)
    out["schede"] += rows
    return out
