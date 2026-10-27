"""Integrazione con Claude via copia e incolla (nessuna API, nessuna chiave).

1. ``analysis_prompt`` prepara il testo da incollare in Claude: istruzioni di
   verifica sul web, input della partita con fonti e date, probabilità del
   simulatore e formato della risposta.
2. ``parse_response`` legge il blocco ``CORREZIONI_CLAUDE:`` restituito da
   Claude, applica i limiti e scarta le correzioni senza fonte.
3. ``extraction_prompt`` prepara le istruzioni per trasformare il testo grezzo
   di un sito nel blocco del parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Mapping

from engine import ClaudeAdjustment


HEADER = "CORREZIONI_CLAUDE:"
BOUNDS = {
    "gol_casa": (0.90, 1.10),
    "gol_ospite": (0.90, 1.10),
    "corner": (0.90, 1.10),
    "cartellini": (0.85, 1.15),
}
LABELS = {
    "gol_casa": "Gol attesi casa (dopo l'ancoraggio al mercato)",
    "gol_ospite": "Gol attesi ospite (dopo l'ancoraggio al mercato)",
    "corner": "Corner (media)",
    "cartellini": "Cartellini (media)",
    "arbitro_gialli_medi": "Gialli medi dell'arbitro",
}
REFEREE_PRIOR_MATCHES = 10  # stesso shrinkage della fase D (datasources/stats.py)
CONFIDENCE = ("bassa", "media", "alta")
_URL = re.compile(r"https?://\S+", re.I)

RESPONSE_FORMAT = f"""{HEADER}
gol_casa: 0.95 | motivo: <perché> | fonte: https://...
gol_ospite: 1.05 | motivo: <perché> | fonte: https://...
corner: 1.00 | motivo: <perché> | fonte: https://...
cartellini: 1.10 | motivo: <perché> | fonte: https://...
arbitro_gialli_medi: 4.6 | partite: 23 | fonte: https://...
confidenza: media
commento: <una o due frasi>"""


# --- Testo per l'analisi -----------------------------------------------------------------------

def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.1f}%"


def probability_lines(result: Mapping[str, Any]) -> list[str]:
    """Probabilità principali del simulatore in righe leggibili."""
    markets = result["markets"]
    final = (result.get("components") or {}).get("finale") or {}
    lines = [
        "1X2: " + " | ".join(f"{key} {_pct(markets['1x2'][key]['percentage'])}" for key in ("1", "X", "2")),
        "Over/Under: " + " | ".join(f"Over {line} {_pct(markets['over_under'][f'Over_{line}']['percentage'])}"
                                    for line in (1.5, 2.5, 3.5)),
        f"GG: {_pct(markets['goal_no_goal']['Goal']['percentage'])} | NG: {_pct(markets['goal_no_goal']['No_Goal']['percentage'])}",
        "Multigol: " + " | ".join(f"{key} {_pct(markets['multigol_complete'][key]['percentage'])}"
                                  for key in ("1-2", "1-3", "2-3", "2-4", "3-5") if key in markets["multigol_complete"]),
        "Primo tempo: " + " | ".join(f"{key} 1T {_pct(markets['first_half_1x2'][key]['percentage'])}" for key in ("1", "X", "2"))
        + f" | Over 0.5 1T {_pct(final.get('Over 0.5 gol 1T'))} | Over 1.5 1T {_pct(final.get('Over 1.5 gol 1T'))}",
        f"Corner: media {markets['corners']['mean']:.2f} | "
        + " | ".join(f"Over {line} {_pct(markets['corners'][f'Over_{line}']['percentage'])}" for line in ("8.5", "9.5", "10.5")),
        f"Cartellini (punti: {result['model']['card_rule']}): media {markets['cards']['mean']:.2f} | "
        + " | ".join(f"Over {line} {_pct(markets['cards'][f'Over_{line}']['percentage'])}" for line in ("3.5", "4.5", "5.5")),
    ]
    model = result["model"]
    anchoring = result.get("market_anchoring") or {}
    goals = [f"modello λ {model['lambda_modello']:.2f} / μ {model['mu_modello']:.2f}"]
    if anchoring.get("active"):
        goals.append(f"mercato λ {anchoring['market_lambda']:.2f} / μ {anchoring['market_mu']:.2f}")
    goals.append(f"finali λ {model['lambda']:.2f} / μ {model['mu']:.2f}")
    lines.append("Gol attesi: " + " · ".join(goals))
    return lines


def analysis_prompt(block: str, result: Mapping[str, Any], *, sources: list[dict] | None = None,
                    match_date: str | None = None, competition: str | None = None, extra: Sequence[str] = ()) -> str:
    """Testo completo da incollare in Claude per la verifica della partita."""
    home, away = result["input"]["home"]["name"], result["input"]["away"]["name"]
    header = f"Partita: {home} - {away}" + (f" ({competition})" if competition else "") + (f", {match_date}" if match_date else "")
    source_lines = [
        f"- {row['Soggetto']} · {row['Campo']}: {row['Valore'] or 'MANCANTE'} — {row['Fonte']} "
        f"(agg. {row['Aggiornato']}, ultima partita {row['Ultima partita inclusa']})"
        for row in (sources or []) if not str(row.get("Campo", "")).startswith("(info)")
    ]
    return "\n".join([
        "Sei un analista di calcio. Verifica sul web i fatti di questa partita e confrontali con gli input del mio simulatore.",
        "",
        header,
        "",
        "COSA VERIFICARE (cita sempre la fonte con un link):",
        "1. Formazioni probabili o ufficiali; assenze per infortunio e squalifiche, soprattutto di titolari e portieri.",
        "2. Turnover probabile per impegni ravvicinati (coppe, partite a 3 giorni di distanza).",
        "3. Arbitro designato e sue medie di gialli e falli per partita, separatamente in campionato e nelle coppe "
        "europee, con il numero di partite.",
        "4. Motivazioni (classifica, derby, qualificazione già ottenuta o da conquistare) e meteo previsto.",
        "5. Incoerenze tra questi fatti e gli input qui sotto: forma o Elo non aggiornati, dati di un'altra stagione o "
        "competizione, valori fuori scala.",
        "",
        "INPUT DEL SIMULATORE (blocco del parser; le righe # indicano fonte e data):",
        "```",
        block.strip(),
        "```",
        *(["", "FONTI E DATE DEI VALORI:", *source_lines] if source_lines else []),
        "",
        "PROBABILITÀ DEL SIMULATORE:",
        *[f"- {line}" for line in probability_lines(result)],
        "",
        *extra,
        "COME RISPONDERE:",
        "Scrivi prima un breve commento in italiano (al massimo 5 righe), poi SOLO un blocco in questo formato, "
        "senza altro testo dopo:",
        "",
        RESPONSE_FORMAT,
        "",
        "Regole del blocco:",
        "- gol_casa, gol_ospite, corner e cartellini sono fattori moltiplicativi (1.00 = nessuna modifica). "
        "Limiti applicati dall'app: gol e corner 0.90-1.10, cartellini 0.85-1.15. Il fattore cartellini si applica "
        "ai gialli attesi e, nella stessa proporzione, ai rossi attesi.",
        "- Ogni correzione diversa da 1.00 deve avere una fonte con link (https://...): senza fonte viene ignorata.",
        "- Usa arbitro_gialli_medi solo se hai trovato la media dell'arbitro designato, con il numero di partite.",
        "- Ometti le righe per cui non hai informazioni affidabili. confidenza: bassa, media o alta.",
    ])


# --- Lettura della risposta --------------------------------------------------------------------

@dataclass
class Correction:
    key: str
    proposed: float
    applied: float | None
    reason: str = ""
    source: str | None = None
    matches: int | None = None
    note: str = ""

    @property
    def accepted(self) -> bool:
        return self.applied is not None


@dataclass
class ClaudeResponse:
    corrections: dict[str, Correction] = field(default_factory=dict)
    confidence: str | None = None
    comment: str = ""
    preamble: str = ""
    warnings: list[str] = field(default_factory=list)

    def adjustment(self) -> ClaudeAdjustment | None:
        """Fattori accettati per il motore; ``None`` se non c'è nulla da applicare."""
        values = {key: self.corrections[key].applied for key in BOUNDS
                  if key in self.corrections and self.corrections[key].accepted}
        if all(abs(value - 1.0) < 1e-9 for value in values.values()):
            return None
        return ClaudeAdjustment(goals_home=values.get("gol_casa", 1.0), goals_away=values.get("gol_ospite", 1.0),
                                corners=values.get("corner", 1.0), cards=values.get("cartellini", 1.0))

    def referee_yellow(self, current: float, competition_mean: float | None = None) -> float | None:
        """Media gialli dell'arbitro con lo shrinkage della fase D; ``None`` se non accettata."""
        correction = self.corrections.get("arbitro_gialli_medi")
        if correction is None or not correction.accepted:
            return None
        prior = competition_mean if competition_mean is not None else current
        count = correction.matches or 0
        return (count * correction.proposed + REFEREE_PRIOR_MATCHES * prior) / (count + REFEREE_PRIOR_MATCHES)


