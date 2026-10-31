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

CURRENT, FULL, CORNER = "attuale", "completo", "corner"
NAMES = {CURRENT: "Calcolo attuale", FULL: "Simulatore reale – completo", CORNER: "Simulatore reale – solo corner"}
HELP = {
    CURRENT: "Il calcolo verificato: punteggi Dixon-Coles ancorati alle quote, corner e cartellini dalle medie.",
    FULL: "Gioca tutta la partita: i gol nascono dai tiri, stile e formazione agiscono sulla partita intera. "
          "Più lento (alcuni secondi) e non verificato sullo storico come il calcolo attuale.",
    CORNER: "Motore a eventi solo per i corner; gol, tempi e cartellini come nel calcolo attuale. Candidato: verificato "
            "su un campione, non ancora su un terzo.",
}
GROUPS = ("Gol, 1X2, multigol, GG/NG", "Primo e secondo tempo", "Corner", "Cartellini", "Combo")

# Avvisi per mercato e motore (testo breve e onesto). I numeri vengono dai documenti citati sopra.
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
        GROUPS[0]: "Prova rapida su 72 partite (docs/backtest/AN_libero.md): nessuna differenza misurabile dal calcolo attuale "
                   "(1X2 log-loss +0,0015 ± 0,029; Over 2.5 +0,0008 ± 0,0057; Over 1.5 −0,0078 ± 0,0044). Campione troppo "
                   "piccolo per dirlo verificato. Nessuna taratura della fase AM.",
        GROUPS[1]: "Tempi del motore a eventi: pari al calcolo attuale su 2.672 partite (differenza non significativa). "
                   "Nessuna taratura per questo motore.",
        GROUPS[2]: f"Corner: meglio del calcolo attuale su {_AK}: log-loss −0,00075 ± 0,00039, ECE 0,0168 → 0,0151. "
                   "Nessuna taratura per questo motore.",
        GROUPS[3]: f"Cartellini: PEGGIO del calcolo attuale su {_AK}: log-loss +0,0042 ± 0,0014, ECE 0,0201 → 0,0319. "
                   "Usali con cautela.",
        GROUPS[4]: "Combo: nel motore completo pari al calcolo attuale su 2.672 partite; con i gol dai tiri non verificate.",
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


def preset(choice: str, base):
    """``EventEngineParams`` della scelta (la base porta le altre impostazioni: passo, lotti, tolleranza…)."""
    if choice == FULL:
        return replace(base, active=True, free=True, markets=("tempi", "corner", "cartellini"))
    if choice == CORNER:
        return replace(base, active=True, free=False, markets=("corner",))
    return replace(base, active=False, free=False)


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
    if not settings.active:
        return CURRENT
    return FULL if settings.free else CORNER


def driven_mode(mode: str, key: str) -> bool:
    """``mode`` = «attuale», «libero» (completo) o «punteggi» (solo corner): il mercato viene dal motore a eventi?"""
    return mode == "libero" or (mode == "punteggi" and "corner" in key)


def driven(settings, key: str) -> bool:
    """Il mercato è prodotto dal motore a eventi (quindi fuori dalla taratura della fase AM)?"""
    if not settings.active:
        return False
    if settings.free:
        return True
    return "corner" in settings.markets and "corner" in key


def result_label(result, tar: taratura.Taratura, market: str, pct: float | None) -> str | None:
    """Come ``label`` ma dal risultato di una simulazione (usa il motore registrato in ``result["motore"]``)."""
    if pct is None:
        return None
    if driven_mode((result.get("motore") or {}).get("modo", "attuale"), market):
        return UNCALIBRATED
    return tar.label(market, pct)


def tag(settings) -> str:
    """Testo fisso per report, scheda e registro: quale motore ha prodotto la previsione."""
    return f"motore: {NAMES[choice_of(settings)]}"


def label(settings, tar: taratura.Taratura, market: str, pct: float | None) -> str | None:
    """Etichetta di affidabilità del motore scelto: se il mercato viene dal motore a eventi la taratura AM non vale."""
    if pct is None:
        return None
    if driven(settings, market):
        return UNCALIBRATED
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
