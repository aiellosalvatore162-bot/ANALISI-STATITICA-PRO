"""Contesto della partita per il motore (fase AH): stile misurato, profilo dell'Analista, assenti, riposo, turnover, correzioni.

``match_context(...)`` raccoglie per ogni squadra, in un solo dict documentato, tutto ciò che il report e i dati dicono:

(a) stile numerico dalla Fase AD (``style_profile.get_style_params``) con campione e fonte;
(b) profilo tattico dell'Analista tradotto in parametri: transizione, blocco, pressing, non_possesso, fasce_cross entrano come
    PRIOR dei numeri misurati (valore = w·dato + (1−w)·prior, w = n/(n+k), prior = mediana per categoria in
    ``config/stile_prior.json``, mai inventato; senza prior vale il dato, senza dati la media del campionato);
    adattabilità = attenuazione degli incroci + verso quale profilo (contro_forti/contro_deboli) in base all'Elo avversario;
    reazioni se_in_svantaggio/se_in_vantaggio = regole di stato per la AK; cambio allenatore = peso ridotto delle gare precedenti;
(c) assenti pesati (con la Fase AL: un assente noto a Understat conta una volta sola), riposo (solo se manca il calendario),
    turnover (riduce la forza della formazione attesa);
(d) CORREZIONI_CLAUDE come oggi (applicate dopo l'ancoraggio, limiti e fonti della fase G).

Precedenza: dato misurato > report > stima dichiarata. ``FIELD_STATUS`` elenca ogni campo del report: assorbito dal motore (e come)
oppure «solo informativo». Il report è facoltativo: senza report si ottiene lo stesso dict con le sole parti misurate.
"""

from __future__ import annotations

from dataclasses import fields
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import tactical_sheets as ts

PRIOR_PATH = Path(__file__).resolve().parent / "config" / "stile_prior.json"
ABSORBED, INFORMATIVE = "assorbito", "solo informativo"

# Ogni campo che l'Analista può scrivere: assorbito (parametro del motore) o solo informativo. Un test verifica la copertura.
FIELD_STATUS: dict[str, tuple[str, str]] = {
    # profilo tattico (PROFILO_TATTICO)
    "transizione": (ABSORBED, "prior di «deep» (verticalità)"),
    "gestione_blocco_basso": (ABSORBED, "condizione delle regole di incrocio (config/tattica.json)"),
    "non_possesso": (ABSORBED, "prior di «quota_tiri» + condizione degli incroci"),
    "blocco": (ABSORBED, "prior di «deep_concessi» (altezza del blocco) + condizione degli incroci"),
    "pressing": (ABSORBED, "prior di «ppda»"),
    "fasce_cross": (ABSORBED, "prior di «corner_per_tiro»"),
    "adattabilita": (ABSORBED, "attenuazione degli incroci (ADAPTABILITY) e verso quale profilo si sposta"),
    "se_in_svantaggio": (ABSORBED, "regola di stato per la AK (reaction_factors)"),
    "se_in_vantaggio": (ABSORBED, "regola di stato per la AK (reaction_factors)"),
    "dal": (ABSORBED, "cambio allenatore: gare precedenti con peso ridotto (CoachChange)"),
    "allenatore": (INFORMATIVE, "nome, nessun parametro"),
    "precedente": (INFORMATIVE, "testo libero"), "modulo": (INFORMATIVE, "testo libero"),
    "alternativo": (INFORMATIVE, "testo libero"), "contro_forti": (INFORMATIVE, "testo libero (mostrato quando l'Elo avversario è più alto)"),
    "contro_deboli": (INFORMATIVE, "testo libero (mostrato quando l'Elo avversario è più basso)"),
    "note": (INFORMATIVE, "testo libero"), "fonti": (INFORMATIVE, "provenienza, mostrata in scheda"),
    "confidenza": (INFORMATIVE, "mostrata in scheda"), "origine": (INFORMATIVE, "provenienza"), "aggiornata": (INFORMATIVE, "data"),
    "team": (INFORMATIVE, "chiave della scheda"),
    # blocco PARTITA
    "ASSENTI_PESATI": (ABSORBED, "peso sulla produzione offensiva solo dove Understat manca (lineup.assenti_esterni)"),
    "RIPOSO": (ABSORBED, "giorni di riposo, solo se manca il calendario (MatchConfig.rest_days)"),
    "TURNOVER": (ABSORBED, "riduce la forza della formazione attesa (lineup.turnover)"),
    "CORREZIONI_CLAUDE": (ABSORBED, "fattori gol/corner/cartellini dopo l'ancoraggio, con limiti e fonti"),
    "assenti_casa/ospite": (ABSORBED, "assenti pesati dell'AL (Understat)"),
    "formazione_casa/ospite": (ABSORBED, "XI atteso dell'AL"),
    "CHIAVI_MATCH": (INFORMATIVE, "chiavi del match, mai nel motore"),
    "FORMA": (INFORMATIVE, "forma scritta dall'Analista, mai nel motore (vale la forma reale misurata dalla AD)"),
}
PROFILE_FIELDS = tuple(item.name for item in fields(ts.TacticalSheet))


