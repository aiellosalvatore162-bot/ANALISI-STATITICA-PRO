"""Schede tattiche per squadra, profili di Claude e regole di incrocio di stile (fase Q, punti 3-6).

Scheda: transizione offensiva (1 = orizzontale … 5 = verticale), gestione contro blocco basso, non
possesso (uomo/mista/zona), altezza del blocco, pressing, uso delle fasce e cross, note; dal profilo di
Claude anche allenatore (dal, precedente), moduli, adattabilità, comportamento contro forti/deboli e
reazioni in svantaggio/vantaggio, fonti e confidenza.

- ``parse_profiles`` legge i blocchi ``PROFILO_TATTICO: <squadra>`` (anche sotto ``SCHEDE_TATTICHE:``),
  tollerante come la fase G: valori fuori elenco scartati, blocco senza fonte (link) scartato;
- ``data_hints`` / ``contrasts``: indizi dai dati (profili di stile Understat) e avvisi di forte contrasto,
  mai correzioni automatiche;
- ``crossing_adjustment``: regole di incrocio con effetti piccoli e limitati (``config/tattica.json``), attenuate
  per le squadre adattabili; solo le regole accese (verificate) cambiano i calcoli.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "tattica.json"
LEVELS = ("basso", "medio", "alto")
CHOICES = {
    "gestione_blocco_basso": ("scarsa", "media", "buona"),
    "non_possesso": ("uomo", "mista", "zona"),
    "blocco": LEVELS, "pressing": LEVELS, "fasce_cross": LEVELS,
    "adattabilita": ("bassa", "media", "alta"),
    "confidenza": ("bassa", "media", "alta"),
}
TEXT_FIELDS = ("allenatore", "precedente", "modulo", "alternativo", "contro_forti", "contro_deboli",
               "se_in_svantaggio", "se_in_vantaggio", "note")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HEADER = re.compile(r"^[ \t>*#_-]*PROFILO_TATTICO\s*:\s*(?P<team>.+?)\s*\**\s*$", re.IGNORECASE | re.MULTILINE)
_DATE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")


@dataclass
class TacticalSheet:
    team: str
    transizione: int | None = None
    gestione_blocco_basso: str | None = None
    non_possesso: str | None = None
    blocco: str | None = None
    pressing: str | None = None
    fasce_cross: str | None = None
    note: str = ""
    allenatore: str = ""
    dal: str | None = None            # data ISO dell'arrivo dell'allenatore
    precedente: str = ""
    modulo: str = ""
    alternativo: str = ""
    adattabilita: str | None = None
    contro_forti: str = ""
    contro_deboli: str = ""
    se_in_svantaggio: str = ""
    se_in_vantaggio: str = ""
    fonti: list[str] = field(default_factory=list)
    confidenza: str | None = None
    origine: str = "manuale"          # «Claude (da confermare)», «Claude, confermata», «manuale»
    aggiornata: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TacticalSheet":
        names = {item.name for item in fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in names})

    def coach_since(self) -> date | None:
        return date.fromisoformat(self.dal) if self.dal else None


# --- Parser della risposta di Claude ----------------------------------------------------------------

def _date(text: str) -> str | None:
    found = _DATE.search(text)
    if not found:
        return None
    day, month, year = (int(value) for value in found.groups())
    year += 2000 if year < 100 else 0
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_profiles(text: str) -> tuple[list[TacticalSheet], list[str]]:
    """Profili dei blocchi ``PROFILO_TATTICO:``; ogni campo fuori elenco è scartato, un blocco senza fonte pure."""
    headers = list(_HEADER.finditer(text))
    sheets, warnings = [], []
    if not headers:
        return [], ["Nessun blocco «PROFILO_TATTICO: <squadra>» nella risposta."]
    for position, header in enumerate(headers):
        end = headers[position + 1].start() if position + 1 < len(headers) else len(text)
        body = text[header.end():end]
        team = header.group("team").strip().strip("*_").strip()
        sheet = TacticalSheet(team=team, origine="Claude (da confermare)", aggiornata=date.today().isoformat())
        for raw in body.splitlines():
            line = raw.strip().strip("`*-").strip()
            if not line:
                continue
            for part in line.split("|"):
                key, _, value = part.partition(":")
                key = key.strip().lower().replace(" ", "_").replace("à", "a")
                value = value.strip()
                if key == "fonte":
                    sheet.fonti += [match.rstrip(").,;") for match in _URL.findall(value)]
                elif key == "transizione":
                    number = re.search(r"[1-5]", value)
                    if number:
                        sheet.transizione = int(number.group(0))
                    elif value:
                        warnings.append(f"{team}: transizione «{value}» non valida (1-5), scartata.")
                elif key in CHOICES:
                    choice = value.lower().strip().split()[0] if value else ""
                    if choice in CHOICES[key]:
                        setattr(sheet, key, choice)
                    elif value:
                        warnings.append(f"{team}: {key} «{value}» non valido ({'/'.join(CHOICES[key])}), scartato.")
                elif key == "dal":
                    sheet.dal = _date(value)
                elif key in TEXT_FIELDS:
                    setattr(sheet, key, "" if value in ("-", "—") else value)
        if not sheet.fonti:
            warnings.append(f"{team}: nessuna fonte con link, profilo scartato.")
            continue
        sheets.append(sheet)
    return sheets, warnings


def sheet_lines(sheet: TacticalSheet) -> list[str]:
    """Scheda in righe leggibili (per i testi di Claude e le tabelle)."""
    parts = [f"transizione {sheet.transizione}/5 (1 orizzontale, 5 verticale)" if sheet.transizione else None,
             f"gestione blocco basso {sheet.gestione_blocco_basso}" if sheet.gestione_blocco_basso else None,
             f"non possesso {sheet.non_possesso}" if sheet.non_possesso else None,
             f"blocco {sheet.blocco}" if sheet.blocco else None, f"pressing {sheet.pressing}" if sheet.pressing else None,
             f"fasce/cross {sheet.fasce_cross}" if sheet.fasce_cross else None,
             f"adattabilità {sheet.adattabilita}" if sheet.adattabilita else None]
    lines = [f"{sheet.team}: " + ", ".join(part for part in parts if part)]
    if sheet.allenatore:
        lines.append(f"  allenatore {sheet.allenatore}" + (f" dal {sheet.dal}" if sheet.dal else ""))
    for label, value in (("se in svantaggio", sheet.se_in_svantaggio), ("se in vantaggio", sheet.se_in_vantaggio),
                         ("note", sheet.note)):
        if value:
            lines.append(f"  {label}: {value}")
    return lines


PROFILE_FORMAT = """PROFILO_TATTICO: <squadra>
allenatore: <nome> | dal: <gg/mm/aaaa> | precedente: <nome o ->
modulo: 4-3-3 | alternativo: 3-5-2
transizione: 1-5 | gestione_blocco_basso: buona/media/scarsa
non_possesso: uomo/mista/zona | blocco: alto/medio/basso | pressing: alto/medio/basso
fasce_cross: alto/medio/basso
adattabilita: alta/media/bassa
contro_forti: <come gioca> | contro_deboli: <come gioca>
se_in_svantaggio: <reazione> | se_in_vantaggio: <reazione>
fonte: https://... | fonte: https://...
confidenza: bassa/media/alta"""


def profile_prompt(teams: Sequence[str], hints: Mapping[str, Mapping[str, str]] | None = None) -> str:
    """Un testo per Claude con le squadre scelte: profilo tattico per squadra nel formato del parser."""
    hints = hints or {}
    lines = ["Sei un analista tattico di calcio. Per OGNUNA delle squadre qui sotto descrivi come gioca nella stagione "
             "in corso, verificando sul web (cita le fonti con link). Indica l'allenatore attuale e da quando è in carica.",
             "", "SQUADRE:"]
    for team in teams:
        clue = hints.get(team) or {}
        extra = f" (indizi dai dati: {', '.join(f'{key} {value}' for key, value in clue.items())})" if clue else ""
        lines.append(f"- {team}{extra}")
    lines += ["", "COME RISPONDERE: un blocco per squadra, esattamente in questo formato, senza altro testo nel blocco:", "",
              PROFILE_FORMAT, "",
              "Regole:",
              "- transizione: 1 = manovra orizzontale e paziente, 5 = attacca in verticale appena recupera palla.",
              "- adattabilita alta = cambia piano in base all'avversario; bassa = gioca sempre allo stesso modo.",
              "- Usa solo i valori indicati; ometti le righe che non conosci; senza almeno una fonte con link il profilo "
              "viene scartato."]
    return "\n".join(lines)


# --- Indizi dai dati e contrasti ---------------------------------------------------------------------

def _level(percentile: float) -> str:
    return "alto" if percentile >= 67 else "basso" if percentile <= 33 else "medio"


def data_hints(percentiles: Mapping[str, float] | None) -> dict[str, str]:
    """Indizi dai profili di stile Understat (percentile nel campionato): pressing, blocco, transizione."""
    if not percentiles:
        return {}
    hints = {}
    if "pressing" in percentiles:
        hints["pressing"] = _level(percentiles["pressing"])
    if "block_height" in percentiles:
        hints["blocco"] = _level(percentiles["block_height"])
    if "build_up" in percentiles and "transitions" in percentiles:
        vertical = (100 - percentiles["build_up"] + percentiles["transitions"]) / 2
        hints["transizione"] = str(1 + min(4, int(vertical // 20)))
    return hints


def contrasts(sheet: TacticalSheet, hints: Mapping[str, str]) -> list[str]:
    """Avvisi quando scheda e dati sono agli opposti (alto contro basso, transizione a 3+ punti): mai correzioni."""
    warnings = []
    for key in ("pressing", "blocco"):
        value, clue = getattr(sheet, key), hints.get(key)
        if value and clue and {value, clue} == {"alto", "basso"}:
            warnings.append(f"{sheet.team}: {key} «{value}» nella scheda, ma i dati dicono «{clue}». Verifica.")
    if sheet.transizione and hints.get("transizione") and abs(sheet.transizione - int(hints["transizione"])) >= 3:
        warnings.append(f"{sheet.team}: transizione {sheet.transizione} nella scheda, ma i dati indicano "
                        f"{hints['transizione']}. Verifica.")
    return warnings


def matchup_text(sheet: TacticalSheet, own_elo: float, opponent_elo: float) -> str:
    """Comportamento contro questo avversario: «contro_forti» se l'avversario ha più Elo, altrimenti «contro_deboli»."""
    stronger = opponent_elo > own_elo
    text = sheet.contro_forti if stronger else sheet.contro_deboli
    return f"contro un avversario {'più forte' if stronger else 'più debole'}: {text}" if text else ""


