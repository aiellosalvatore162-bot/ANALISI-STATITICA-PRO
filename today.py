"""Pagina «Oggi» (fase S): analisi in blocco delle partite del giorno, giocate di valore, Claude e verifica esiti.

Per ogni partita: dati automatici (``DataProvider.build``), quote del passaggio
economico (1X2 e Over/Under per campionato), simulazione. Le partite con dati
mancanti sono segnalate e saltate: nessun valore inventato.

Le segnalazioni da osservatore («partita aperta», «turnover casa»…) e le
correzioni di Claude si applicano come ``engine.ClaudeAdjustment`` dopo
l'ancoraggio al mercato; le segnalazioni hanno effetti piccoli e limitati in
``config/oggi.json`` e finiscono nella colonna Note del registro.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from claude_bridge import BOUNDS, HEADER, RESPONSE_FORMAT, ClaudeResponse, ResponseError, parse_response, probability_lines
from engine import ClaudeAdjustment, MatchConfig, config_from_input, simulate_match
from multiples import load_settings


@dataclass(frozen=True)
class TodayMatch:
    event_id: str
    sport: str
    competition: str
    commence_time: datetime
    home: str
    away: str

    @property
    def label(self) -> str:
        return f"{self.home} - {self.away}"


@dataclass
class Analysis:
    match: TodayMatch
    block: str = ""
    odds: dict[str, float] = field(default_factory=dict)
    config: MatchConfig | None = None          # senza segnalazioni né Claude
    result: dict | None = None
    flags: tuple[str, ...] = ()
    claude: ClaudeResponse | None = None
    claude_text: str = ""                      # blocco di Claude della partita, nel formato della scheda
    skipped: str | None = None                 # motivo per cui la partita è saltata
    warnings: list[str] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.result is not None

    def note(self) -> str:
        """Note del registro: segnalazioni e confidenza di Claude, per misurarle nella pagina Prestazioni."""
        parts = [f"segnalazione: {', '.join(self.flags)}"] if self.flags else []
        if self.claude is not None and self.claude.adjustment() is not None:
            parts.append(f"Claude (oggi){f' confidenza {self.claude.confidence}' if self.claude.confidence else ''}")
        return "; ".join(parts)


# --- Analisi in blocco ----------------------------------------------------------------------------

def analyze(match: TodayMatch, build: Callable[..., Any], odds_fields: Mapping[str, Any], *,
            simulations: int, competition: str | None = None, settings: Mapping[str, Any] | None = None) -> Analysis:
    """Dati automatici + quote del passaggio economico + simulazione; salta la partita se manca un dato.

    ``build`` è ``DataProvider.build`` (o un sostituto nei test); ``odds_fields`` sono i campi quota del blocco
    (``oddsapi.sheet_odds``).
    """
    from datasources.builder import missing_fields, provenance_rows, render_block
    from parser import MatchInputError, parse_match_input

    analysis = Analysis(match)
    try:
        sheet = build(match.home, match.away, match_date=match.commence_time.date(), competition=competition)
    except Exception as exc:  # fonti remote: si degrada con un avviso, mai un blocco dell'intera giornata
        analysis.skipped = f"dati automatici non disponibili ({type(exc).__name__}: {str(exc)[:120]})"
        return analysis
    sheet.odds = dict(odds_fields)
    sheet.competition = sheet.competition or match.competition
    analysis.warnings = list(sheet.warnings)
    analysis.sources = provenance_rows(sheet)
    missing = missing_fields(sheet)
    if missing:
        analysis.skipped = "dati mancanti: " + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else "")
        return analysis
    analysis.block = render_block(sheet)
    try:
        parsed = parse_match_input(analysis.block)
    except MatchInputError as exc:
        analysis.skipped = f"blocco non valido: {exc}"
        return analysis
    analysis.odds = dict(parsed.odds)
    analysis.config = config_from_input(parsed, simulations=simulations)
    return simulate(analysis, settings=settings)


def simulate(analysis: Analysis, *, flags: Sequence[str] | None = None, claude: ClaudeResponse | None = None,
             extra_odds: Mapping[str, float] | None = None, settings: Mapping[str, Any] | None = None,
             keep_claude: bool = True) -> Analysis:
    """Ricalcolo della partita con segnalazioni, correzioni di Claude e quote aggiuntive (es. corner mirati)."""
    if analysis.config is None:
        return analysis
    if flags is not None:
        analysis.flags = tuple(flags)
    if claude is not None or not keep_claude:
        analysis.claude = claude
    if extra_odds:
        analysis.odds = {**analysis.odds, **{key: float(value) for key, value in extra_odds.items()}}
    adjustment = combined_adjustment(analysis.flags, analysis.claude, settings)
    referee = analysis.claude.referee_yellow(analysis.config.referee_yellow_avg) if analysis.claude else None
    config = replace(analysis.config, odds=dict(analysis.odds), claude=adjustment,
                     referee_yellow_avg=referee if referee is not None else analysis.config.referee_yellow_avg)
    analysis.result = simulate_match(config)
    return analysis


def observer_adjustment(flags: Iterable[str], settings: Mapping[str, Any] | None = None) -> dict[str, float]:
    """Fattori delle segnalazioni da osservatore: prodotto dei fattori, limitato in ``limiti_segnalazioni``."""
    settings = settings or load_settings()
    factors = {"gol_casa": 1.0, "gol_ospite": 1.0, "corner": 1.0, "cartellini": 1.0}
    for flag in flags:
        effect = settings["segnalazioni"].get(flag)
        if effect is None:
            raise ValueError(f"Segnalazione «{flag}» non prevista in config/oggi.json.")
        for key in factors:
            factors[key] *= float(effect.get(key, 1.0))
    limits = settings["limiti_segnalazioni"]
    bound = {"gol_casa": limits["gol"], "gol_ospite": limits["gol"], "corner": limits["corner"], "cartellini": limits["cartellini"]}
    return {key: min(max(value, bound[key][0]), bound[key][1]) for key, value in factors.items()}


def combined_adjustment(flags: Iterable[str], claude: ClaudeResponse | None,
                        settings: Mapping[str, Any] | None = None) -> ClaudeAdjustment | None:
    """Segnalazioni × correzioni di Claude (ciascuna già nei propri limiti); ``None`` se nulla da applicare."""
    observer = observer_adjustment(flags, settings)
    from_claude = claude.adjustment() if claude is not None else None
    values = {
        "goals_home": observer["gol_casa"] * (from_claude.goals_home if from_claude else 1.0),
        "goals_away": observer["gol_ospite"] * (from_claude.goals_away if from_claude else 1.0),
        "corners": observer["corner"] * (from_claude.corners if from_claude else 1.0),
        "cards": observer["cartellini"] * (from_claude.cards if from_claude else 1.0),
    }
    if all(abs(value - 1.0) < 1e-12 for value in values.values()):
        return None
    return ClaudeAdjustment(**values)


# --- Cartellini per squadra (fase T) ------------------------------------------------------------------

_TEAM_CARD = re.compile(r"^(?:(?:Casa|Ospite) (?:Over|Under) \d+\.5 cartellini|[1X2] cartellini)$")


def team_card_market(selection: str) -> bool:
    """1X2 cartellini e Over/Under cartellini per squadra (divisione tra le squadre)."""
    return bool(_TEAM_CARD.match(selection))


def team_cards_status(settings: Mapping[str, Any] | None = None, verification: Mapping[str, Any] | None = None) -> tuple[bool, str]:
    """Ammessi se la verifica fuori campione (``python -m tools.card_split --salva``) dà ECE entro la soglia per ogni voce."""
    import json

    from engine import GOAL_MODEL_PATH

    settings = settings or load_settings()
    limit = float(settings.get("cartellini_squadra", {}).get("ece_massimo", 0.03))
    if verification is None:
        try:
            verification = json.loads(GOAL_MODEL_PATH.read_text(encoding="utf-8")).get("divisione_cartellini", {})
        except (OSError, ValueError):
            verification = {}
    values = {key: value for key, value in (verification.get("ece_fuori_campione") or {}).items() if key != "media"}
    if not verification.get("attiva") or not values:
        return False, "divisione dei cartellini non verificata (python -m tools.card_split --salva)"
    worst = max(values, key=values.get)
    if values[worst] > limit:
        return False, f"ECE fuori campione {values[worst]:.3f} su {worst}, oltre la soglia {limit:.3f}"
    return True, f"ECE fuori campione al massimo {values[worst]:.3f} ({worst}), entro la soglia {limit:.3f}"


# --- Giocate di valore (modalità veloce) -------------------------------------------------------------

THRESHOLD_GROUPS = {"Over 1.5": "Gol", "Under 1.5": "Gol", "Over 2.5": "Gol", "Under 2.5": "Gol", "Over 3.5": "Gol",
                    "Under 3.5": "Gol", "Goal/NoGoal": "Gol", "Multigol": "Gol", "Multigol casa": "Gol",
                    "Multigol ospite": "Gol", "Over 0.5 1T": "Primo tempo", "Over 1.5 1T": "Primo tempo"}


def ev_threshold(selection: str, settings: Mapping[str, Any] | None = None) -> float | None:
    """Soglia EV (punti %) del mercato della selezione; ``None`` se il mercato non è registrabile."""
    from prediction_log import market_of

    settings = settings or load_settings()
    market = market_of(selection)
    if market is None:
        return None
    group = THRESHOLD_GROUPS.get(market, market)
    return float(settings["soglie_ev"].get(group, settings["soglie_ev"].get("Gol", 3.0)))


@dataclass(frozen=True)
class Pick:
    analysis_index: int
    match: str
    selection: str
    probability: float      # %
    odds: float
    ev: float               # %
    threshold: float
    reason: str
    suspicious: bool = False


def value_picks(analyses: Sequence[Analysis], settings: Mapping[str, Any] | None = None, *,
                include_team_cards: bool | None = None) -> list[Pick]:
    """Giocate con valore sopra la soglia EV del proprio mercato, dalla più alta, ognuna con il perché.

    1X2 cartellini e cartellini per squadra solo se ammessi (``team_cards_status``) o scelti a mano.
    """
    settings = settings or load_settings()
    if include_team_cards is None:
        include_team_cards = team_cards_status(settings)[0]
    picks = []
    for index, analysis in enumerate(analyses):
        if not analysis.ok:
            continue
        for row in analysis.result["financial"]["markets"]:
            threshold = ev_threshold(row["market"], settings)
            if threshold is None or not row.get("is_value") or row["ev_pct"] < threshold:
                continue
            if team_card_market(row["market"]) and not include_team_cards:
                continue
            picks.append(Pick(index, analysis.match.label, row["market"], row["simulated_probability_pct"], row["odds"],
                              row["ev_pct"], threshold, explain(row, analysis), bool(row.get("suspicious_value"))))
    return sorted(picks, key=lambda pick: pick.ev, reverse=True)


def explain(row: Mapping[str, Any], analysis: Analysis) -> str:
    """Una frase: probabilità del simulatore contro quella della quota, e da dove viene la differenza."""
    result = analysis.result
    text = (f"Il simulatore dà {row['simulated_probability_pct']:.0f}% contro il {row['implied_probability_pct']:.0f}% "
            f"implicito nella quota {row['odds']:.2f} (EV {row['ev_pct']:+.1f}%)")
    market = row["market"]
    if "corner" in market:
        text += f"; corner attesi {result['markets']['corners']['mean']:.1f}"
    elif "cartellini" in market:
        text += f"; punti cartellini attesi {result['markets']['cards']['mean']:.1f}"
    else:
        text += f"; gol attesi {result['model']['lambda']:.2f} - {result['model']['mu']:.2f}"
    model, market_only = row.get("model_only_probability_pct"), row.get("market_only_probability_pct")
    if model is not None and market_only is not None:
        text += f" (solo modello {model:.0f}%, solo mercato {market_only:.0f}%)"
    if analysis.flags:
        text += f"; segnalazioni: {', '.join(analysis.flags)}"
    if row.get("suspicious_value"):
        text += ". Attenzione: modello e mercato molto distanti, verifica i dati"
    return text + "."


# --- Claude: un solo testo per tutte le partite -------------------------------------------------------

_MULTI_HEADER = re.compile(rf"{re.escape(HEADER)}\s*(?:ID\s*[:=]?\s*)?(P\d+)", re.IGNORECASE)


def match_ids(analyses: Sequence[Analysis]) -> dict[str, int]:
    """ID delle partite nel testo per Claude («P1», «P2»…) -> indice dell'analisi."""
    return {f"P{position}": index for position, index in enumerate(
        (index for index, analysis in enumerate(analyses) if analysis.ok), start=1)}


