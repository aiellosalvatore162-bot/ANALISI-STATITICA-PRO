"""Raccolta delle quote da The Odds API a due livelli (fase Z), sempre con pre-conto e conferma.

- Livello A, per tutte le partite selezionate: UNA chiamata per campionato con i mercati del campionato (1X2 e
  Over/Under goal: ``h2h``, ``totals``); GG/NG esiste solo per evento (``btts``) e costa 1 credito a partita per
  regione: si aggiunge solo con ``gg_ng_per_evento``.
- Livello B, solo per le «Da giocare»: una chiamata per evento con corner e cartellini totali (e primo tempo se
  acceso). Cartellini per squadra, multigol e risultati esatti non sono offerti dall'API: finiscono nella tabella
  «Quote non raccolte» con il motivo.

Prima di ogni raccolta ``preconto``: crediti stimati (mercati × regioni), residui del mese, tetto del giorno
(``tetto_giornaliero`` o budget mensile / 30). Oltre il tetto o il budget non parte nessuna chiamata. Ogni chiamata
ha un timeout breve e un solo nuovo tentativo; costo stimato e reale (intestazioni) finiscono nella tabella SQLite
``quote_crediti``. «Analizza tutte» non usa mai questo modulo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from typing import Any, Callable, Iterable, Mapping

from quotes.adapters.oddsapi import from_event

LEDGER = """CREATE TABLE IF NOT EXISTS quote_crediti (
    id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, ora TEXT NOT NULL, ambito TEXT NOT NULL,
    livello TEXT NOT NULL, stimati INTEGER NOT NULL, reali INTEGER, esito TEXT NOT NULL)"""


@dataclass
class Call:
    livello: str                 # «A» o «B»
    ambito: str                  # campionato (sport) o partita
    sport: str
    event_id: str | None
    keys: list[str]              # voci dell'archivio coperte
    mercati: list[str]
    stimati: int


@dataclass
class Plan:
    calls: list[Call]
    not_offered: list[dict] = field(default_factory=list)     # partita, livello, mercato, motivo

    @property
    def total(self) -> int:
        return sum(call.stimati for call in self.calls)


def settings_of(api) -> dict:
    return dict(api.settings.get("raccolta") or {})


def _regions(api) -> int:
    return len(str(api.region).split(","))


def plan_level_a(api, entries: Iterable[Mapping]) -> Plan:
    settings = settings_of(api).get("livello_a", {})
    league_markets = list(settings.get("mercati_campionato", ["h2h", "totals"]))
    by_sport: dict[str, list[Mapping]] = {}
    for entry in entries:
        by_sport.setdefault(entry.get("sport") or "", []).append(entry)
    calls = []
    for sport, group in by_sport.items():
        if not sport:
            continue  # partite non arrivate dall'elenco eventi: nessun campionato da chiedere
        calls.append(Call("A", sport, sport, None, [entry["key"] for entry in group], league_markets,
                          len(league_markets) * _regions(api)))
        if settings.get("gg_ng_per_evento"):
            calls += [Call("A", f"{entry['home']} - {entry['away']}", sport, entry["event_id"], [entry["key"]], ["btts"],
                           _regions(api)) for entry in group if entry.get("event_id")]
    plan = Plan(calls)
    if not settings.get("gg_ng_per_evento"):
        plan.not_offered += [{"Partita": f"{entry['home']} - {entry['away']}", "Livello": "A", "Mercato": "GG/NG",
                              "Motivo": "solo per evento (1 credito a partita): spento in config/odds_api.json; incolla da Eurobet"}
                             for entry in entries]
    return plan


def plan_level_b(api, entries: Iterable[Mapping]) -> Plan:
    settings = settings_of(api)
    level = settings.get("livello_b", {})
    markets = list(level.get("mercati_evento", ["alternate_totals_corners", "alternate_totals_cards"]))
    if level.get("primo_tempo"):
        markets += ["h2h_h1", "totals_h1"]
    calls, missing = [], []
    for entry in entries:
        label = f"{entry['home']} - {entry['away']}"
        if not entry.get("event_id") or not entry.get("sport"):
            missing.append({"Partita": label, "Livello": "B", "Mercato": "tutti", "Motivo": "partita senza evento dell'API"})
            continue
        calls.append(Call("B", label, entry["sport"], entry["event_id"], [entry["key"]], markets, len(markets) * _regions(api)))
        missing += [{"Partita": label, "Livello": "B", "Mercato": name, "Motivo": "non offerto da The Odds API: incolla da Eurobet"}
                    for name in settings.get("non_offerti", {})]
        if not level.get("primo_tempo"):
            missing.append({"Partita": label, "Livello": "B", "Mercato": "primo tempo",
                            "Motivo": "spento in config/odds_api.json (+2 crediti a partita)"})
    return Plan(calls, missing)


def daily_cap(api) -> int:
    cap = settings_of(api).get("tetto_giornaliero")
    return int(cap) if cap else int(api.settings.get("budget_mensile", 500)) // 30


def preconto(api, plan: Plan) -> dict[str, Any]:
    """Crediti stimati, residui del mese, tetto e residuo del giorno; ``consentito`` False se si supera qualcosa."""
    usage = api.usage()
    cap = daily_cap(api)
    day_left = max(0, cap - usage["spent_today"])
    allowed = plan.total <= day_left and plan.total <= usage["left"]
    reason = ("" if allowed else
              f"oltre il tetto del giorno ({usage['spent_today']} spesi + {plan.total} > {cap})" if plan.total > day_left else
              f"oltre i crediti residui del mese ({usage['left']})")
    return {"stimati": plan.total, "chiamate": len(plan.calls), "residui_mese": usage["left"], "speso_oggi": usage["spent_today"],
            "tetto_giorno": cap, "residuo_giorno": day_left, "consentito": allowed, "motivo": reason}


def _ledger(api, call: Call, real: int | None, outcome: str) -> None:
    now = api.now().astimezone()
    with api.cache._connect() as connection:
        connection.execute(LEDGER)
        connection.execute("INSERT INTO quote_crediti (data, ora, ambito, livello, stimati, reali, esito) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (now.date().isoformat(), now.strftime("%H:%M:%S"), call.ambito, call.livello, call.stimati, real, outcome))


def ledger_rows(api) -> list[dict]:
    with api.cache._connect() as connection:
        connection.execute(LEDGER)
        rows = connection.execute("SELECT data, ora, ambito, livello, stimati, reali, esito FROM quote_crediti ORDER BY id").fetchall()
    return [dict(zip(("Data", "Ora", "Campionato/partita", "Livello", "Stimati", "Reali", "Esito"), row)) for row in rows]


def _with_retry(function: Callable[[], Any], retries: int) -> Any:
    from datasources.oddsapi import BudgetConfirmationRequired, BudgetExceeded, OddsApiError

    for attempt in range(retries + 1):
        try:
            return function()
        except (BudgetExceeded, BudgetConfirmationRequired):
            raise
        except OddsApiError:
            if attempt == retries:
                raise


def collect(api, plan: Plan, archive: dict, *, confirmed: bool) -> dict[str, Any]:
    """Esegue il piano SOLO se confermato e nel tetto; le quote vanno nell'archivio (conflitti da confermare)."""
    from day_archive import add_quotes

    check = preconto(api, plan)
    if not confirmed or not check["consentito"]:
        return {"eseguite": 0, "reali": 0, "non_raccolte": [], "preconto": check,
                "motivo": "serve la conferma" if not confirmed else check["motivo"]}
    settings = settings_of(api)
    api.timeout = float(settings.get("timeout_s", 8))
    retries = int(settings.get("nuovi_tentativi", 1))
    done, real, failed = 0, 0, []
    for call in plan.calls:
        try:
            if call.event_id is None:
                result = _with_retry(lambda: api.league_odds(call.sport, call.mercati), retries)
                events = {event.get("id"): event for event in result.payload}
            else:
                result = _with_retry(lambda: api.event_odds(call.sport, call.event_id, call.mercati), retries)
                events = {call.event_id: result.payload}
        except Exception as exc:  # rete, timeout, budget: la raccolta continua con le altre chiamate
            _ledger(api, call, None, f"non riuscita: {type(exc).__name__}")
            failed += [{"Partita": archive[key]["home"] + " - " + archive[key]["away"], "Livello": call.livello,
                        "Mercato": ", ".join(call.mercati), "Motivo": str(exc)[:160]} for key in call.keys]
            continue
        done += 1
        real += int(result.cost or 0)
        _ledger(api, call, int(result.cost or 0) if not result.from_cache else 0, "dalla cache" if result.from_cache else "ok")
        fetched = result.fetched_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        for key in call.keys:
            event = events.get(archive[key].get("event_id"))
            if event is None:
                failed.append({"Partita": archive[key]["home"] + " - " + archive[key]["away"], "Livello": call.livello,
                               "Mercato": ", ".join(call.mercati), "Motivo": "partita assente nella risposta (quote non ancora pubblicate)"})
                continue
            add_quotes(archive, key, from_event(event, fetched_at=fetched))
    return {"eseguite": done, "reali": real, "non_raccolte": failed, "preconto": check, "motivo": ""}


def projection(level_a: int, level_b: int, days: int = 30, budget: int = 500) -> dict[str, Any]:
    daily = level_a + level_b
    return {"livello_a": level_a, "livello_b": level_b, "totale_giorno": daily, "giorni": days, "totale_mese": daily * days,
            "budget": budget, "entro_budget": daily * days <= budget}
