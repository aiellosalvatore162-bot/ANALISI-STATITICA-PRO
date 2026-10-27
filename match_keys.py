"""Chiavi del match (fase X): 3-4 duelli chiave con il mercato collegato, dal blocco «CHIAVI_MATCH:».

Formato (report dell'Analista o risposta di Claude):

    CHIAVI_MATCH:
    duello: <A> vs <B> | effetto: <testo breve> | mercato: cartellini/corner/gol | fonte: https://...

Parser tollerante come quello della fase G (maiuscole, spazi, markdown); al massimo 4 righe; una riga
senza fonte o senza mercato riconosciuto è scartata. Le chiavi sono solo informative: non cambiano le
probabilità.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


HEADER = "CHIAVI_MATCH:"
MAX_KEYS = 4
MARKETS = ("cartellini", "corner", "gol")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_VERSUS = re.compile(r"\s+(?:vs\.?|v\.?|contro|-)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class MatchKey:
    first: str
    second: str
    effect: str
    markets: tuple[str, ...]
    source: str

    @property
    def duel(self) -> str:
        return f"{self.first} vs {self.second}"

    def swapped(self) -> "MatchKey":
        return MatchKey(self.second, self.first, self.effect, self.markets, self.source)


def keys_section(text: str) -> str:
    """Il blocco «CHIAVI_MATCH:» fino alla prima riga vuota dopo le righe dei duelli ("" se assente)."""
    position = text.upper().find(HEADER)
    if position < 0:
        return ""
    lines, seen = [text[position:].splitlines()[0]], False
    for line in text[position:].splitlines()[1:]:
        if not line.strip():
            if seen:
                break
            continue
        if not line.strip().strip("`*-").strip().lower().startswith("duello"):
            break
        lines.append(line)
        seen = True
    return "\n".join(lines).strip()


def parse_keys(text: str) -> tuple[list[MatchKey], list[str]]:
    """Duelli validi (al massimo 4) e righe scartate con il motivo."""
    section = keys_section(text)
    keys, discarded = [], []
    for raw in section.splitlines()[1:]:
        line = raw.strip().strip("`*-").strip()
        parts = [part.strip() for part in line.split("|")]
        attributes = {}
        for part in parts:
            name, _, value = part.partition(":")
            attributes[name.strip().lower()] = value.strip()
        duel = _VERSUS.split(attributes.get("duello", ""), maxsplit=1)
        markets = tuple(market for market in MARKETS if market in attributes.get("mercato", "").lower())
        source = _URL.search(attributes.get("fonte", ""))
        if len(duel) != 2 or not all(side.strip() for side in duel):
            discarded.append(f"«{line}»: duello non leggibile (atteso «A vs B»)")
        elif not markets:
            discarded.append(f"«{line}»: mercato mancante (cartellini, corner o gol)")
        elif source is None:
            discarded.append(f"«{line}»: senza fonte, scartata")
        elif len(keys) >= MAX_KEYS:
            discarded.append(f"«{line}»: oltre le {MAX_KEYS} chiavi, scartata")
        else:
            keys.append(MatchKey(duel[0].strip(), duel[1].strip(), attributes.get("effetto", ""), markets,
                                 source.group(0).rstrip(").,;")))
    return keys, discarded


def swap_text(text: str) -> str:
    """Testo con casa e ospite scambiati: gol_casa ↔ gol_ospite e lati dei duelli (squadre invertite nel report)."""
    swapped = re.sub(r"\bgol_casa\b", "\0", text, flags=re.IGNORECASE)
    swapped = re.sub(r"\bgol_ospite\b", "gol_casa", swapped, flags=re.IGNORECASE).replace("\0", "gol_ospite")

    def duel(match: re.Match) -> str:
        sides = _VERSUS.split(match.group(2), maxsplit=1)
        return f"{match.group(1)}{sides[1].strip()} vs {sides[0].strip()}" if len(sides) == 2 else match.group(0)

    return re.sub(r"(duello\s*:\s*)([^|\n]+?)(?=\s*\||\s*$)", duel, swapped, flags=re.IGNORECASE | re.MULTILINE)