class ResponseError(ValueError):
    """La risposta incollata non contiene un blocco leggibile."""


def _number(text: str) -> float:
    match = re.search(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not match:
        raise ValueError(text)
    return float(match.group(0).replace(",", "."))


def parse_response(text: str) -> ClaudeResponse:
    """Legge il blocco ``CORREZIONI_CLAUDE:``; tollera spazi, maiuscole, virgole decimali e markdown."""
    position = text.upper().find(HEADER)
    if position < 0:
        raise ResponseError(f"Nella risposta non c'è il blocco «{HEADER}»: chiedi a Claude di rispondere nel formato indicato.")
    response = ClaudeResponse(preamble=text[:position].strip().strip("`").strip())
    seen: set[str] = set()
    for raw_line in text[position + len(HEADER):].splitlines():
        line = raw_line.strip().strip("`*-").strip()
        if line.upper().startswith("CHIAVI_MATCH"):
            break  # chiavi del match (match_keys.py): informative, lette a parte
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        key, _, value = parts[0].partition(":")
        key = key.strip().lower().replace(" ", "_")
        value = value.strip()
        attributes = {}
        for part in parts[1:]:
            name, _, content = part.partition(":")
            attributes[name.strip().lower()] = content.strip()
        if key == "confidenza":
            response.confidence = value.lower() if value.lower() in CONFIDENCE else None
            if response.confidence is None:
                response.warnings.append(f"Confidenza «{value}» non riconosciuta (attese: bassa, media, alta).")
            continue
        if key == "commento":
            response.comment = value
            continue
        if key not in BOUNDS and key != "arbitro_gialli_medi":
            if ":" in raw_line:
                response.warnings.append(f"Riga ignorata: «{line}».")
            continue
        if key in seen:
            response.warnings.append(f"{key} ripetuto: uso solo la prima riga.")
            continue
        seen.add(key)
        response.corrections[key] = _correction(key, value, attributes)
    if not response.corrections:
        response.warnings.append("Nessuna correzione nel blocco.")
    return response


def _correction(key: str, value: str, attributes: dict[str, str]) -> Correction:
    reason = attributes.get("motivo", "")
    source_match = _URL.search(attributes.get("fonte", ""))
    source = source_match.group(0).rstrip(").,;") if source_match else None
    try:
        proposed = _number(value)
    except ValueError:
        return Correction(key, float("nan"), None, reason, source, note=f"valore «{value}» non numerico: ignorata")
    if key == "arbitro_gialli_medi":
        try:
            matches = int(_number(attributes.get("partite", "")))
        except ValueError:
            matches = None
        if source is None:
            return Correction(key, proposed, None, reason, None, matches, "senza fonte: ignorata")
        if not matches or matches < 1:
            return Correction(key, proposed, None, reason, source, None, "numero di partite mancante: ignorata")
        if not 1.0 <= proposed <= 10.0:
            return Correction(key, proposed, None, reason, source, matches, "media fuori scala (attesa 1-10): ignorata")
        note = "poco affidabile (meno di 10 partite): avvicinata alla media della competizione" if matches < 10 else \
               "avvicinata alla media della competizione con peso 10 partite"
        return Correction(key, proposed, proposed, reason, source, matches, note)
    if proposed <= 0:
        return Correction(key, proposed, None, reason, source, note="fattore non positivo: ignorata")
    if source is None and abs(proposed - 1.0) > 1e-9:
        return Correction(key, proposed, None, reason, None, note="senza fonte: ignorata")
    low, high = BOUNDS[key]
    applied = min(max(proposed, low), high)
    note = f"limitata da {proposed:g} a {applied:g}" if applied != proposed else ""
    return Correction(key, proposed, applied, reason, source, note=note)


def changes_table(response: ClaudeResponse) -> list[dict]:
    rows = []
    for key, correction in response.corrections.items():
        rows.append({
            "Campo": LABELS.get(key, key),
            "Proposto": correction.proposed,
            "Applicato": correction.applied if correction.accepted else None,
            "Partite": correction.matches,
            "Motivo": correction.reason,
            "Fonte": correction.source or "—",
            "Stato": "applicabile" + (f" ({correction.note})" if correction.note else "") if correction.accepted
                     else correction.note,
        })
    return rows


# --- Estrazione dati da un sito -----------------------------------------------------------------

EXTRACTION_PROMPT = """Trasforma il testo grezzo di un sito di statistiche calcistiche (incollato in fondo) in un blocco per il mio simulatore.
Rispondi SOLO con il blocco, senza commenti, esattamente in questo formato:

CASA: <nome squadra di casa>
Attacco: <coeff> | Difesa: <coeff> | Elo: <rating> | Forma: <W-D-L> | xG Fatti: <media> | xG Subiti: <media> | Corner pro/sub: <media>/<media> | Cartellini pro: <media>
# Fonti: <sito e data per ogni valore>

OSPITE: <nome squadra ospite>
Attacco: ... (stessi campi)
# Fonti: ...

ARBITRO: Gialli medi <media gialli per partita> | Falli medi <media falli per partita>

QUOTE_MERCATI_PRINCIPALI:
Quota 1: <quota> | Quota X: <quota> | Quota 2: <quota> | Quota Over 2.5: <quota> | Quota Under 2.5: <quota>

Definizioni (valori per partita, stessa stagione e competizione per entrambe le squadre):
- Attacco = gol fatti medi della squadra / gol medi per squadra della competizione (1.00 = media; 0.2-3.0).
- Difesa = gol medi per squadra della competizione / gol subiti medi della squadra (sopra 1.00 = difesa migliore; 0.2-3.0).
- Elo: rating ClubElo se presente nel testo (800-2400), stessa scala per le due squadre.
- Forma: ultimi 1-5 risultati di campionato dal più vecchio al più recente con W (vittoria), D (pareggio), L (sconfitta).
- xG Fatti/Subiti: expected goals medi per partita (di solito 0.5-3.0, mai totali di stagione).
- Corner pro/sub: corner conquistati/concessi medi per partita della singola squadra (di solito 2-9).
- Cartellini pro: gialli medi ricevuti dalla squadra per partita (rossi esclusi).
- Arbitro: gialli e falli medi TOTALI per partita (di solito 3-6 gialli, 18-30 falli).
- Quote: decimali (es. 1.85). Ometti le righe delle quote che non trovi.
- Se un valore non è nel testo, ometti il campo: NON inventarlo e NON stimarlo.
- Per ogni valore indica nella riga # Fonti il sito e la data.

TESTO DEL SITO:
[INCOLLA QUI IL TESTO COPIATO DAL SITO]
"""


def extraction_prompt(home: str | None = None, away: str | None = None) -> str:
    """Istruzioni per l'estrazione; con le squadre note le indica a Claude."""
    if home and away:
        return f"Partita: {home} (casa) - {away} (ospite).\n" + EXTRACTION_PROMPT
    return EXTRACTION_PROMPT