def multi_analysis_prompt(analyses: Sequence[Analysis], selected: Iterable[int], *, day: date | None = None) -> str:
    """Un unico testo per Claude con tutte le partite selezionate, ognuna con il suo ID."""
    selected = set(selected)
    ids = {index: match_id for match_id, index in match_ids(analyses).items() if index in selected}
    sections = []
    for index, match_id in ids.items():
        analysis = analyses[index]
        sections += [
            f"=== {match_id} · {analysis.match.label} ({analysis.match.competition}, "
            f"{analysis.match.commence_time:%d/%m/%Y %H:%M} UTC) ===",
            "INPUT DEL SIMULATORE:", "```", analysis.block.strip(), "```",
            "PROBABILITÀ DEL SIMULATORE:", *[f"- {line}" for line in probability_lines(analysis.result)], "",
        ]
    example = RESPONSE_FORMAT.replace(HEADER, f"{HEADER} P1", 1)
    return "\n".join([
        "Sei un analista di calcio. Per OGNUNA delle partite qui sotto verifica sul web i fatti e confrontali con gli "
        "input del mio simulatore." + (f" Data: {day:%d/%m/%Y}." if day else ""),
        "",
        "COSA VERIFICARE PER OGNI PARTITA (cita sempre la fonte con un link):",
        "1. Formazioni probabili o ufficiali; assenze per infortunio e squalifiche, soprattutto titolari e portieri.",
        "2. Turnover probabile per impegni ravvicinati.",
        "3. Arbitro designato e sue medie di gialli e falli per partita, con il numero di partite.",
        "4. Motivazioni (classifica, derby, qualificazione) e meteo previsto.",
        "5. Incoerenze tra questi fatti e gli input del simulatore.",
        "",
        *sections,
        "COME RISPONDERE:",
        "Per ogni partita scrivi al massimo 3 righe di commento, poi un blocco con il suo ID, in questo formato:",
        "",
        example,
        "",
        "Regole del blocco (uguali per ogni partita):",
        "- Un blocco per partita, con l'ID esatto dopo «CORREZIONI_CLAUDE:» (P1, P2…).",
        "- gol_casa, gol_ospite, corner e cartellini sono fattori moltiplicativi (1.00 = nessuna modifica). "
        f"Limiti applicati dall'app: gol e corner {BOUNDS['corner'][0]:.2f}-{BOUNDS['corner'][1]:.2f}, cartellini "
        f"{BOUNDS['cartellini'][0]:.2f}-{BOUNDS['cartellini'][1]:.2f}.",
        "- Ogni correzione diversa da 1.00 deve avere una fonte con link (https://...): senza fonte viene ignorata.",
        "- Usa arbitro_gialli_medi solo con la media dell'arbitro designato e il numero di partite.",
        "- Ometti le righe senza informazioni affidabili. confidenza: bassa, media o alta.",
    ])


