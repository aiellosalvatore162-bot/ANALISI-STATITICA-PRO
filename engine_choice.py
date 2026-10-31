"""Fase AN, parte A: scelta del motore («Calcolo attuale» / «Simulatore reale – completo» / «Simulatore reale – solo corner»).

Solo configurazione e testi: il calcolo resta in ``engine.py`` (``MatchConfig.event_engine``). Nessuna posizione è nascosta o
disattivata; gli avvisi informano su quanto ogni motore è verificato (numeri da ``docs/backtest/AK_motore_eventi_nuovo.md``,
``docs/backtest/AN_libero.md`` e dalla taratura della fase AM).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import taratura

SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "impostazioni.json"

CURRENT, FULL, CORNER, UNIQUE = "attuale", "completo", "corner", "unico"
NAMES = {CURRENT: "Calcolo attuale", FULL: "Simulatore reale – completo", CORNER: "Simulatore reale – solo corner",
         UNIQUE: "Simulatore unico"}
HELP = {
    CURRENT: "Il calcolo verificato: punteggi Dixon-Coles ancorati alle quote, corner e cartellini dalle medie.",
    FULL: "Gioca tutta la partita: i gol nascono dai tiri, stile e formazione agiscono sulla partita intera. "
          "Più lento (alcuni secondi) e non verificato sullo storico come il calcolo attuale.",
    CORNER: "Motore a eventi solo per i corner; gol, tempi e cartellini come nel calcolo attuale. Candidato: verificato "
            "su un campione, non ancora su un terzo.",
    UNIQUE: "Ogni mercato usa la sorgente migliore secondo le verifiche (calcolo tarato dalla AM oppure motore a eventi), "
            "con la sua etichetta di affidabilità. Non cerca di battere le quote: le percentuali devono essere vere.",
}
GROUPS = ("Gol, 1X2, multigol, GG/NG", "Primo e secondo tempo", "Corner", "Cartellini", "Combo")

# Avvisi per mercato e motore (testo breve e onesto). I numeri vengono dai documenti citati sopra.
_AO = "563 partite 2025-27 con tutti i dati (docs/backtest/AO_verifica.md)"
_AK = "campione nuovo di 2.672 partite (docs/backtest/AK_motore_eventi_nuovo.md)"
WARNINGS: dict[str, dict[str, str]] = {
    CURRENT: {
        GROUPS[0]: "Verificato e tarato (fase AM): scarto medio previsto/uscito intorno all'1%.",
        GROUPS[1]: "Verificato e tarato dove la taratura migliora (vedi etichette).",
        GROUPS[2]: "Verificato; senza quote corner l'ancoraggio è solo sulle medie.",
        GROUPS[3]: "Verificato e in parte tarato; cartellini per squadra meno precisi.",
        GROUPS[4]: "Verificato; molte combo hanno poche partite per fascia: etichetta «poco verificata».",
    },
    FULL: {
        GROUPS[0]: f"Con tutti i dati (formazione, corsie, stile) su {_AO}: log-loss +0,0010 ± 0,0028, ECE 0,017 → 0,019: "
                   "nessuna differenza misurabile dal calcolo attuale. Nessuna taratura della fase AM.",
        GROUPS[1]: f"Tempi su {_AO}: +0,0006 ± 0,0011 (pari), ECE 0,023 → 0,026. Nessuna taratura per questo motore.",
        GROUPS[2]: f"Corner su {_AO}: −0,0010 ± 0,0011 (leggermente meglio, non significativo); sul {_AK}: −0,00075 ± 0,00039. "
                   "Nessuna taratura per questo motore.",
        GROUPS[3]: f"Cartellini su {_AO}: +0,0015 ± 0,0029 (pari), ECE 0,023 → 0,027; sul {_AK} erano PEGGIO "
                   "(+0,0042 ± 0,0014). Usali con cautela.",
        GROUPS[4]: f"Combo su {_AO}: −0,0008 ± 0,0012 (pari), ECE 0,028 → 0,024.",
    },
    CORNER: {
        GROUPS[0]: "Come il calcolo attuale (verificato e tarato).",
        GROUPS[1]: "Come il calcolo attuale.",
        GROUPS[2]: f"Corner: meglio del calcolo attuale su {_AK}: −0,00075 ± 0,00039. Candidato, non riverificato su un "
                   "terzo campione. Nessuna taratura per questo motore.",
        GROUPS[3]: "Come il calcolo attuale (verificato e tarato).",
        GROUPS[4]: "Combo con i corner: leggermente meglio (−0,00053 ± 0,00045, ECE 0,0185 → 0,0166), non significativo.",
    },
}
UNCALIBRATED = "poco verificata (nessuna taratura per questo motore)"
UNIQUE_PATH = Path(__file__).resolve().parent / "config" / "simulatore_unico.json"
UNIQUE_EVENT_LABEL = "verificata a eventi (non tarata)"
FAMILY_GROUP = {"tempi": "tempi", "corner": "corner", "cartellini": "cartellini"}
CROSSING_GROUP = {"possesso_contro_pressing": "cartellini", "cross_contro_blocco_basso": "corner"}


def load_unified(path: Path = UNIQUE_PATH) -> dict:
    """Scelta della sorgente per famiglia (``tools.ap_scegli``); senza file tutto resta del calcolo attuale."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"famiglie": {}, "incroci_gruppi_tenuti": []}