def load_prior(path: Path = PRIOR_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def blend(value: float | None, n: int, prior: float | None, k: float) -> tuple[float | None, float, str]:
    """(valore, peso del dato, origine): w·dato + (1−w)·prior con w = n/(n+k). Senza prior vale il dato."""
    if value is None:
        return (prior, 0.0, "solo prior del profilo") if prior is not None else (None, 0.0, "nessun numero")
    weight = n / (n + k) if n + k > 0 else 0.0
    if prior is None:
        return value, weight, "dato misurato (nessun prior stimato per questa categoria)"
    return weight * value + (1.0 - weight) * prior, weight, f"dato {weight:.0%} + prior del profilo {1 - weight:.0%}"


def profile_parameters(sheet: ts.TacticalSheet | None, params: Mapping[str, Mapping[str, Any]] | None,
                       prior: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Profilo qualitativo → parametri numerici (prior + dato)."""
    rows = []
    if sheet is None:
        return rows
    for name, spec in prior["mappa"].items():
        category = getattr(sheet, name, None)
        if category is None:
            continue
        category = str(category)
        data = (params or {}).get(spec["parametro"]) or {}
        value, n = data.get("valore"), int(data.get("campione") or 0)
        prior_value = (prior["prior"].get(name) or {}).get(category)
        blended, weight, origin = blend(value, n, prior_value, float(prior["k_dati"]))
        rows.append({"campo": name, "categoria": category, "parametro": spec["parametro"], "descrizione": spec["descrizione"],
                     "dato": value, "campione": n, "prior": prior_value, "peso_dati": round(weight, 3), "valore": blended,
                     "origine": origin, "fonte_dato": data.get("fonte", "nessun dato misurato"),
                     "fonte_profilo": ", ".join(sheet.fonti) or sheet.origine})
    return rows


def adaptability(sheet: ts.TacticalSheet | None, own_elo: float | None, other_elo: float | None, prior: Mapping[str, Any]) -> dict[str, Any] | None:
    if sheet is None or sheet.adattabilita is None:
        return None
    toward, text = None, ""
    if own_elo is not None and other_elo is not None and sheet.adattabilita == "alta":
        gap = float(prior["soglia_elo_adattabilita"])
        if other_elo - own_elo >= gap:
            toward, text = "contro_forti", sheet.contro_forti
        elif own_elo - other_elo >= gap:
            toward, text = "contro_deboli", sheet.contro_deboli
    return {"livello": sheet.adattabilita, "attenuazione_incroci": ts.ADAPTABILITY.get(sheet.adattabilita, 1.0),
            "sposta_verso": toward, "testo": text or None,
            "nota": "il testo libero è solo informativo; l'attenuazione degli incroci è numerica"}


def labels(profile: Mapping[str, Any] | None, store, league: str | None, when, prior: Mapping[str, Any]) -> dict[str, str]:
    """Etichette brevi della squadra: forma, territorio, pressing (soglie in ``soglie_etichette``)."""
    if not profile or not profile.get("forma_reale") or profile["forma_reale"].get("valore") is None:
        return {"forma": "n/d", "territorio": "n/d", "pressing": "n/d"}
    thresholds = prior["soglie_etichette"]
    form = profile["forma_reale"]["valore"]
    out = {"forma": "in forma" if form >= thresholds["forma"] else "in calo" if form <= -thresholds["forma"] else "in linea"}
    parameters = profile.get("parametri", {})
    venue = "home" if profile.get("campo") == "home" else "away"
    import pandas as pd
    for label, name, sign, threshold in (("territorio", "quota_tiri", 1, thresholds["territorio"]),
                                          ("pressing", "ppda", -1, thresholds["pressing"])):
        value = (parameters.get(name) or {}).get("valore")
        mean = store.league_stats(profile["campionato"], venue, name, pd.Timestamp(when))[0] if store is not None and profile.get("campionato") else None
        if value is None or mean is None or mean != mean:
            out[label] = "n/d"
        elif label == "territorio":
            out[label] = "domina" if value - mean >= threshold else "subisce" if value - mean <= -threshold else "equilibrata"
        else:
            relative = (value - mean) / mean if mean else 0.0
            out[label] = "pressing alto" if relative <= -threshold else "pressing basso" if relative >= threshold else "pressing medio"
    return out


def match_context(home: str, away: str, when, *, league: str | None = None, style_store=None, player_store=None,
                  sheets: Sequence[Mapping[str, Any]] = (), block=None, response=None,
                  elo: tuple[float | None, float | None] = (None, None), calendar_rest: tuple[int | None, int | None] | None = None,
                  rules: Mapping[str, Any] | None = None, prior: Mapping[str, Any] | None = None, extras: Any = None) -> dict[str, Any]:
    """Contesto completo della partita. Tutto facoltativo: senza stile, giocatori o report restano le parti misurate."""
    import lineup as lineup_module
    import style_profile

    prior = prior or load_prior()
    rules = rules or ts.load_rules()
    warnings: list[str] = []
    effects = ts.match_effects(sheets, home, away, rules)
    context: dict[str, Any] = {"casa": {"squadra": home}, "ospite": {"squadra": away}, "avvisi": warnings}
    extras = extras if extras is not None else getattr(block, "extras", None)
    if extras is not None:
        warnings += extras.warnings
    # (a) stile misurato e (b) profilo -> parametri
    for side, team, is_home, sheet, own, other in (("casa", home, True, effects.home, elo[0], elo[1]),
                                                    ("ospite", away, False, effects.away, elo[1], elo[0])):
        style = style_profile.get_style_params(team, when, is_home, style_store, league) if style_store is not None else None
        if style is None:
            warnings.append(f"{team}: stile misurato non disponibile (dati AD mancanti), restano profilo e report.")
        elif style.get("avvisi"):
            warnings += style["avvisi"][:3]
        params = (style or {}).get("parametri")
        context[side].update({
            "stile": style, "profilo": profile_parameters(sheet, params, prior),
            "scheda": ts.sheet_row(sheet) if sheet is not None else None,
            "adattabilita": adaptability(sheet, own, other, prior),
            "reazioni": None if sheet is None else dict(zip(("se_in_svantaggio", "se_in_vantaggio"), ts.reaction_factors(sheet, rules)),
                                                          testo_svantaggio=sheet.se_in_svantaggio, testo_vantaggio=sheet.se_in_vantaggio),
            "cambio_allenatore": None if ts.coach_change(sheet, rules) is None else {
                "dal": sheet.dal, "peso_partite_precedenti": float(rules.get("cambio_allenatore", {}).get("peso_partite_precedenti", 0.3)),
                "partite_per_fidarsi": int(rules.get("cambio_allenatore", {}).get("partite_per_fidarsi", 8))},
            "etichette": labels(style, style_store, league, when, prior)})
    # incroci di stile applicati
    context["incroci"] = {"fattori": effects.factors, "note": list(effects.notes) + list(effects.analyst_notes),
                          "reazioni_stato": {"casa": effects.reactions[:2], "ospite": effects.reactions[2:]}}
    # (c) formazione, assenti pesati, turnover, riposo (con l'AL: un assente noto a Understat conta una volta sola)
    report = lineup_module.report_from_response(response, extras) or {}
    lineup = None
    if player_store is not None:
        try:
            lineup = lineup_module.get_lineup_params(home, away, when, player_store, league=league, report=report or None)
        except Exception as exc:    # le fonti degradano con un avviso
            warnings.append(f"Formazioni non disponibili ({type(exc).__name__}).")
    context["formazione"] = lineup
    rest = {"casa": None, "ospite": None}
    for index, side in enumerate(("casa", "ospite")):
        if calendar_rest and calendar_rest[index] is not None:
            rest[side] = {"giorni": calendar_rest[index], "origine": "calendario"}
        elif extras is not None and side in extras.rest_days:
            rest[side] = {"giorni": extras.rest_days[side], "origine": f"report dell'Analista ({extras.rest_source})"}
    context["riposo"] = rest
    context["turnover"] = {side: (extras.turnover.get(side) if extras else None) for side in ("casa", "ospite")}
    # (d) correzioni di Claude come oggi
    context["correzioni_claude"] = None if response is None else [
        {"chiave": key, "valore": item.applied, "accettata": item.accepted, "nota": item.note} for key, item in response.corrections.items()]
    context["campi"] = {name: {"stato": status, "come": how} for name, (status, how) in FIELD_STATUS.items()}
    context["spiegazioni"] = {"corner": None, "cartellini": None,
                              "nota": "le righe di spiegazione di corner e cartellini si attivano quando la AK è su main"}
    return context


def absorbed_rows(context: Mapping[str, Any]) -> list[dict[str, str]]:
    """Per il riquadro: quali campi del report sono stati assorbiti (parametro e valore) e quali solo informativi."""
    rows = []
    for side in ("casa", "ospite"):
        data = context[side]
        sheet = data.get("scheda") or {}
        for item in data.get("profilo", []):
            value = "n/d" if item["valore"] is None else f"{item['valore']:.3g}"
            rows.append({"Squadra": data["squadra"], "Campo": item["campo"], "Valore nel report": item["categoria"],
                         "Stato": ABSORBED, "Parametro": item["parametro"], "Valore usato": value, "Come": item["origine"]})
        if data.get("adattabilita"):
            rows.append({"Squadra": data["squadra"], "Campo": "adattabilita", "Valore nel report": data["adattabilita"]["livello"],
                         "Stato": ABSORBED, "Parametro": "attenuazione_incroci", "Valore usato": f"{data['adattabilita']['attenuazione_incroci']:g}",
                         "Come": data["adattabilita"]["sposta_verso"] or "nessuno spostamento (Elo simili o adattabilità non alta)"})
        if data.get("reazioni"):
            rows.append({"Squadra": data["squadra"], "Campo": "se_in_svantaggio/se_in_vantaggio", "Valore nel report": "testo",
                         "Stato": ABSORBED, "Parametro": "reazioni (regole di stato)",
                         "Valore usato": f"{data['reazioni']['se_in_svantaggio']:.2f} / {data['reazioni']['se_in_vantaggio']:.2f}",
                         "Come": "per la AK; contano solo col motore a blocchi acceso"})
        if data.get("cambio_allenatore"):
            rows.append({"Squadra": data["squadra"], "Campo": "dal", "Valore nel report": data["cambio_allenatore"]["dal"], "Stato": ABSORBED,
                         "Parametro": "peso gare precedenti", "Valore usato": f"{data['cambio_allenatore']['peso_partite_precedenti']:g}",
                         "Come": f"fino a {data['cambio_allenatore']['partite_per_fidarsi']} gare col nuovo allenatore"})
        for name in ("allenatore", "precedente", "modulo", "alternativo", "contro_forti", "contro_deboli", "note"):
            if sheet.get(name):
                rows.append({"Squadra": data["squadra"], "Campo": name, "Valore nel report": str(sheet[name])[:80], "Stato": INFORMATIVE,
                             "Parametro": "—", "Valore usato": "—", "Come": FIELD_STATUS[name][1]})
    return rows


def dataset_summary(context: Mapping[str, Any], extras: Any = None) -> dict[str, Any]:
    """Voce compatta per il dataset Analista: parametri del profilo (prior/dato/valore), campo e fonte, extras con la fonte."""
    summary: dict[str, Any] = {"profilo": {}, "extras": None}
    for side in ("casa", "ospite"):
        summary["profilo"][side] = [{key: item[key] for key in ("campo", "categoria", "parametro", "dato", "campione", "prior", "peso_dati",
                                                               "valore", "fonte_profilo")} for item in context[side].get("profilo", [])]
    if extras:
        summary["extras"] = {"assenti_pesati": [vars(item) for item in extras.absent], "riposo": dict(extras.rest_days),
                             "fonte_riposo": extras.rest_source, "turnover": {k: list(v) for k, v in extras.turnover.items()}}
    return summary
