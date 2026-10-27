"""Quote Eurobet incollate dal sito: parser a stati guidato dai titoli delle sezioni.

Il testo copiato dalle pagine quote di Eurobet ha una voce per riga: il titolo
della sezione in maiuscolo («U/O GOAL», «MULTIGOL CASA», «U/O CORNER»…), a
volte «Combo Builder», poi parametri (linea «2.5», «1T - 1.5», «SQ.1 - 2.5»,
intervallo «1-2», handicap «2:0»), etichette (UNDER/OVER, SI/NO, 1/X/2…) e
quote. Regole:

- una quota ha sempre due decimali («1.62», «1,62») e vale solo per
  l'etichetta che la precede; un'etichetta senza quota (selezione sospesa)
  resta senza quota, la quota non slitta mai alla selezione successiva;
- un numero con un solo decimale o intero è una linea o un parametro;
- il significato di «1-2» dipende dalla sezione (intervallo multigol,
  risultato esatto, 1T/finale);
- righe incollate insieme («1.11 U/O CARTELLINI») si separano;
- «Combo Builder» subito sotto il titolo marca il mercato come combinabile;
- le sezioni sconosciute si ignorano e si elencano, senza inventare nulla.

Si riempiono solo i campi quota che il simulatore ha già (chiavi evento di
``market_catalog`` e il gruppo dei risultati esatti); il resto è «non
simulato» e non entra in EV, ancoraggio o registro. Fanno eccezione le linee
Over/Under totali di corner e cartellini fuori catalogo (es. corner 5.5 e
6.5): servono solo a ricavare la media implicita per l'ancoraggio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Iterable, Mapping

from market_catalog import event_keys


SOURCE = "Eurobet (incollata)"
EXACT_TARGET = "Risultati esatti · Il mio gruppo"
GOAL_ANCHOR_KEYS = ("1", "X", "2", "Over 2.5 gol", "Under 2.5 gol")

OK, SUSPENDED, NOT_SIMULATED, UNRECOGNIZED, DUPLICATE = "ok", "senza quota", "non simulato", "non riconosciuto", "doppione"

_QUOTE = re.compile(r"^\d+[.,]\d{2}$")
_GLUED = re.compile(r"^(\d+[.,]\d{2})\s+([A-Za-z].*)$")
_IGNORED = {"", "*"}
COMBO_BUILDER = "combo builder"


def _norm(text: str) -> str:
    """Spazi uniformi (anche intorno a «+») e minuscole: base dei confronti."""
    text = re.sub(r"\s*\+\s*(?=\S)", " + ", text)  # «2 +2 + X»; «12+» resta com'è
    return re.sub(r"\s+", " ", text).strip().casefold()


def _number(text: str) -> float:
    return float(text.replace(",", "."))


def _line(text: str) -> str:
    return f"{_number(text):g}"


# --- Grammatiche delle sezioni ------------------------------------------------------------

X12, UO, SINO, GGNG = r"1|x|2", r"under|over", r"si|sì|no", r"gg|ng"
LINE = r"\d+[.,]5"
HALF = r"[12]t"
RANGE = r"\d+-\d+"
BAND = r"(?:meno di|più di|piu' di|piu di)\s*\d+|[<>]\s*\d+|\d+\s*-\s*\d+|\d+\+?"
TEAM = r"sq\.[12]"
Mapper = Callable[[str | None, str], str | None]


@dataclass(frozen=True)
class SectionSpec:
    title: str                  # regex del titolo (su testo normalizzato)
    labels: str                 # regex delle etichette (selezioni)
    params: str | None = None   # regex dei parametri (linee, intervalli, tempi)
    mapper: Mapper | None = None
    margin: str | None = None   # «gruppi»: esiti dello stesso parametro; «famiglie»: anche per tipo (1X2, U/O, GG/NG)
    anchor: str | None = None   # «corner» o «cartellini»: scala usata per l'ancoraggio


def _side(label: str) -> str:
    return "Over" if label.startswith("over") else "Under"


def _total(suffix: str, half: str | None = None) -> Mapper:
    def mapper(param: str | None, label: str) -> str | None:
        if param is None:
            return None
        if half:
            match = re.fullmatch(rf"{half} - ({LINE})", param)
            return f"{_side(label)} {_line(match[1])} {suffix}" if match else None
        return f"{_side(label)} {_line(param)} {suffix}" if re.fullmatch(LINE, param) else None
    return mapper


def _team_total(suffix: str) -> Mapper:
    def mapper(param: str | None, label: str) -> str | None:
        match = re.fullmatch(rf"sq\.([12]) - ({LINE})", param or "")
        if not match:
            return None
        return f"{'Casa' if match[1] == '1' else 'Ospite'} {_side(label)} {_line(match[2])} {suffix}"
    return mapper


def _sign(label: str) -> str:
    return label.upper()


def _top(half: bool) -> Mapper:
    """«SCOMMESSE TOP» e «SCOMMESSE TOP 1T»: 1X2, Under/Over della linea indicata, GG/NG."""
    suffix = " 1T" if half else ""

    def mapper(param: str | None, label: str) -> str | None:
        if re.fullmatch(X12, label):
            return f"{_sign(label)}{suffix}"
        if re.fullmatch(GGNG, label):
            return ("Goal" if label == "gg" else "No Goal") + suffix
        if half:
            match = re.fullmatch(rf"1t - ({LINE})", param or "")
            return f"{_side(label)} {_line(match[1])} gol 1T" if match else None
        return f"{_side(label)} {_line(param)} gol" if param and re.fullmatch(LINE, param) else None
    return mapper


def _multigol(team: str | None) -> Mapper:
    def mapper(param: str | None, label: str) -> str | None:
        if not param or not re.fullmatch(RANGE, param) or not label.startswith("s"):
            return None  # «No» (fuori dall'intervallo) non ha un campo
        low, high = param.split("-")
        return f"Multigol {team + ' ' if team else ''}{int(low)}-{int(high)}"
    return mapper


def _result_uo(param: str | None, label: str) -> str | None:
    match = re.fullmatch(rf"(1|x|2|1x|x2) \+ ({UO})", label)
    if not match or not param or not re.fullmatch(LINE, param):
        return None
    return f"{_sign(match[1])} + {_side(match[2])} {_line(param)}"


def _result_multigol(param: str | None, label: str) -> str | None:
    match = re.fullmatch(r"(1|2|1x|x2|12|x) \+ multigol", label)
    if not match or not param or not re.fullmatch(RANGE, param):
        return None
    low, high = param.split("-")
    return f"{_sign(match[1])} + Multigol {int(low)}-{int(high)}"


def _simple(mapping: Mapping[str, str]) -> Mapper:
    return lambda param, label: mapping.get(label)


def _exact(param: str | None, label: str) -> str | None:
    match = re.fullmatch(r"(\d+)-(\d+)", label)
    return f"{int(match[1])}-{int(match[2])}" if match else None


def _exact_group(param: str | None, label: str) -> str | None:
    if not re.fullmatch(r"\d+-\d+(?:/\d+-\d+)+", label):
        return None  # «SQ.1 ALTRO», «X»: insiemi non elencati, nessun campo
    from exact_scores import group_selection

    return group_selection(label.split("/"))


def _half_multigol(half: str) -> Mapper:
    """«MULTIGOL 1T/2T»: intervallo «1-2» o «4-99» (= 4+) → «Multigol 1T 1-2», solo per «Sì»."""
    from market_catalog import range_label

    def mapper(param: str | None, label: str) -> str | None:
        if not param or not re.fullmatch(RANGE, param) or not label.startswith("s"):
            return None
        low, high = (int(value) for value in param.split("-"))
        return f"Multigol {half} {range_label(low, high)}"
    return mapper


def _pair_multigol(param: str | None, label: str) -> str | None:
    found = re.fullmatch(rf"({RANGE}) \+ ({RANGE})", param or "")
    if not found or not label.startswith("s"):
        return None
    home, away = found.group(1), found.group(2)
    return f"Multigol Casa {home} + Ospite {away}"


def _goal_uo(param: str | None, label: str) -> str | None:
    found = re.fullmatch(rf"({GGNG}) \+ ({UO})", label)
    if not found or not param or not re.fullmatch(LINE, param):
        return None
    return f"{'Goal' if found.group(1) == 'gg' else 'No Goal'} + {_side(found.group(2))} {_line(param)}"


def _half_total(suffix: str) -> Mapper:
    """«1T - 3.5» → «Over 3.5 corner 1T» (o cartellini)."""
    def mapper(param: str | None, label: str) -> str | None:
        found = re.fullmatch(rf"([12])t - ({LINE})", param or "")
        return f"{_side(label)} {_line(found.group(2))} {suffix} {found.group(1)}T" if found else None
    return mapper


def _half_sign(suffix: str) -> Mapper:
    def mapper(param: str | None, label: str) -> str | None:
        return f"{_SIGNS[label]} {suffix} 1T" if param == "1t" and label in _SIGNS else None
    return mapper


def _band(prefix: str) -> Mapper:
    """Fasce: «< 6», «6 - 8», «> 14», «0-8», «12+», «Meno Di 4», «4», «>11» → «Corner totali 6-8» ecc."""
    from market_catalog import OPEN, range_label

    def mapper(param: str | None, label: str) -> str | None:
        text = label.replace(" ", "")
        if found := re.fullmatch(r"(?:<|menodi)(\d+)", text):
            low, high = 0, int(found.group(1)) - 1
        elif found := re.fullmatch(r">(\d+)", text):
            low, high = int(found.group(1)) + 1, OPEN
        elif found := re.fullmatch(r"(\d+)\+", text):
            low, high = int(found.group(1)), OPEN
        elif found := re.fullmatch(r"(\d+)-(\d+)", text):
            low, high = int(found.group(1)), int(found.group(2))
        elif found := re.fullmatch(r"(\d+)", text):
            low = high = int(found.group(1))
        else:
            return None
        return f"{prefix} {range_label(low, high)}"
    return mapper


_SIGNS = {"1": "1", "x": "X", "2": "2"}
SECTIONS: tuple[SectionSpec, ...] = (
    # Gol
    SectionSpec(r"scommesse top", rf"{X12}|{UO}|{GGNG}", LINE, _top(False), "famiglie"),
    SectionSpec(r"scommesse top 1t", rf"{X12}|{UO}|{GGNG}", rf"1t(?: - {LINE})?", _top(True), "famiglie"),
    SectionSpec(r"1x2", X12, None, _simple(_SIGNS), "gruppi"),
    SectionSpec(r"1x2 1t|1x2 primo tempo", X12, None, _simple({k: f"{v} 1T" for k, v in _SIGNS.items()}), "gruppi"),
    SectionSpec(r"1x2 2t|1x2 secondo tempo", X12, None, _simple({k: f"{v} 2T" for k, v in _SIGNS.items()}), "gruppi"),
    SectionSpec(r"u/o goal|under/over|u/o gol", UO, LINE, _total("gol"), "gruppi"),
    SectionSpec(r"u/o goal 1t|u/o 1t", UO, rf"(?:1t - )?{LINE}",
                lambda p, l: _total("gol 1T")(re.sub(r"^1t - ", "", p or "") or None, l), "gruppi"),
    SectionSpec(r"gg/ng", GGNG, None, _simple({"gg": "Goal", "ng": "No Goal"}), "gruppi"),
    SectionSpec(r"gg/ng 1t", GGNG, None, _simple({"gg": "Goal 1T", "ng": "No Goal 1T"}), "gruppi"),
    SectionSpec(r"dc|doppia chance", r"1x|x2|12", None, _simple({"1x": "1X", "x2": "X2", "12": "12"})),
    SectionSpec(r"quasi vince", SINO, TEAM),
    SectionSpec(r"1x2 \+ u/o", rf"(?:{X12}) \+ (?:{UO})", LINE, _result_uo, "gruppi"),
    SectionSpec(r"1x \+ u/o", rf"(?:1x|2) \+ (?:{UO})", LINE, _result_uo, "gruppi"),
    SectionSpec(r"x2 \+ u/o", rf"(?:1|x2) \+ (?:{UO})", LINE, _result_uo, "gruppi"),
    SectionSpec(r"gg/ng \+ u/o", rf"(?:{GGNG}) \+ (?:{UO})", LINE, _goal_uo, "gruppi"),
    SectionSpec(r"risultato esatto(?: xl)?", r"\d+-\d+", None, _exact),
    SectionSpec(r"ris\. esatto a gruppi|risultato esatto a gruppi", r"\d+-\d+(?:/\d+-\d+)+|sq\.[12] altro|x", None, _exact_group),
    SectionSpec(r"1t/finale|parziale/finale", r"[12x]-[12x]", None, None, "gruppi"),
    SectionSpec(r"1x2 handicap", X12, r"\d+:\d+", None, "gruppi"),
    # Multigol
    SectionSpec(r"multigol", SINO, RANGE, _multigol(None)),
    SectionSpec(r"multigol 1t", SINO, RANGE, _half_multigol("1T")),
    SectionSpec(r"multigol 2t", SINO, RANGE, _half_multigol("2T")),
    SectionSpec(r"multigol casa", SINO, RANGE, _multigol("Casa")),
    SectionSpec(r"multigol ospite", SINO, RANGE, _multigol("Ospite")),
    SectionSpec(r"multigol 1t \+ 2t", SINO, rf"{RANGE} \+ {RANGE}"),
    SectionSpec(r"multigol casa \+ ospite", SINO, rf"{RANGE} \+ {RANGE}", _pair_multigol),
    SectionSpec(r"1x \+ multigol", r"(?:1x|2) \+ (?:multigol|altro)", RANGE, _result_multigol, "gruppi"),
    SectionSpec(r"x2 \+ multigol", r"(?:1|x2) \+ (?:multigol|altro)", RANGE, _result_multigol, "gruppi"),
    SectionSpec(r"12 \+ multigol", r"(?:12|x) \+ (?:multigol|altro)", RANGE, _result_multigol, "gruppi"),
    # Corner
    SectionSpec(r"1x2 corner", X12, None, _simple({k: f"{v} corner" for k, v in _SIGNS.items()}), "gruppi"),
    SectionSpec(r"u/o corner", UO, LINE, _total("corner"), "gruppi", "corner"),
    SectionSpec(r"totale corner|tot\. corner", BAND, None, _band("Corner totali"), "gruppi"),
    SectionSpec(r"totale corner casa", BAND, None, _band("Corner casa"), "gruppi"),
    SectionSpec(r"totale corner ospite", BAND, None, _band("Corner ospite"), "gruppi"),
    SectionSpec(r"tot\. corner 1t|totale corner (?:casa|ospite) 1t", BAND, None, None, "gruppi"),
    SectionSpec(r"t/t hand\.? corner(?: 1t| 2t)?", r"1|2", r"[+-]\s*\d+[.,]5", None, "gruppi"),
    SectionSpec(r"ultimo corner", r"sq\.[12]|nessuno", None, None, "gruppi"),
    SectionSpec(r"(?:primo|ultimo) corner tempo", r"sq\.[12]|nessuno", HALF, None, "gruppi"),
    SectionSpec(r"p/d corner", r"pari|dispari", None, None, "gruppi"),
    SectionSpec(r"p/d corner tempo", r"pari|dispari", HALF, None, "gruppi"),
    SectionSpec(r"1x2 corner tempo", X12, HALF, _half_sign("corner"), "gruppi"),
    SectionSpec(r"u/o corner tempo", UO, rf"{HALF} - {LINE}", _half_total("corner"), "gruppi"),
    SectionSpec(r"u/o corner sq\.", UO, rf"{TEAM} - {LINE}", _team_total("corner"), "gruppi"),
    SectionSpec(r"u/o corner sq\. tempo", UO, rf"{HALF}/{TEAM} - {LINE}", None, "gruppi"),
    SectionSpec(r"corner battuti casa \+ ospite", rf"(?:{UO}) \+ (?:{UO})", rf"casa {LINE} - ospite {LINE}", None, "gruppi"),
    SectionSpec(r"1x2 finale \+ u/o corner", rf"(?:{X12}) \+ (?:{UO})", LINE, None, "gruppi"),
    SectionSpec(r"1x2 finale \+ 1x2 corner", rf"(?:{X12}) \+ (?:{X12})", None, None, "gruppi"),
    SectionSpec(r"1x2 corner 1t/finale", rf"(?:{X12})/(?:{X12})", None, None, "gruppi"),
    SectionSpec(r"almeno x corner sq\. nei tempi", SINO, r"almeno \d+ corner"),
    SectionSpec(r"corner minuto", SINO, r"\d+:\d+ - \d+:\d+"),
    SectionSpec(r"tempo con piu' corner|tempo con più corner", X12, None, None, "gruppi"),
    # Cartellini
    SectionSpec(r"u/o cartellini", UO, LINE, _total("cartellini"), "gruppi", "cartellini"),
    SectionSpec(r"u/o cartellini tempo", UO, rf"{HALF} - {LINE}", _half_total("cartellini"), "gruppi"),
    SectionSpec(r"1x2 cartellini", X12, None, _simple({k: f"{v} cartellini" for k, v in _SIGNS.items()}), "gruppi"),
    SectionSpec(r"1x2 cartellini tempo", X12, HALF, _half_sign("cartellini"), "gruppi"),
    SectionSpec(r"tot\. cartellini", BAND, None, _band("Cartellini totali"), "gruppi"),
    SectionSpec(r"tot\. cartellini casa", BAND, None, _band("Cartellini casa"), "gruppi"),
    SectionSpec(r"tot\. cartellini ospite", BAND, None, _band("Cartellini ospite"), "gruppi"),
    SectionSpec(r"tot\. cartellini 1t (?:casa|ospite)", BAND, None, None, "gruppi"),
    SectionSpec(r"primo cartellino", r"1|2|nessuno", None, None, "gruppi"),
    SectionSpec(r"cartellino minuto", SINO, r"\d+:\d+ - \d+:\d+"),
    SectionSpec(r"u/o cartellini sq\.", UO, rf"{TEAM} - {LINE}", _team_total("cartellini"), "gruppi"),
    SectionSpec(r"entrambe almeno x cartellini", SINO, r"\d+"),
    SectionSpec(r"espulso sq\. tempo", SINO, rf"{HALF} - {TEAM}"),
    SectionSpec(r"1x2 corner \+ 1x2 cartellini", rf"(?:{X12}) \+ (?:{X12})", None, None, "gruppi"),
    SectionSpec(r"1x2 \+ 1x2 corner \+ 1x2 cartellini", rf"(?:{X12}) \+ (?:{X12}) \+ (?:{X12})", None, None, "gruppi"),
    SectionSpec(r"1x2 finale \+ u/o cartellini", rf"(?:{X12}) \+ (?:{UO})", LINE, None, "gruppi"),
    SectionSpec(r"1x2 finale \+ 1x2 cartellini", rf"(?:{X12}) \+ (?:{X12})", None, None, "gruppi"),
    SectionSpec(r"p/d cartellini", r"pari|dispari", None, None, "gruppi"),
)


def _spec_for(line: str) -> SectionSpec | None:
    text = _norm(line)
    return next((spec for spec in SECTIONS if re.fullmatch(spec.title, text)), None)


# --- Risultato ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EurobetQuote:
    section: str                # titolo come incollato
    selection: str              # etichetta come incollata
    line: str | None            # parametro come incollato
    price: float | None         # None = selezione senza quota (sospesa)
    market: str | None          # campo del simulatore (chiave evento, o risultato/gruppo esatto)
    status: str
    combo_builder: bool = False
    anchor: str | None = None   # chiave Over/Under usata solo per l'ancoraggio (corner, cartellini)
    block: int = 0              # occorrenza della sezione: la stessa sezione può arrivare da due pagine


@dataclass
class EurobetPaste:
    quotes: list[EurobetQuote] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)
    unrecognized_lines: list[str] = field(default_factory=list)
    combo_sections: dict[str, bool] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.quotes

    def odds(self) -> dict[str, float]:
        """Quote dei campi del simulatore (chiavi evento del catalogo) con stato «ok»."""
        return {quote.market: quote.price for quote in self.quotes
                if quote.status == OK and quote.market in event_keys() and quote.price is not None}

    def exact(self) -> dict[str, float]:
        """Quote dei risultati esatti e dei gruppi («1-0», «1-0/2-0/3-0»): campo «Il mio gruppo»."""
        return {quote.market: quote.price for quote in self.quotes
                if quote.status == OK and quote.market not in event_keys() and quote.price is not None}

    def count_lines(self, kind: str) -> dict[str, float]:
        """Tutta la scala Over/Under totale di corner o cartellini (anche le linee fuori catalogo)."""
        return {quote.anchor: quote.price for quote in self.quotes
                if quote.anchor and quote.anchor.endswith(f" {kind}") and quote.price is not None
                and quote.status in (OK, NOT_SIMULATED)}

    def combinable(self) -> set[str]:
        """Campi del simulatore dei mercati marcati «Combo Builder»: i soli usabili nelle multiple combinate."""
        return {quote.market for quote in self.quotes if quote.combo_builder and quote.status == OK and quote.market}

    def margins(self) -> dict[str, float]:
        """Margine Eurobet per sezione: media su ogni gruppo completo di esiti di (Σ 1/quota − 1)."""
        result = {}
        for title in dict.fromkeys(quote.section for quote in self.quotes):
            spec = _spec_for(title)
            if spec is None or spec.margin is None:
                continue
            groups: dict[tuple, list[EurobetQuote]] = {}
            for quote in self.quotes:
                if quote.section == title:
                    family = _family(quote.selection) if spec.margin == "famiglie" else ""
                    groups.setdefault((quote.block, quote.line, family), []).append(quote)
            # Solo gruppi completi: con una selezione sospesa il margine non si può calcolare.
            values = [sum(1.0 / quote.price for quote in group) - 1.0 for group in groups.values()
                      if len(group) >= 2 and all(quote.price for quote in group)]
            if values:
                result[title] = sum(values) / len(values)
        return result


def _family(label: str) -> str:
    """Esiti che insieme coprono tutti i casi (stesso parametro): base del margine."""
    text = _norm(label)
    for name, pattern in (("1x2", X12), ("uo", UO), ("ggng", GGNG), ("sino", SINO)):
        if re.fullmatch(pattern, text):
            return name
    return "altro"


def _split(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        glued = _GLUED.match(line)
        if glued:
            lines.extend([glued[1], glued[2].strip()])
        else:
            lines.append(line)
    return lines


def parse_eurobet(text: str) -> EurobetPaste:
    """Una o più pagine Eurobet incollate una dopo l'altra, in qualsiasi ordine."""
    paste = EurobetPaste()
    keys = event_keys()
    seen: dict[str, float | None] = {}
    spec: SectionSpec | None = None
    title: str | None = None          # sezione corrente (nota o sconosciuta)
    param: str | None = None
    pending: str | None = None        # etichetta in attesa della sua quota
    fresh = False                     # subito dopo il titolo: qui può comparire «Combo Builder»
    last_was_quote = False
    block = 0

    def record(label: str, price: float | None) -> None:
        normalized = _norm(label)
        market = spec.mapper(param, normalized) if spec and spec.mapper else None
        combo = paste.combo_sections.get(title, False)
        anchor = None
        if spec and spec.anchor and param and re.fullmatch(LINE, param) and re.fullmatch(UO, normalized):
            anchor = f"{_side(normalized)} {_line(param)} {spec.anchor}"
        is_exact = spec is not None and spec.mapper in (_exact, _exact_group)
        if market is not None and market not in keys and not is_exact:
            market = None   # nessun campo nel simulatore (es. Over 5.5 gol, Multigol 0-0)
        if price is None:
            status = SUSPENDED
        elif market is None:
            status = NOT_SIMULATED
        else:
            status = OK
        if status == OK:
            if market in seen:
                status = DUPLICATE
            else:
                seen[market] = price
        paste.quotes.append(EurobetQuote(title or "", label, param, price, market, status, combo, anchor, block))

    def flush() -> None:
        nonlocal pending
        if pending is not None:
            record(pending, None)
            pending = None

    def start(line: str) -> None:
        nonlocal spec, title, param, fresh, block
        flush()
        spec, title, param, fresh = _spec_for(line), line, None, True
        block += 1
        if spec is None:
            paste.unknown_sections.append(line)
        paste.combo_sections.setdefault(line, False)

    for line in _split(text):
        if line in _IGNORED:
            continue
        normalized = _norm(line)
        if normalized == COMBO_BUILDER:
            if title is not None and fresh:
                paste.combo_sections[title] = True
            continue
        is_quote = bool(_QUOTE.match(line))
        if spec is not None:
            if is_quote:
                if pending is not None:
                    label, pending = pending, None
                    record(label, _number(line))
                else:
                    paste.unrecognized_lines.append(f"{title}: quota {line} senza selezione")
            elif re.fullmatch(spec.labels, normalized):
                flush()
                pending = line
            elif spec.params and re.fullmatch(spec.params, normalized):
                flush()
                param = normalized
            else:
                start(line)
                last_was_quote = False
                continue
        elif title is not None:
            # Sezione sconosciuta: si ignora fino al prossimo titolo noto o a un nuovo titolo plausibile.
            if _spec_for(line) is not None or (not is_quote and last_was_quote and _looks_like_title(line)):
                start(line)
                last_was_quote = False
                continue
        elif _spec_for(line) is not None or _looks_like_title(line):
            start(line)
            continue
        else:
            paste.unrecognized_lines.append(line)
        fresh = False
        last_was_quote = is_quote
    flush()
    return paste


