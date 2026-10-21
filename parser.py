"""Parser for the on-demand match input format.

The parser deliberately keeps user values as floats/strings and reports every
fallback. It never consults a database or invents team data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Optional

from market_catalog import definition_for_event, event_keys, normalize_market_label

@dataclass(frozen=True)
class ParsedTeam:
    name: str
    attack: float
    defense: float
    elo: float
    form: str
    xg_for: float
    xg_against: float
    corners_for: float
    corners_against: float
    cards_for: float


@dataclass(frozen=True)
class ParsedReferee:
    yellow_avg: float
    fouls_avg: float


@dataclass(frozen=True)
class MatchInput:
    home: ParsedTeam
    away: ParsedTeam
    referee: ParsedReferee
    odds: dict[str, float] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)


class MatchInputError(ValueError):
    """Raised when required input cannot be parsed."""


_NUMBER = r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)"
_TEAM_LINE = re.compile(
    rf"^(?P<label>Attacco|Difesa|Elo|Forma|xG\s+Fatti|xG\s+Subiti|"
    rf"Corner\s+pro/sub|Cartellini\s+pro)\s*:\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
_REF_LINE = re.compile(
    rf"^(?P<label>Gialli\s+medi|Falli\s+medi)\s+(?P<value>{_NUMBER})\s*$",
    re.IGNORECASE,
)
_ODDS_LINE = re.compile(
    rf"^(?:Quota\s+)?(?P<label>.+?)(?:\s*:\s*|\s+[-–—]\s+|\s+)(?P<value>{_NUMBER})\s*$",
    re.IGNORECASE,
)
_MATCH_HEADER = re.compile(r"(?P<label>CASA|OSPITE|ARBITRO)\s*:", re.IGNORECASE)
_QUOTE_SECTION = re.compile(
    r"^\s*(?:#+\s*)?(?:QUOTE_MERCATI_PRINCIPALI|"
    r"QUOTE_MULTIGOL_TOTALI_E_SQUADRA|QUOTE_MULTIGOL_TOTALI|"
    r"QUOTE_MULTIGOL_CASA|QUOTE_MULTIGOL_OSPITE|QUOTE_SOMMA_GOL|"
    r"QUOTE_CORNER_E_CARTELLINI|QUOTE_COMBO)\s*:?\s*$",
    re.IGNORECASE,
)
_MULTIGOL_LABEL = re.compile(
    r"^Multigol\s+(?:(?:Totale|Totali)\s+)?"
    r"(?:(Casa|Ospite)\s+)?(\d+)\s*-\s*(\d+)$",
    re.IGNORECASE,
)
_TEAM_MULTIGOL_KEY = re.compile(r"^Multigol (Casa|Ospite) \d+-\d+$")


def _supported_market(market: str) -> bool:
    if definition_for_event(market) is not None or _TEAM_MULTIGOL_KEY.fullmatch(market):
        return True
    if " + " not in market:
        return False
    legs = market.split(" + ")
    return len(legs) == 2 and all(
        definition_for_event(leg) is not None or _TEAM_MULTIGOL_KEY.fullmatch(leg)
        for leg in legs
    )


def _normalize_quote_label(label: str) -> str:
    normalized = re.sub(r"\s+", " ", label.strip().replace("_", " "))
    normalized = re.sub(r"^quota\s+", "", normalized, flags=re.IGNORECASE)
    multigol = _MULTIGOL_LABEL.fullmatch(normalized)
    if multigol:
        team, low, high = multigol.groups()
        prefix = f"{team.title()} " if team else ""
        return f"Multigol {prefix}{low}-{high}"
    normalized = re.sub(r"\bcorner\b", "corner", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bcartellini\b", "cartellini", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bgol\b", "gol", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^DNB\s+(Casa|Ospite)$", r"\1 DNB", normalized, flags=re.IGNORECASE)
    normalized = normalize_market_label(normalized)
    for event_key in event_keys():
        if event_key.casefold() == normalized.casefold():
            return event_key
    return normalized


def _collect_odds(item: str, *, allow_unprefixed: bool = False) -> tuple[str, str] | None:
    normalized_item = item.strip()
    match = _ODDS_LINE.match(normalized_item)
    if not match:
        if normalized_item.lower().startswith("quota "):
            raise MatchInputError(
                f"Quota malformata: {normalized_item!r}; usa 'Quota <mercato>: <valore numerico>'"
            )
        return None
    explicit = normalized_item.lower().startswith("quota ")
    key = _normalize_quote_label(match.group("label"))
    if not explicit and not allow_unprefixed:
        return None
    if not explicit and not _supported_market(key):
        return None
    return key, match.group("value")


def _number(value: str, field_name: str) -> float:
    normalized = value.strip().replace(",", ".")
    try:
        number = float(normalized)
    except ValueError as exc:
        raise MatchInputError(f"{field_name}: valore numerico non valido: {value!r}") from exc
    if not math.isfinite(number):
        raise MatchInputError(f"{field_name}: il valore deve essere finito")
    return number


def _section_lines(text: str) -> tuple[dict[str, str], dict[str, str], dict[str, str], list[tuple[str, str]]]:
    sections: dict[str, dict[str, str]] = {"home": {}, "away": {}, "referee": {}}
    odds: list[tuple[str, str]] = []
    section: Optional[str] = None
    quote_section = False

    def process_content(content: str, current_section: Optional[str], *, allow_unprefixed_odds: bool) -> None:
        if current_section in ("home", "away"):
            parts = [part.strip() for part in content.split("|")]
            for item in parts:
                quote = _collect_odds(item, allow_unprefixed=allow_unprefixed_odds)
                if quote:
                    odds.append(quote)
                    continue
                match = _TEAM_LINE.match(item)
                if match:
                    sections[current_section][match.group("label").lower()] = match.group("value")
        elif current_section == "referee":
            for item in content.split("|"):
                quote = _collect_odds(item, allow_unprefixed=allow_unprefixed_odds)
                if quote:
                    odds.append(quote)
                    continue
                match = _REF_LINE.match(item.strip())
                if match:
                    sections["referee"][match.group("label").lower()] = match.group("value")
        elif allow_unprefixed_odds:
            for item in content.split("|"):
                quote = _collect_odds(item, allow_unprefixed=True)
                if quote:
                    odds.append(quote)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _QUOTE_SECTION.match(line):
            quote_section = True
            section = None
            continue
        if quote_section and not re.match(r"^(?:CASA|OSPITE|ARBITRO)\s*:", line, re.IGNORECASE):
            process_content(line, None, allow_unprefixed_odds=True)
            continue
        headers = list(_MATCH_HEADER.finditer(line))
        if headers and headers[0].start() != 0:
            headers = []
        elif len(headers) > 1:
            valid_headers = headers[:1]
            for header in headers[1:]:
                prefix = line[:header.start()]
                repeated_header = re.fullmatch(
                    r"(?:CASA|OSPITE|ARBITRO)\s*:\s*[^|]+",
                    prefix,
                    re.IGNORECASE,
                )
                if prefix.rstrip().endswith("|") or repeated_header:
                    valid_headers.append(header)
            headers = valid_headers
        if headers:
            quote_section = False
            for index, header in enumerate(headers):
                content_end = headers[index + 1].start() if index + 1 < len(headers) else len(line)
                content = line[header.end():content_end].strip(" |")
                section = {"casa": "home", "ospite": "away", "arbitro": "referee"}[header.group("label").lower()]
                if section in ("home", "away"):
                    name = content.split("|", 1)[0].strip()
                    if name and "name" not in sections[section]:
                        sections[section]["name"] = name
                process_content(content, section, allow_unprefixed_odds=False)
            continue
        process_content(line, section, allow_unprefixed_odds=True)
    return sections["home"], sections["away"], sections["referee"], odds


def _team(
    section: dict[str, str], label: str, warnings: list[str], *, strict: bool
) -> ParsedTeam:
    required = {
        "name": "Nome",
        "attacco": "Attacco",
        "difesa": "Difesa",
        "elo": "Elo",
        "forma": "Forma",
        "xg fatti": "xG Fatti",
        "xg subiti": "xG Subiti",
    }
    missing = [name for key, name in required.items() if not section.get(key)]
    if missing:
        raise MatchInputError(f"{label}: campi obbligatori mancanti: {', '.join(missing)}")

    values = {
        key: _number(section[key], f"{label} {name}")
        for key, name in required.items()
        if key != "name" and key != "forma"
    }
    for key in ("attacco", "difesa"):
        if not 0.2 <= values[key] <= 3.0:
            raise MatchInputError(f"{label} {key.title()}: usare un coefficiente relativo tra 0.2 e 3.0")
    if not 800.0 <= values["elo"] <= 2400.0:
        raise MatchInputError(f"{label} Elo: usare un rating tra 800 e 2400")
    for key in ("xg fatti", "xg subiti"):
        if not 0.0 <= values[key] <= 10.0:
            raise MatchInputError(f"{label} {key}: usare una media per partita tra 0 e 10")
    form = section["forma"].strip().upper().replace(" ", "")
    if not re.fullmatch(r"[WDL](?:-[WDL]){0,4}", form):
        raise MatchInputError(f"{label} Forma: usare token W-D-L, massimo cinque risultati")

    corners = section.get("corner pro/sub")
    if corners:
        parts = re.split(r"\s*/\s*", corners)
        if len(parts) != 2:
            raise MatchInputError(f"{label} Corner pro/sub: usare il formato valore/valore")
        corners_for, corners_against = (
            _number(parts[0], f"{label} Corner pro"),
            _number(parts[1], f"{label} Corner sub"),
        )
        if not 0.0 <= corners_for <= 15.0 or not 0.0 <= corners_against <= 15.0:
            raise MatchInputError(f"{label} Corner pro/sub: usare medie per squadra tra 0 e 15 a partita")
    else:
        if strict:
            raise MatchInputError(f"{label}: campo obbligatorio mancante: Corner pro/sub")
        corners_for = corners_against = 5.0
        warnings.append(f"{label}: Corner pro/sub mancante, fallback indicativo 5.0/5.0 per partita")

    cards = section.get("cartellini pro")
    if cards:
        cards_for = _number(cards, f"{label} Cartellini pro")
        if not 0.0 <= cards_for <= 10.0:
            raise MatchInputError(f"{label} Cartellini pro: usare una media per squadra tra 0 e 10 a partita")
    else:
        if strict:
            raise MatchInputError(f"{label}: campo obbligatorio mancante: Cartellini pro")
        cards_for = 1.0
        warnings.append(f"{label}: Cartellini pro mancante, fallback neutro 1.0")

    return ParsedTeam(
        name=section["name"],
        attack=values["attacco"],
        defense=values["difesa"],
        elo=values["elo"],
        form=form,
        xg_for=values["xg fatti"],
        xg_against=values["xg subiti"],
        corners_for=corners_for,
        corners_against=corners_against,
        cards_for=cards_for,
    )


def parse_match_input(text: str, *, strict: bool = True) -> MatchInput:
    """Parse one complete match block and return explicit fallback warnings."""
    home_section, away_section, referee_section, raw_odds = _section_lines(text)
    warnings: list[str] = []
    home = _team(home_section, "CASA", warnings, strict=strict)
    away = _team(away_section, "OSPITE", warnings, strict=strict)
    expected_corner_mean = (
        home.corners_for + away.corners_against
        + away.corners_for + home.corners_against
    ) / 2.0
    if expected_corner_mean < 4.0:
        warnings.append(
            f"Corner: media totale attesa {expected_corner_mean:.2f} a partita insolitamente bassa; verifica che i valori siano medie, non coefficienti"
        )
    if expected_corner_mean > 20.0:
        raise MatchInputError(
            "Corner: la media totale attesa supera 20 a partita; verifica che siano medie per squadra, non totali o percentuali"
        )

    yellow_raw = referee_section.get("gialli medi")
    fouls_raw = referee_section.get("falli medi")
    if yellow_raw is None:
        if strict:
            raise MatchInputError("ARBITRO: campo obbligatorio mancante: Gialli medi")
        yellow = 4.5
        warnings.append("ARBITRO: Gialli medi mancante, fallback neutro 4.5")
    else:
        yellow = _number(yellow_raw, "ARBITRO Gialli medi")
    if fouls_raw is None:
        if strict:
            raise MatchInputError("ARBITRO: campo obbligatorio mancante: Falli medi")
        fouls = 24.0
        warnings.append("ARBITRO: Falli medi mancante, fallback neutro 24.0")
    else:
        fouls = _number(fouls_raw, "ARBITRO Falli medi")
    if not 0.0 <= yellow <= 15.0 or not 0.0 <= fouls <= 60.0:
        raise MatchInputError("ARBITRO: usare medie per partita tra 0-15 gialli e 0-60 falli")
    expected_card_mean = max(
        0.0,
        (home.cards_for + away.cards_for) * (yellow / 4.5) * (fouls / 24.0),
    )
    if expected_card_mean > 20.0:
        raise MatchInputError(
            "Cartellini: la media totale attesa supera 20 a partita; verifica gialli per squadra e medie arbitrali"
        )

    odds: dict[str, float] = {}
    for market, raw_value in raw_odds:
        if not _supported_market(market):
            if strict:
                raise MatchInputError(f"Quota {market}: mercato non riconosciuto o non supportato")
            warnings.append(f"Quota {market}: mercato non supportato, quota scartata")
            continue
        value = _number(raw_value, f"Quota {market}")
        if value <= 1.0:
            if strict:
                raise MatchInputError(f"Quota {market}: deve essere maggiore di 1.0")
            warnings.append(f"Quota {market}: deve essere maggiore di 1.0, quota scartata")
            continue
        if market in odds:
            if strict:
                raise MatchInputError(f"Quota {market}: duplicata; ogni mercato deve avere una sola quota")
            warnings.append(f"Quota {market}: duplicata, mantenuta la prima quota")
            continue
        odds[market] = value

    return MatchInput(
        home=home,
        away=away,
        referee=ParsedReferee(yellow_avg=yellow, fouls_avg=fouls),
        odds=odds,
        warnings=tuple(warnings),
    )
