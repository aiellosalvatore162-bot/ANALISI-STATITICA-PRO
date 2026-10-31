"""Fase AM: taratura per mercato (previsto contro uscito) letta da ``config/taratura.json``.

Una sola mappa per mercato (generata da ``python -m tools.taratura_check --salva``); sostituisce la ricalibrazione
della fase P dello stesso mercato, mai una sopra l'altra. Qui c'è solo l'applicazione, le etichette e le tabelle
da mostrare: nessun calcolo del modello.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import numpy as np

PATH = Path(__file__).resolve().parent / "config" / "taratura.json"

# Terne che sommano 100 dopo la taratura.
TRIOS = (("1", "X", "2"), ("1 1T", "X 1T", "2 1T"), ("1 secondo tempo", "X secondo tempo", "2 secondo tempo"))
# Mercati identici ad altri o loro somme/complementi: non hanno una mappa propria, restano coerenti con la base.
DERIVED: dict[str, tuple[str, tuple[str, ...]]] = {
    "1X": ("somma", ("1", "X")), "X2": ("somma", ("X", "2")), "12": ("somma", ("1", "2")),
    "1X 1T": ("somma", ("1 1T", "X 1T")), "X2 1T": ("somma", ("X 1T", "2 1T")), "12 1T": ("somma", ("1 1T", "2 1T")),
    "1X secondo tempo": ("somma", ("1 secondo tempo", "X secondo tempo")),
    "X2 secondo tempo": ("somma", ("X secondo tempo", "2 secondo tempo")),
    "12 secondo tempo": ("somma", ("1 secondo tempo", "2 secondo tempo")),
    "Esatti 1-0/0-1/0-0": ("complemento", ("Over 1.5 gol",)),
    "Totale 5+ gol": ("uguale", ("Over 4.5 gol",)),
    "X + Over 3.5": ("uguale", ("X + Over 2.5",)),
}
_COMBO = re.compile(r"^(1|X|2|Goal) \+ Over (\d\.5)$")
NO_TARATURA = "non tarato"


def _complement_key(key: str) -> str | None:
    match = re.match(r"^((?:Casa |Ospite )?)(Over|Under) (.+)$", key)
    if not match:
        return None
    return f"{match.group(1)}{'Under' if match.group(2) == 'Over' else 'Over'} {match.group(3)}"


def _recalibrate(pct: float, mapping: Mapping[str, Any]) -> float:
    p = min(max(pct / 100.0, 1e-6), 1 - 1e-6)
    if mapping.get("metodo") == "platt":
        q = 1.0 / (1.0 + math.exp(-(mapping["a"] + mapping["b"] * math.log(p / (1 - p)))))
    else:
        q = float(np.interp(p, mapping["x"], mapping["y"]))
    return 100.0 * q


@dataclass(frozen=True)
class Taratura:
    attiva: bool = False
    parametri: Mapping[str, Any] = field(default_factory=dict)
    mercati: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    data: str = ""

    def excluding(self, predicate) -> "Taratura":
        """Stessa taratura senza i mercati per cui ``predicate(chiave)`` è vero (es. quelli prodotti da un altro motore)."""
        kept = {key: item for key, item in self.mercati.items() if not predicate(key)}
        return Taratura(self.attiva, self.parametri, kept, self.data)

    def has_map(self, key: str) -> bool:
        return bool(self.attiva and self.mercati.get(key, {}).get("mappa"))

    def status(self, key: str) -> str:
        """«tarato (metodo, n=…)» o «non tarato» per la scheda del mercato."""
        item = self.mercati.get(key)
        if key in DERIVED and self.attiva:
            base = DERIVED[key][1][0]
            return f"derivato da {base}" if self.has_map(base) else NO_TARATURA
        if not self.attiva or not item or not item.get("mappa"):
            return NO_TARATURA
        return f"tarato ({item.get('metodo', '?')}, n={item.get('casi', 0)})"

    def table(self, key: str) -> list[dict]:
        """Righe «dichiarato contro uscito» per fascia (con etichetta); vuota se il mercato non è misurato."""
        source = DERIVED[key][1][0] if key in DERIVED and key in self.mercati and not self.mercati[key].get("fasce") else key
        item = self.mercati.get(source) or {}
        return [dict(row) for row in item.get("fasce", []) if row.get("n")]

    def label(self, key: str, pct: float | None) -> str | None:
        """Etichetta («verificata», «poco verificata», «non affidabile») della fascia in cui cade la percentuale."""
        if pct is None:
            return None
        rows = self.table(key)
        if not rows:
            return "poco verificata"
        bands = {"sotto 50": (0, 50), "50-55": (50, 55), "55-60": (55, 60), "60-70": (60, 70), "70-80": (70, 80),
                 "oltre 80": (80, 101)}
        for row in rows:
            low, high = bands.get(row["fascia"], (None, None))
            if low is not None and low <= pct < high:
                return row.get("etichetta") or "poco verificata"
        return "poco verificata"

    def apply(self, percentages: Mapping[str, float]) -> tuple[dict[str, float], list[str], list[str]]:
        """(percentuali tarate, mercati cambiati, avvisi). Coerenza: terne a 100, Over/Under complementari, combo ≤ componenti."""
        out = {key: float(value) for key, value in percentages.items()}
        if not self.attiva:
            return out, [], []
        limit = float(self.parametri.get("limite_correzione_pp", 15.0))
        changed, warnings = [], []
        for key, item in self.mercati.items():
            mapping = item.get("mappa")
            if not mapping or key not in out or key in DERIVED:
                continue
            raw = out[key]
            value = _recalibrate(raw, mapping)
            if abs(value - raw) > limit:
                value = raw + math.copysign(limit, value - raw)
                warnings.append(f"{key}: correzione di taratura limitata a ±{limit:g} punti")
            out[key] = round(value, 2)
            changed.append(key)
        for trio in TRIOS:
            if all(key in changed for key in trio):
                total = sum(out[key] for key in trio)
                for key in trio:
                    out[key] = round(100.0 * out[key] / total, 2)
        for key, (kind, parts) in DERIVED.items():
            if key not in out or parts[0] not in changed or not all(part in out for part in parts):
                continue
            out[key] = round({"somma": sum(out[part] for part in parts), "complemento": 100.0 - out[parts[0]],
                              "uguale": out[parts[0]]}[kind], 2)
            changed.append(key)
        for key in list(changed):
            other = _complement_key(key)
            if other and other in out and key not in DERIVED:
                out[other] = round(100.0 - out[key], 2)
        for key in out:
            combo = _COMBO.match(key)
            if combo and key in changed:
                first, line = combo.groups()
                parts = [out.get(first), out.get(f"Over {line} gol")]
                bound = min(value for value in parts if value is not None) if any(v is not None for v in parts) else None
                if bound is not None and out[key] > bound:
                    out[key] = bound
        changed = [key for key in out if abs(out[key] - float(percentages[key])) > 1e-9]
        return out, changed, warnings


def load(path: Path = PATH) -> Taratura:
    if not path.exists():
        return Taratura()
    data = json.loads(path.read_text(encoding="utf-8"))
    return Taratura(attiva=bool(data.get("attiva")), parametri=data.get("parametri", {}), mercati=data.get("mercati", {}),
                    data=str(data.get("data", "")))