def unified_markets(data: dict | None = None) -> tuple[str, ...]:
    data = data if data is not None else load_unified()
    return tuple(group for key, group in FAMILY_GROUP.items() if data.get("famiglie", {}).get(key, {}).get("sorgente") == "eventi")


def groups_of(key: str) -> set[str]:
    """Gruppi del motore a eventi da cui dipende il mercato (una combo dipende da tutti i suoi pezzi)."""
    found = set()
    if "corner" in key:
        found.add("corner")
    if "cartellini" in key:
        found.add("cartellini")
    if any(part in key for part in ("1T", "2T", "tempo")):
        found.add("tempi")
    return found


def unified_table(data: dict | None = None) -> list[dict]:
    """Tabella mercato → sorgente → etichetta del Simulatore unico, con i numeri che la motivano."""
    data = data if data is not None else load_unified()
    rows = []
    for item in data.get("famiglie", {}).values():
        events = item.get("sorgente") == "eventi"
        united = item.get("unito") or {}
        proof = (f"{united['diff']:+.5f} ± {2 * united['se']:.5f} (2 e.s.), ECE {united['ece_prima']:.4f} → {united['ece_dopo']:.4f}, "
                 f"{united['partite']} partite" if united else "—")
        rows.append({"Mercati": item["nome"], "Sorgente": "motore a eventi" if events else "calcolo attuale (tarato AM)",
                     "Etichetta": UNIQUE_EVENT_LABEL if events else "dalla taratura AM: verificata / poco verificata / non affidabile",
                     "Differenza eventi − attuale (log-loss)": proof, "Motivo": item.get("motivo", "")})
    return rows


def preset(choice: str, base):
    """``EventEngineParams`` della scelta (la base porta le altre impostazioni: passo, lotti, tolleranza…)."""
    if choice == FULL:
        return replace(base, active=True, free=True, markets=("tempi", "corner", "cartellini"))
    if choice == CORNER:
        return replace(base, active=True, free=False, markets=("corner",))
    if choice == UNIQUE:
        data = load_unified()
        markets = unified_markets(data)
        crossings = ()
        if markets:
            wanted = [name for name, group in CROSSING_GROUP.items() if group in markets and group in data.get("incroci_gruppi_tenuti", [])]
            crossings = tuple(dict(item) for name, item in (engine_config().get("incroci") or {}).items() if name in wanted)
        return replace(base, active=bool(markets), free=False, markets=markets or base.markets, crossings=crossings, unified=True)
    return replace(base, active=False, free=False)


def engine_config() -> dict:
    import event_engine

    try:
        return json.loads(event_engine.PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def apply(config, choice: str):
    """Configurazione con il motore scelto. La fase O (motore a blocchi) è incompatibile con quello a eventi: si spegne per
    la partita e la scelta lo dichiara (nessun errore)."""
    if choice not in NAMES:
        choice = CURRENT
    event = preset(choice, config.event_engine)
    timeline = config.timeline
    if event.active and getattr(timeline, "active", False):
        timeline = replace(timeline, active=False)
    return replace(config, event_engine=event, timeline=timeline)


def choice_of(settings) -> str:
    if getattr(settings, "unified", False):
        return UNIQUE
    if not settings.active:
        return CURRENT
    return FULL if settings.free else CORNER


def driven_mode(mode: str, key: str, markets: tuple[str, ...] | list[str] | None = None) -> bool:
    """``mode`` = «attuale», «libero» (completo) o «punteggi» (solo corner / unico): il mercato viene dal motore a eventi?"""
    if markets is not None:
        return mode == "libero" or (mode == "punteggi" and bool(groups_of(key) & set(markets)))
    return mode == "libero" or (mode == "punteggi" and "corner" in key)


def driven(settings, key: str) -> bool:
    """Il mercato è prodotto dal motore a eventi (quindi fuori dalla taratura della fase AM)?"""
    if not settings.active:
        return False
    if settings.free:
        return True
    return bool(groups_of(key) & set(settings.markets))


def result_label(result, tar: taratura.Taratura, market: str, pct: float | None) -> str | None:
    """Come ``label`` ma dal risultato di una simulazione (usa il motore registrato in ``result["motore"]``)."""
    if pct is None:
        return None
    motor = result.get("motore") or {}
    if driven_mode(motor.get("modo", "attuale"), market, motor.get("mercati") if motor.get("chiave") == UNIQUE else None):
        return UNIQUE_EVENT_LABEL if motor.get("chiave") == UNIQUE else UNCALIBRATED
    return tar.label(market, pct)


def tag(settings) -> str:
    """Testo fisso per report, scheda e registro: quale motore ha prodotto la previsione."""
    return f"motore: {NAMES[choice_of(settings)]}"


def label(settings, tar: taratura.Taratura, market: str, pct: float | None) -> str | None:
    """Etichetta di affidabilità del motore scelto: se il mercato viene dal motore a eventi la taratura AM non vale."""
    if pct is None:
        return None
    if driven(settings, market):
        return UNIQUE_EVENT_LABEL if getattr(settings, "unified", False) else UNCALIBRATED
    return tar.label(market, pct)


def load_default(path: Path = SETTINGS_PATH) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("motore_predefinito", CURRENT)
    except (OSError, ValueError):
        return CURRENT
    return value if value in NAMES else CURRENT


def save_default(choice: str, path: Path = SETTINGS_PATH) -> None:
    data: dict[str, Any] = {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    data["motore_predefinito"] = choice if choice in NAMES else CURRENT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