# --- Regole di incrocio ----------------------------------------------------------------------------

def load_rules(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


ADAPTABILITY = {"bassa": 1.0, "media": 0.75, "alta": 0.5, None: 1.0}


def _applies(rule: Mapping[str, Any], attack: TacticalSheet, defence: TacticalSheet) -> bool:
    condition = rule["condizione"]
    for side, sheet in (("attacco", attack), ("difesa", defence)):
        for key, allowed in condition.get(side, {}).items():
            value = getattr(sheet, key)
            if key == "transizione":
                if value is None or not (allowed[0] <= value <= allowed[1]):
                    return False
            elif value not in allowed:
                return False
    return True


def crossing_adjustment(home: TacticalSheet | None, away: TacticalSheet | None, *, settings: Mapping[str, Any] | None = None,
                        only_active: bool = True) -> tuple[dict[str, float], list[str]]:
    """Fattori sui gol di casa/ospite, corner e cartellini dalle regole di incrocio, nei limiti di config.

    Ogni regola guarda una squadra che attacca contro l'altra che difende; l'effetto è attenuato
    dall'adattabilità di chi attacca (alta = 0.5). Con ``only_active`` contano solo le regole accese.
    """
    settings = settings or load_rules()
    factors = {"gol_casa": 1.0, "gol_ospite": 1.0, "corner": 1.0, "cartellini": 1.0}
    notes = []
    if home is None or away is None:
        return factors, notes
    for rule in settings["regole"]:
        if only_active and not rule.get("attiva"):
            continue
        for attack, defence, goal_key in ((home, away, "gol_casa"), (away, home, "gol_ospite")):
            if not _applies(rule, attack, defence):
                continue
            scale = ADAPTABILITY.get(attack.adattabilita, 1.0)
            effect = rule["effetto"]
            for key, value in (("gol", goal_key), ("corner", "corner"), ("cartellini", "cartellini")):
                if key in effect:
                    factors[value] *= 1.0 + (float(effect[key]) - 1.0) * scale
            notes.append(f"{rule['nome']}: {attack.team} contro {defence.team}"
                         + (f" (attenuata: adattabilità {attack.adattabilita})" if scale < 1 else ""))
    low, high = settings["limiti"]
    return {key: min(max(value, low), high) for key, value in factors.items()}, notes


# --- Regole «da osservatore» con i profili dell'Analista (fase Y) ------------------------------------

PROFILE_ORIGINS = ("Analista", "Claude")


def from_profile(sheet: TacticalSheet | None) -> bool:
    """Scheda nata da un blocco PROFILO_TATTICO (Analista o Claude), non scritta a mano."""
    return sheet is not None and sheet.origine.startswith(PROFILE_ORIGINS)


def analyst_adjustment(home: TacticalSheet | None, away: TacticalSheet | None,
                       settings: Mapping[str, Any] | None = None) -> tuple[dict[str, float], list[str]]:
    """Regole non misurabili con i dati gratuiti, applicate con i profili PROFILO_TATTICO: effetto ridotto ai
    limiti di ``regole_analista`` (0.95-1.05), solo con stato «da verificare» o «verificata»."""
    settings = settings or load_rules()
    section = settings.get("regole_analista") or {}
    factors = {"gol_casa": 1.0, "gol_ospite": 1.0, "corner": 1.0, "cartellini": 1.0}
    notes: list[str] = []
    if not section.get("attiva") or not (from_profile(home) and from_profile(away)):
        return factors, notes
    low, high = section.get("limiti", (0.95, 1.05))
    rules = {rule["id"]: rule for rule in settings["regole"]}
    for rule_id, state in (section.get("regole") or {}).items():
        status = state.get("stato", "da verificare")
        if status == "spenta" or rule_id not in rules:
            continue
        rule = rules[rule_id]
        effect = state.get("effetto") if status == "verificata" and state.get("effetto") else rule["effetto"]
        for attack, defence, goal_key in ((home, away, "gol_casa"), (away, home, "gol_ospite")):
            if not _applies(rule, attack, defence):
                continue
            scale = ADAPTABILITY.get(attack.adattabilita, 1.0)
            for key, target in (("gol", goal_key), ("corner", "corner"), ("cartellini", "cartellini")):
                if key in effect:
                    value = min(max(1.0 + (float(effect[key]) - 1.0) * scale, low), high)
                    factors[target] *= value
            notes.append(f"{rule['nome']}: {attack.team} contro {defence.team}"
                         + (" (regola non ancora verificata)" if status != "verificata" else " (verificata)"))
    return {key: min(max(value, low), high) for key, value in factors.items()}, notes


def merge_profile(old: TacticalSheet | None, new: TacticalSheet) -> tuple[TacticalSheet, list[dict]]:
    """Profilo nuovo sopra quello salvato: i campi vuoti del nuovo tengono il vecchio valore. Restituisce anche
    i cambiamenti di valori già presenti (da confermare); campi nuovi, data e fonti non chiedono conferma."""
    if old is None:
        return new, []
    merged, changes = old.to_dict(), []
    for name, value in new.to_dict().items():
        if name in ("team", "origine", "aggiornata", "fonti"):
            continue
        if value in (None, "", []):
            continue
        if merged.get(name) not in (None, "", []) and merged[name] != value:
            changes.append({"Squadra": old.team, "Campo": name, "Prima": merged[name], "Dopo": value})
        merged[name] = value
    merged["fonti"] = list(dict.fromkeys([*new.fonti, *old.fonti]))
    merged["origine"], merged["aggiornata"] = new.origine, new.aggiornata
    return TacticalSheet.from_dict(merged), changes


# --- Reazioni allo stato della partita (motore minuto per minuto) ------------------------------------

_AGGRESSIVE = ("attacc", "spinge", "alza", "aggressiv", "offensiv", "forza", "in avanti")
_PASSIVE = ("chiude", "abbass", "difend", "gestisce", "rallent", "conserva", "addormenta")


def reaction_factors(sheet: TacticalSheet | None, settings: Mapping[str, Any] | None = None) -> tuple[float, float]:
    """(fattore quando è in svantaggio, fattore quando è in vantaggio) dal testo delle reazioni, nei limiti di config."""
    if sheet is None:
        return 1.0, 1.0
    settings = settings or load_rules()
    step = float(settings.get("reazioni", {}).get("passo", 0.08))

    def read(text: str) -> float:
        text = text.lower()
        if any(word in text for word in _AGGRESSIVE):
            return 1.0 + step
        if any(word in text for word in _PASSIVE):
            return 1.0 - step
        return 1.0
    return read(sheet.se_in_svantaggio), read(sheet.se_in_vantaggio)


# --- Effetti sulla partita ---------------------------------------------------------------------------

def coach_change(sheet: TacticalSheet | None, settings: Mapping[str, Any] | None = None):
    """``datasources.stats.CoachChange`` dalla data «dal» della scheda (pesi in ``cambio_allenatore``)."""
    from datasources.stats import CoachChange

    since = sheet.coach_since() if sheet is not None else None
    if since is None:
        return None
    settings = (settings or load_rules()).get("cambio_allenatore", {})
    return CoachChange(since, float(settings.get("peso_partite_precedenti", 0.3)), int(settings.get("partite_per_fidarsi", 8)))


@dataclass
class MatchEffects:
    """Schede trovate per la partita e quello che cambiano: fattori di incrocio (solo regole accese) e reazioni."""

    home: TacticalSheet | None
    away: TacticalSheet | None
    factors: dict[str, float]
    notes: list[str]
    reactions: tuple[float, float, float, float]
    analyst_notes: list[str] = field(default_factory=list)   # fase Y: regole non ancora verificate applicate

    @property
    def analyst_rules(self) -> bool:
        return bool(self.analyst_notes)

    @property
    def any_sheet(self) -> bool:
        return self.home is not None or self.away is not None

    def coaches(self, settings: Mapping[str, Any] | None = None) -> dict:
        return {side: change for side, change in (("home", coach_change(self.home, settings)),
                                                  ("away", coach_change(self.away, settings))) if change is not None}

    def timeline(self, params):
        """Parametri del motore minuto per minuto con le reazioni delle schede (contano solo se il motore è attivo)."""
        if self.reactions == (1.0, 1.0, 1.0, 1.0) or not hasattr(params, "reactions"):
            return params
        return replace(params, reactions=self.reactions)


def match_effects(sheets: Iterable[Mapping[str, Any]], home: str, away: str,
                  settings: Mapping[str, Any] | None = None) -> MatchEffects:
    sheets = list(sheets)
    settings = settings or load_rules()
    home_sheet, away_sheet = find_sheet(sheets, home), find_sheet(sheets, away)
    factors, notes = crossing_adjustment(home_sheet, away_sheet, settings=settings)
    extra, analyst_notes = analyst_adjustment(home_sheet, away_sheet, settings)
    factors = {key: value * extra.get(key, 1.0) for key, value in factors.items()}
    return MatchEffects(home_sheet, away_sheet, factors, notes,
                        (*reaction_factors(home_sheet, settings), *reaction_factors(away_sheet, settings)), analyst_notes)


def prompt_lines(effects: MatchEffects, elo: tuple[float, float] | None = None) -> list[str]:
    """Righe «SCHEDE TATTICHE» da aggiungere al testo per Claude (vuoto senza schede)."""
    if not effects.any_sheet:
        return []
    lines = ["SCHEDE TATTICHE (mie, da verificare):"]
    for sheet, own, other in ((effects.home, 0, 1), (effects.away, 1, 0)):
        if sheet is None:
            continue
        lines += [f"- {line.strip()}" for line in sheet_lines(sheet)]
        if elo is not None:
            text = matchup_text(sheet, elo[own], elo[other])
            if text:
                lines.append(f"  {text}")
    return lines + [""]


def upsert(sheets: Sequence[Mapping[str, Any]], new: Iterable[TacticalSheet]) -> list[dict]:
    """Elenco delle schede salvate con le nuove al posto di quelle della stessa squadra."""
    from datasources.names import match_team

    result = [dict(item) for item in sheets]
    for sheet in new:
        teams = [item.get("team") for item in result]
        name = match_team(sheet.team, teams) if teams else None
        result = [item for item in result if item.get("team") != name] + [sheet.to_dict()]
    return result


# --- Excel della giornata ---------------------------------------------------------------------------

SHEET_COLUMNS = ("Squadra", "Aggiornata", "Origine", "Allenatore", "Dal", "Modulo", "Transizione", "Gestione blocco basso",
                 "Non possesso", "Blocco", "Pressing", "Fasce/cross", "Adattabilità", "Contro forti", "Contro deboli",
                 "Se in svantaggio", "Se in vantaggio", "Fonti", "Confidenza", "Note")


def sheet_row(sheet: TacticalSheet) -> dict:
    return {"Squadra": sheet.team, "Aggiornata": sheet.aggiornata, "Origine": sheet.origine, "Allenatore": sheet.allenatore,
            "Dal": sheet.dal, "Modulo": " / ".join(part for part in (sheet.modulo, sheet.alternativo) if part),
            "Transizione": sheet.transizione, "Gestione blocco basso": sheet.gestione_blocco_basso,
            "Non possesso": sheet.non_possesso, "Blocco": sheet.blocco, "Pressing": sheet.pressing,
            "Fasce/cross": sheet.fasce_cross, "Adattabilità": sheet.adattabilita, "Contro forti": sheet.contro_forti,
            "Contro deboli": sheet.contro_deboli, "Se in svantaggio": sheet.se_in_svantaggio,
            "Se in vantaggio": sheet.se_in_vantaggio, "Fonti": " ".join(sheet.fonti), "Confidenza": sheet.confidenza,
            "Note": sheet.note}


def find_sheet(sheets: Iterable[Mapping[str, Any]], team: str) -> TacticalSheet | None:
    """Scheda salvata della squadra (nomi riconosciuti anche con grafie diverse)."""
    from datasources.names import match_team

    stored = {item.get("team"): item for item in sheets if item.get("team")}
    name = match_team(team, list(stored)) if stored else None
    return TacticalSheet.from_dict(stored[name]) if name else None