def split_multi_response(text: str, ids: Mapping[str, int]) -> tuple[dict[int, str], list[str]]:
    """Blocco di ogni partita nel formato a partita singola («CORREZIONI_CLAUDE:» senza ID), più gli avvisi."""
    found = list(_MULTI_HEADER.finditer(text))
    if not found:
        raise ResponseError(f"Nella risposta non ci sono blocchi «{HEADER} P1»: chiedi a Claude di usare gli ID.")
    texts, warnings = {}, []
    for position, header in enumerate(found):
        match_id = header.group(1).upper()
        end = found[position + 1].start() if position + 1 < len(found) else len(text)
        if match_id not in ids:
            warnings.append(f"Blocco {match_id}: ID non presente nel testo inviato, ignorato.")
            continue
        if ids[match_id] in texts:
            warnings.append(f"Blocco {match_id} ripetuto: uso solo il primo.")
            continue
        texts[ids[match_id]] = f"{HEADER}\n{text[header.end():end].strip()}"
    missing = sorted(match_id for match_id, index in ids.items() if index not in texts)
    if missing:
        warnings.append("Partite senza blocco nella risposta: " + ", ".join(missing) + ".")
    return texts, warnings


def parse_multi_response(text: str, ids: Mapping[str, int]) -> tuple[dict[int, ClaudeResponse], list[str]]:
    """Blocchi «CORREZIONI_CLAUDE: P1» … della risposta: indice dell'analisi -> correzioni, più gli avvisi."""
    texts, warnings = split_multi_response(text, ids)
    return {index: parse_response(block) for index, block in texts.items()}, warnings