_GENERIC = {"si", "sì", "no", "under", "over", "gg", "ng", "pari", "dispari", "nessuno", "x", "altro"}


def _looks_like_title(line: str) -> bool:
    """Titolo plausibile di una sezione non in elenco: maiuscolo, con lettere, senza cifre, non un'etichetta comune."""
    text = line.strip()
    return (len(text) >= 3 and text == text.upper() and bool(re.search(r"[A-Z]", text))
            and not re.search(r"\d", text) and _norm(text) not in _GENERIC)


# --- Uso nell'app ---------------------------------------------------------------------------

def table_rows(paste: EurobetPaste) -> list[dict]:
    """Righe della tabella dopo l'incolla: sezione, selezione, linea, quota, mercato del simulatore, stato."""
    rows = []
    for quote in paste.quotes:
        market = quote.market if quote.market in event_keys() else (
            f"{EXACT_TARGET} ({quote.market})" if quote.market else None)
        if quote.status == NOT_SIMULATED and quote.anchor:
            market = f"solo ancoraggio ({quote.anchor})"
        rows.append({"Sezione": quote.section, "Selezione": quote.selection, "Linea": quote.line or "",
                     "Quota": quote.price, "Mercato del simulatore": market or "—", "Stato": quote.status,
                     "Combo Builder": "sì" if quote.combo_builder else ""})
    for line in paste.unrecognized_lines:
        rows.append({"Sezione": "", "Selezione": line, "Linea": "", "Quota": None, "Mercato del simulatore": "—",
                     "Stato": UNRECOGNIZED, "Combo Builder": ""})
    return rows


