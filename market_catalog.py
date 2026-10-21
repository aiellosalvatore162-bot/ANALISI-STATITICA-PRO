"""Single source of truth for supported football markets.

The catalog is deliberately independent from Streamlit and NumPy so the
parser, settlement layer, engine and UI can share stable market identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class MarketDefinition:
    key: str
    label: str
    group: str
    event_key: str
    settlement: str = "binary"
    combo_legs: tuple[str, ...] = ()


_definitions: list[MarketDefinition] = []
MULTIGOL_RANGES: tuple[tuple[int, int], ...] = (
    (1, 2), (1, 3), (1, 4), (1, 5),
    (2, 3), (2, 4), (2, 5), (2, 6),
    (3, 4), (3, 5), (3, 6),
)


def _add(key: str, label: str, group: str, event_key: str | None = None, settlement: str = "binary", combo_legs: tuple[str, ...] = ()) -> None:
    _definitions.append(MarketDefinition(key, label, group, event_key or key, settlement, combo_legs))


for key, label in (("1", "Vittoria Casa"), ("X", "Pareggio"), ("2", "Vittoria Ospite")):
    _add(key, label, "1x2")
for key, label in (("1X", "Casa o Pareggio"), ("X2", "Pareggio o Ospite"), ("12", "Esito diverso dal pareggio")):
    _add(key, label, "double_chance")
for key in ("1", "X", "2"):
    _add(f"{key}_1t", f"{label if False else key} 1° tempo", "first_half_1x2", f"{key} 1T")
for key in ("1X", "X2", "12"):
    _add(f"{key}_1t", f"{key} 1° tempo", "first_half_double_chance", f"{key} 1T")
for key in ("1", "X", "2"):
    _add(f"{key}_2t", f"{key} 2° tempo", "second_half_1x2", f"{key} 2T")
for key in ("1X", "X2", "12"):
    _add(f"{key}_2t", f"{key} 2° tempo", "second_half_double_chance", f"{key} 2T")
_add("dnb_home", "Casa DNB", "draw_no_bet", "Casa DNB", "push")
_add("dnb_away", "Ospite DNB", "draw_no_bet", "Ospite DNB", "push")

for prefix, group, thresholds in (
    ("", "over_under", (0.5, 1.5, 2.5, 3.5, 4.5)),
    ("1T ", "first_half_over_under", (0.5, 1.5)),
):
    for threshold in thresholds:
        for side in ("Over", "Under"):
            event = f"{side} {threshold:g} gol{f' {prefix}' if prefix else ''}".strip()
            _add(f"{side.lower()}_{threshold:g}_{'1t' if prefix else 'full'}", event, group, event)
for team in ("Casa", "Ospite"):
    for threshold in (0.5, 1.5, 2.5):
        for side in ("Over", "Under"):
            event = f"{team} {side} {threshold:g} gol"
            _add(f"{team.lower()}_{side.lower()}_{threshold:g}_goals", event, "team_goals", event)
_add("goal", "Goal", "goal_no_goal", "Goal")
_add("no_goal", "No Goal", "goal_no_goal", "No Goal")
_add("goal_1t", "Goal 1° tempo", "first_half_goal_no_goal", "Goal 1T")
_add("no_goal_1t", "No Goal 1° tempo", "first_half_goal_no_goal", "No Goal 1T")
for low, high in MULTIGOL_RANGES:
    event = f"Multigol {low}-{high}"
    _add(f"multigol_{low}_{high}", event, "multigol_complete", event)
for team in ("Casa", "Ospite"):
    for low, high in MULTIGOL_RANGES:
        event = f"Multigol {team} {low}-{high}"
        _add(f"multigol_{team.lower()}_{low}_{high}", event, "team_multigol", event)
for value in ("0", "1", "2", "3", "4", "5+"):
    event = f"Somma gol {value}"
    _add(f"goal_sum_{value.replace('+', 'plus')}", event, "goal_sums", event)
for event in ("Casa segna", "Casa non segna", "Ospite segna", "Ospite non segna"):
    _add(event.lower().replace(" ", "_"), event, "team_scoring", event)
for event in ("BTTS entrambi i tempi", "BTTS almeno un tempo"):
    _add(event.lower().replace(" ", "_"), event, "both_teams", event)

for threshold in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5):
    for side in ("Over", "Under"):
        event = f"{side} {threshold:g} corner"
        _add(f"{side.lower()}_{threshold:g}_corners", event, "corners", event)
for team in ("Casa", "Ospite"):
    for threshold in (2.5, 3.5, 4.5, 5.5, 6.5):
        for side in ("Over", "Under"):
            event = f"{team} {side} {threshold:g} corner"
            _add(event.lower().replace(" ", "_"), event, "team_corners", event)
for key, label in (("1", "Più corner Casa"), ("X", "Parità corner"), ("2", "Più corner Ospite")):
    _add(f"corner_{key}", label, "corner_1x2", f"{key} corner")
for threshold in (2.5, 3.5, 4.5, 5.5, 6.5):
    for side in ("Over", "Under"):
        event = f"{side} {threshold:g} cartellini"
        _add(f"{side.lower()}_{threshold:g}_cards", event, "cards", event)
for team in ("Casa", "Ospite"):
    for threshold in (1.5, 2.5, 3.5, 4.5):
        for side in ("Over", "Under"):
            event = f"{team} {side} {threshold:g} cartellini"
            _add(event.lower().replace(" ", "_"), event, "team_cards", event)
for key, label in (("1", "Più cartellini Casa"), ("X", "Parità cartellini"), ("2", "Più cartellini Ospite")):
    _add(f"cards_{key}", label, "card_1x2", f"{key} cartellini")

_COMBOS = (
    ("1 + Over 1.5", ("1", "Over 1.5 gol")),
    ("1 + Over 2.5", ("1", "Over 2.5 gol")),
    ("1 + Over 3.5", ("1", "Over 3.5 gol")),
    ("X2 + Under 2.5", ("X2", "Under 2.5 gol")),
    ("X2 + Under 3.5", ("X2", "Under 3.5 gol")),
    ("1X + Goal", ("1X", "Goal")),
    ("1X + No Goal", ("1X", "No Goal")),
    ("2 + Goal", ("2", "Goal")),
    ("2 + No Goal", ("2", "No Goal")),
)
for label, legs in _COMBOS:
    _add(label.lower().replace(" ", "_"), label, "combos", label, "binary", legs)
for low, high in MULTIGOL_RANGES:
    for result in ("1", "2"):
        label = f"{result} + Multigol {low}-{high}"
        _add(label.lower().replace(" ", "_"), label, "combos", label, "binary", (result, f"Multigol {low}-{high}"))

MARKET_CATALOG: tuple[MarketDefinition, ...] = tuple(_definitions)
MARKETS_BY_KEY = {definition.key: definition for definition in MARKET_CATALOG}
MARKETS_BY_EVENT = {definition.event_key: definition for definition in MARKET_CATALOG}
MARKET_GROUPS = tuple(dict.fromkeys(definition.group for definition in MARKET_CATALOG))


def event_keys() -> set[str]:
    return set(MARKETS_BY_EVENT)


def definitions_for_group(group: str) -> tuple[MarketDefinition, ...]:
    return tuple(definition for definition in MARKET_CATALOG if definition.group == group)


def normalize_market_label(label: str) -> str:
    """Normalize human quote labels to the event-key namespace."""
    normalized = re.sub(r"\s+", " ", label.strip())
    if " + " in normalized:
        return " + ".join(normalize_market_label(leg) for leg in normalized.split(" + "))
    lowered = normalized.lower()
    aliases = {"1": "1", "x": "X", "2": "2", "1x": "1X", "x2": "X2", "12": "12"}
    if lowered in aliases:
        return aliases[lowered]
    normalized = re.sub(r"^over\s+", "Over ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^under\s+", "Under ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b1t\b", "1T", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b2t\b", "2T", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(?:primo tempo|1° tempo)\b", "1T", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\b(?:secondo tempo|2° tempo)\b", "2T", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^(1T|2T)\s+(1X|X2|12|1|X|2)$", r"\2 \1", normalized, flags=re.IGNORECASE)
    if re.fullmatch(r"(?:Casa|Ospite) (?:Over|Under) \d+(?:[.,]\d+)?", normalized, re.IGNORECASE):
        return f"{normalized.replace(',', '.')} gol"
    first_half_total = re.fullmatch(
        r"(Over|Under) (\d+(?:[.,]\d+)?) 1T", normalized, re.IGNORECASE
    )
    if first_half_total:
        side, threshold = first_half_total.groups()
        return f"{side.title()} {threshold.replace(',', '.')} gol 1T"
    if re.fullmatch(r"(?:Over|Under) \d+(?:[.,]\d+)?(?: (?:gol|corner|cartellini))?", normalized, re.IGNORECASE):
        if "corner" in normalized.lower():
            return normalized.replace(",", ".")
        if "cartellini" in normalized.lower():
            return normalized.replace(",", ".")
        return f"{normalized.replace(',', '.')} gol" if "gol" not in normalized.lower() else normalized.replace(",", ".")
    for event_key in event_keys():
        if normalized.casefold() == event_key.casefold():
            return event_key
    return normalized


def definition_for_event(event_key: str) -> MarketDefinition | None:
    return MARKETS_BY_EVENT.get(event_key)


def quote_aliases() -> Iterable[str]:
    return event_keys()