# --- Verifica esiti con Claude (corner e cartellini delle coppe) ------------------------------------

OUTCOME_HEADER = "ESITI_CLAUDE:"
OUTCOME_MARKETS = ("Corner", "Cartellini")
_OUTCOME_BLOCK = re.compile(rf"{re.escape(OUTCOME_HEADER)}\s*(E\d+)", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def outcome_targets(frame) -> list[dict]:
    """Partite con selezioni di corner o cartellini ancora senza esito: una voce per partita e data."""
    import pandas as pd

    rows = frame[frame["Esito"].isna() & frame["Mercato"].isin(OUTCOME_MARKETS)]
    rows = rows[~rows["Note"].fillna("").str.contains("rimborsata")]
    targets = []
    for (day, match), group in rows.groupby(["Data", "Partita"], sort=True):
        if pd.isna(day):
            continue
        targets.append({"id": f"E{len(targets) + 1}", "date": day, "match": match,
                        "competition": next((value for value in group["Competizione"] if value), ""),
                        "selections": sorted(set(group["Selezione"]))})
    return targets


def outcome_prompt(targets: Sequence[Mapping[str, Any]]) -> str:
    """Un unico testo per Claude con tutte le partite da verificare."""
    lines = [
        "Per ognuna delle partite qui sotto cerca sul web il tabellino ufficiale (sito della competizione, UEFA, "
        "Lega o un sito di statistiche affidabile) e riporta i numeri finali. Cita sempre la fonte con un link.",
        "",
        *[f"{target['id']} · {target['match']} · {target['date']:%d/%m/%Y}"
          + (f" · {target['competition']}" if target["competition"] else "")
          + f" (da verificare: {', '.join(target['selections'])})" for target in targets],
        "",
        "COME RISPONDERE: per ogni partita SOLO un blocco con il suo ID, in questo formato (casa-ospite):",
        "",
        f"{OUTCOME_HEADER} E1",
        "risultato: 2-1",
        "primo_tempo: 1-0",
        "corner: 6-4",
        "gialli: 2-3",
        "rossi: 0-1",
        "fonte: https://...",
        "",
        "Regole:",
        "- corner, gialli e rossi sono per squadra, casa-ospite, a fine partita (tempi supplementari esclusi).",
        "- gialli: le ammonizioni, senza contare il secondo giallo di chi viene espulso per doppia ammonizione; "
        "rossi: tutte le espulsioni, anche per doppia ammonizione.",
        "- Ometti le righe che non trovi; senza fonte il blocco viene ignorato.",
    ]
    return "\n".join(lines)


def parse_outcomes(text: str, targets: Sequence[Mapping[str, Any]]):
    """Blocchi ``ESITI_CLAUDE`` -> (risultati per ``performance.fill_from_results`` con la fonte, avvisi)."""
    import pandas as pd

    from performance import split_match

    by_id = {target["id"]: target for target in targets}
    found = list(_OUTCOME_BLOCK.finditer(text))
    if not found:
        raise ResponseError(f"Nella risposta non ci sono blocchi «{OUTCOME_HEADER} E1».")
    results, warnings = [], []
    for position, header in enumerate(found):
        target = by_id.get(header.group(1).upper())
        end = found[position + 1].start() if position + 1 < len(found) else len(text)
        if target is None:
            warnings.append(f"Blocco {header.group(1)}: ID non presente nel testo inviato, ignorato.")
            continue
        values: dict[str, Any] = {}
        source = None
        for raw in text[header.end():end].splitlines():
            key, _, value = raw.strip().strip("`*-").strip().partition(":")
            key = key.strip().lower().replace(" ", "_")
            if key == "fonte":
                url = _URL.search(value)
                source = url.group(0).rstrip(").,;") if url else None
                continue
            pair = re.fullmatch(r"\s*(\d+)\s*[-–:]\s*(\d+)\s*", value)
            columns = {"risultato": ("home_goals", "away_goals"), "primo_tempo": ("home_ht_goals", "away_ht_goals"),
                       "corner": ("home_corners", "away_corners"), "gialli": ("home_yellows", "away_yellows"),
                       "rossi": ("home_reds", "away_reds")}.get(key)
            if columns and pair:
                values[columns[0]], values[columns[1]] = int(pair[1]), int(pair[2])
        if source is None:
            warnings.append(f"{target['id']} {target['match']}: senza fonte, ignorato.")
            continue
        if "home_goals" not in values:
            warnings.append(f"{target['id']} {target['match']}: manca il risultato finale, ignorato.")
            continue
        teams = split_match(target["match"]) or (target["match"], "")
        results.append({"date": pd.Timestamp(target["date"]), "home_team": teams[0], "away_team": teams[1],
                        "source": source, **values})
    return results, warnings