def apply_plan(paste: EurobetPaste, current: Mapping[str, float]) -> dict[str, dict[str, float]]:
    """Campi da riempire: ``fill`` (vuoti o con la stessa quota) e ``conflicts`` (già con un'altra quota, serve conferma)."""
    fill, conflicts = {}, {}
    for key, price in paste.odds().items():
        existing = float(current.get(key) or 0.0)
        if existing > 1.0 and abs(existing - price) > 1e-9:
            conflicts[key] = price
        else:
            fill[key] = price
    return {"fill": fill, "conflicts": conflicts}


def anchor_odds(odds: Mapping[str, float], sharp: Mapping[str, float] | None = None,
                paste: EurobetPaste | None = None) -> tuple[dict[str, float], dict[str, str]]:
    """Quote per l'ancoraggio (``MatchConfig.anchor_odds``) e fonte usata per gol, corner e cartellini.

    ``odds`` sono le quote dei campi (quelle giocate, Eurobet quando incollate: EV e semaforo). Gol: quota
    «sharp» dell'API (Pinnacle o mediana) se c'è l'1X2, altrimenti le quote dei campi (il margine si toglie
    nel motore). Corner e cartellini: tutta la scala Over/Under Eurobet se incollata, altrimenti le linee
    dei campi.
    """
    sharp = {key: float(value) for key, value in (sharp or {}).items() if value and float(value) > 1.0}
    result: dict[str, float] = {}
    sources: dict[str, str] = {}
    if all(key in sharp for key in ("1", "X", "2")):
        result |= {key: sharp[key] for key in GOAL_ANCHOR_KEYS if key in sharp}
        sources["gol"] = "quota sharp The Odds API"
    else:
        result |= {key: float(odds[key]) for key in GOAL_ANCHOR_KEYS if key in odds}
        eurobet = paste.odds() if paste else {}
        from_eurobet = any(key in eurobet and abs(eurobet[key] - float(odds[key])) < 1e-9
                           for key in ("1", "X", "2") if key in odds)
        sources["gol"] = "Eurobet senza margine" if from_eurobet else "quote dei campi senza margine"
    for kind in ("corner", "cartellini"):
        ladder = paste.count_lines(kind) if paste else {}
        if ladder:
            result |= ladder
            sources[kind] = f"scala Eurobet ({len(ladder) // 2} linee)"
        else:
            result |= {key: float(value) for key, value in odds.items()
                       if re.fullmatch(rf"(?:Over|Under) \d+\.5 {kind}", key)}
            sources[kind] = "quote dei campi"
    return result, sources


def skip_event_markets(paste: EurobetPaste | None, markets: Iterable[str]) -> list[str]:
    """Mercati per evento dell'API ancora da scaricare: niente corner o cartellini se la scala Eurobet c'è già."""
    skip = set()
    if paste is not None:
        if paste.count_lines("corner"):
            skip.add("alternate_totals_corners")
        if paste.count_lines("cartellini"):
            skip.add("alternate_totals_cards")
    return [market for market in markets if market not in skip]


def format_margin(value: float) -> str:
    return f"{value * 100:.1f}%".replace(".", ",")


def combo_allowed(legs: Iterable[str], combinable: Iterable[str]) -> bool:
    """Una multipla combinata (Combo Builder, fase S) usa solo mercati marcati «Combo Builder» nella pagina Eurobet."""
    allowed = set(combinable)
    legs = list(legs)
    return bool(legs) and all(leg in allowed for leg in legs)
