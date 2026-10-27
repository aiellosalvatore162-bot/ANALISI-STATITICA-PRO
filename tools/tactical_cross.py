"""Fase Q, punto 5 e 7: regole di incrocio di stile, stima su StatsBomb e verifica con Understat.

1. Stima (StatsBomb Open Data 2015/16, ``python -m tools.style_data``): ogni squadra riceve una scheda dai
   valori medi di stagione senza la partita in esame (transizione = quintile della progressione per passaggio,
   blocco = terzile dell'altezza delle azioni difensive, pressing = terzile delle pressioni per passaggio
   avversario, fasce/cross = terzile dei cross, gestione del blocco basso = terzile degli xG prodotti: proxy).
   Per chi attacca: rapporto osservato/atteso (attacco × difesa avversaria / media) di xG (gol), corner e falli
   (proxy dei cartellini), quando la regola vale diviso lo stesso rapporto quando non vale; errore standard
   bootstrap per partita. Meno di ``MIN_MATCHES`` casi o un campo non misurabile (non possesso a uomo/zona)
   = non stimabile, resta il valore prudente.
2. Verifica (football-data.co.uk + Understat 2019-27, Serie A, Premier, Liga, Bundesliga): schede dalle misure
   Understat della stagione prima della partita (pressing = PPDA, blocco = PPDA e deep concessi, transizione =
   PPDA concesso invertito, gestione = xG prodotti; i cross non ci sono). Gol attesi ancorati alle quote di
   chiusura, fattori dopo l'ancoraggio come nell'app; corner e cartellini dal modello dei conteggi. Ogni regola
   resta accesa solo con la regola severa: log-loss appaiata giù di oltre 2 errori standard ED ECE non peggiore.
   Le stime StatsBomb non usano i dati di verifica, quindi tutte le stagioni sono fuori campione.

Uso: ``python -m tools.tactical_cross [--salva] [--output docs/BASELINE.md]``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

import engine
import tactical_sheets
from tactical_sheets import TacticalSheet, _applies
from tools import baseline
from tools.minute_data import CACHE

MIN_MATCHES = 40
BOOTSTRAP = 300
UNDERSTAT_CODES = {"I1": "Serie_A", "E0": "EPL", "SP1": "La_liga", "D1": "Bundesliga"}
MEASURABLE = {"transizione", "blocco", "pressing", "fasce_cross", "gestione_blocco_basso"}
VERIFIABLE = {"transizione", "blocco", "pressing", "gestione_blocco_basso"}
GOAL_LINES_ECE = ("Over 2.5",)


def _bins(values: pd.Series, labels) -> pd.Series:
    """Quantili di ``values`` (per lega-stagione) nelle etichette date, dal più basso."""
    ranks = values.rank(pct=True)
    edges = np.linspace(0, 1, len(labels) + 1)[1:-1]
    return ranks.apply(lambda rank: labels[int(np.searchsorted(edges, rank))] if pd.notna(rank) else None)


def _sheet(row) -> TacticalSheet:
    return TacticalSheet(team=str(row["team"]), transizione=None if pd.isna(row.get("transizione")) else int(row["transizione"]),
                         blocco=row.get("blocco"), pressing=row.get("pressing"), fasce_cross=row.get("fasce_cross"),
                         gestione_blocco_basso=row.get("gestione_blocco_basso"))


# --- 1. Stima su StatsBomb -------------------------------------------------------------------------------------

def statsbomb_rows(path: Path = CACHE / "stili_statsbomb.json.gz") -> pd.DataFrame:
    rows = pd.DataFrame(json.load(gzip.open(path, "rt", encoding="utf-8")))
    sums = rows.groupby(["season", "team"])[["passes", "progress", "def_x", "def_n", "pressures", "crosses", "xg",
                                             "corners", "fouls", "opp_passes"]].transform("sum")
    counts = rows.groupby(["season", "team"])["match"].transform("count")
    loo = (sums - rows[sums.columns]).div((counts - 1).replace(0, np.nan), axis=0)  # medie senza la partita
    rows["vert"] = loo["progress"] / loo["passes"]
    rows["height"] = loo["def_x"] / loo["def_n"]
    rows["press"] = loo["pressures"] / loo["opp_passes"]
    rows["cross_avg"], rows["xg_avg"], rows["corner_avg"], rows["foul_avg"] = loo["crosses"], loo["xg"], loo["corners"], loo["fouls"]
    against = rows[["match", "team", "xg", "corners"]].rename(columns={"team": "opponent", "xg": "xg_against",
                                                                       "corners": "corners_against"})
    rows = rows.merge(against, on=["match", "opponent"])
    conceded = rows.groupby(["season", "team"])[["xg_against", "corners_against"]].transform("sum")
    rows["xga_avg"] = (conceded["xg_against"] - rows["xg_against"]) / (counts - 1).replace(0, np.nan)
    rows["ca_avg"] = (conceded["corners_against"] - rows["corners_against"]) / (counts - 1).replace(0, np.nan)
    seasons = rows.groupby("season")
    rows["transizione"] = seasons["vert"].transform(lambda values: _bins(values, (1, 2, 3, 4, 5)))
    rows["blocco"] = seasons["height"].transform(lambda values: _bins(values, ("basso", "medio", "alto")))
    rows["pressing"] = seasons["press"].transform(lambda values: _bins(values, ("basso", "medio", "alto")))
    rows["fasce_cross"] = seasons["cross_avg"].transform(lambda values: _bins(values, ("basso", "medio", "alto")))
    rows["gestione_blocco_basso"] = seasons["xg_avg"].transform(lambda values: _bins(values, ("scarsa", "media", "buona")))
    return rows[rows["season"] != "9_27"].dropna(subset=["vert", "xga_avg"])  # Bundesliga: solo un club nei dati aperti


def _pairs(rows: pd.DataFrame) -> pd.DataFrame:
    """Una riga per squadra che attacca con la riga dell'avversario (suffisso _d)."""
    return rows.merge(rows, left_on=["match", "opponent"], right_on=["match", "team"], suffixes=("", "_d"))


def estimate(rows: pd.DataFrame, rules: list[dict], seed: int = 7) -> dict[str, dict]:
    pairs = _pairs(rows)
    league = pairs.groupby("season")[["xg", "corners"]].transform("mean")
    expected = {"gol": pairs["xg_avg"] * pairs["xga_avg_d"] / league["xg"],
                "corner": pairs["corner_avg"] * pairs["ca_avg_d"] / league["corners"],
                "cartellini": pairs["foul_avg"] + pairs["foul_avg_d"]}
    observed = {"gol": pairs["xg"], "corner": pairs["corners"], "cartellini": pairs["fouls"] + pairs["fouls_d"]}
    attack = [_sheet(row) for row in pairs[["team", "transizione", "blocco", "pressing", "fasce_cross", "gestione_blocco_basso"]]
              .to_dict("records")]
    defence = [_sheet({key.removesuffix("_d"): value for key, value in row.items()}) for row in
               pairs[["team_d", "transizione_d", "blocco_d", "pressing_d", "fasce_cross_d", "gestione_blocco_basso_d"]]
               .to_dict("records")]
    rng = np.random.default_rng(seed)
    codes, unique = pd.factorize(pairs["match"])
    draws_weights = [np.bincount(rng.integers(0, len(unique), len(unique)), minlength=len(unique))[codes]
                     for _ in range(BOOTSTRAP)]  # bootstrap per partita, gli stessi ricampionamenti per ogni regola
    result = {}
    for rule in rules:
        fields = set(rule["condizione"].get("attacco", {})) | set(rule["condizione"].get("difesa", {}))
        if not fields <= MEASURABLE:
            result[rule["id"]] = {"stimabile": False, "motivo": "campo non misurabile nei dati: "
                                  + ", ".join(sorted(fields - MEASURABLE)), "partite": 0}
            continue
        mask = np.array([_applies(rule, a, d) for a, d in zip(attack, defence)])
        if mask.sum() < MIN_MATCHES:
            result[rule["id"]] = {"stimabile": False, "motivo": f"solo {int(mask.sum())} casi (servono {MIN_MATCHES})",
                                  "partite": int(mask.sum())}
            continue
        effects, errors = {}, {}
        for key in rule["effetto"]:
            obs, exp = observed[key].to_numpy(float), expected[key].to_numpy(float)
            valid = np.isfinite(exp) & (exp > 0) & np.isfinite(obs)
            inside, outside = mask & valid, ~mask & valid

            def ratio(weights: np.ndarray) -> float:
                return ((weights * obs)[inside].sum() / (weights * exp)[inside].sum()) / \
                    ((weights * obs)[outside].sum() / (weights * exp)[outside].sum())

            effects[key] = float(ratio(np.ones(len(obs))))
            errors[key] = float(np.std([ratio(weights) for weights in draws_weights], ddof=1))
        result[rule["id"]] = {"stimabile": True, "partite": int(mask.sum()), "effetto": effects, "errore": errors}
    return result


# --- 2. Verifica con Understat + football-data ----------------------------------------------------------------

def understat_profiles(cache=None, seasons=range(2019, 2027)) -> pd.DataFrame:
    """Schede per squadra e data dalle misure Understat della stagione precedenti la partita (almeno 5 gare)."""
    from datasources.cache import SourceCache
    from datasources.sources import Understat

    understat = Understat(cache or SourceCache())
    frames = []
    for league, code in UNDERSTAT_CODES.items():
        for year in seasons:
            frame = understat.league(code, year, timedelta(days=1) if year == max(seasons) else timedelta(days=365)).data
            if frame.empty:
                continue
            frame = frame.sort_values(["team", "date"]).copy()
            frame["league"], frame["year"] = league, year
            grouped = frame.groupby("team")
            for column in ("ppda", "ppda_allowed", "deep_allowed", "xg_for"):
                clean = frame[column].replace([np.inf, -np.inf], np.nan)
                frame[f"{column}_prior"] = clean.groupby(frame["team"]).transform(lambda values: values.shift().expanding().mean())
            frame["played"] = grouped.cumcount()
            frames.append(frame)
    rows = pd.concat(frames, ignore_index=True)
    rows = rows[rows["played"] >= 5].copy()
    rows["press"] = -np.log(rows["ppda_prior"])
    rows["build"] = np.log(rows["ppda_allowed_prior"])

    def z(values: pd.Series) -> pd.Series:
        return (values - values.mean()) / values.std(ddof=0)

    by_season = rows.groupby(["league", "year"])
    rows["height"] = (by_season["press"].transform(z) - by_season["deep_allowed_prior"].transform(z)) / 2
    rows["transizione"] = by_season["build"].transform(lambda values: _bins(-values, (1, 2, 3, 4, 5)))
    rows["blocco"] = by_season["height"].transform(lambda values: _bins(values, ("basso", "medio", "alto")))
    rows["pressing"] = by_season["press"].transform(lambda values: _bins(values, ("basso", "medio", "alto")))
    rows["gestione_blocco_basso"] = by_season["xg_for_prior"].transform(lambda values: _bins(values, ("scarsa", "media", "buona")))
    return rows[["league", "team", "date", "transizione", "blocco", "pressing", "gestione_blocco_basso"]]


def attach_sheets(features: pd.DataFrame, profiles: pd.DataFrame) -> tuple[list, list]:
    from datasources.names import match_team

    lookup = {(league, team, day): row for (league, team, day), row in
              profiles.set_index(["league", "team", "date"]).to_dict("index").items()}
    names: dict[tuple[str, str], str | None] = {}
    homes, aways = [], []
    for row in features.itertuples():
        day = pd.Timestamp(row.date).normalize()
        sides = []
        for team in (row.home_team, row.away_team):
            key = (row.league, team)
            if key not in names:
                candidates = profiles.loc[profiles["league"] == row.league, "team"].unique()
                names[key] = match_team(team, list(candidates))
            found = lookup.get((row.league, names[key], day)) if names[key] else None
            sides.append(_sheet({"team": team, **found}) if found else None)
        homes.append(sides[0])
        aways.append(sides[1])
    return homes, aways


def _settings_with(rule_ids: set[str], rules: list[dict], base: dict) -> dict:
    settings = deepcopy(base)
    settings["regole"] = [dict(rule, attiva=rule["id"] in rule_ids) for rule in rules]
    return settings


def verify(features: pd.DataFrame, rates: pd.DataFrame, homes: list, aways: list, rules: list[dict], base: dict) -> dict:
    from tools.calibrate import count_logpmf, count_means, count_sf

    model = engine.DEFAULT_COUNT_MODEL
    means = count_means(model, features)
    corner_shape = model.corner_dispersion if model.active else 0.0
    card_shape = model.card_dispersion if model.active else 0.0
    home_goals, away_goals = features["home_goals"].to_numpy(int), features["away_goals"].to_numpy(int)
    result_1x2 = np.select([home_goals > away_goals, home_goals == away_goals], [0, 1], 2)
    over = (home_goals + away_goals > 2).astype(int)
    corners = (features["home_corners"] + features["away_corners"]).to_numpy(int)
    cards = (features["home_yellows"] + features["away_yellows"]).to_numpy(int)
    lam, mu, rho = rates["lambda"].to_numpy(), rates["mu"].to_numpy(), rates["rho"].to_numpy()

    def goal_probabilities(factor_home, factor_away) -> tuple[np.ndarray, np.ndarray]:
        probabilities, overs = np.zeros((len(lam), 3)), np.zeros(len(lam))
        for index in range(len(lam)):
            matrix = engine.dixon_coles_matrix(lam[index] * factor_home[index], mu[index] * factor_away[index], rho[index], max_goals=10)
            home, away = np.indices(matrix.shape)
            probabilities[index] = (matrix[home > away].sum(), np.trace(matrix), matrix[home < away].sum())
            overs[index] = matrix[home + away > 2].sum()
        return probabilities / probabilities.sum(axis=1, keepdims=True), overs

    def losses(factors: dict[str, np.ndarray]) -> dict[str, tuple[np.ndarray, float]]:
        probabilities, overs = goal_probabilities(factors["gol_casa"], factors["gol_ospite"])
        goal_loss = (-np.log(np.clip(probabilities[np.arange(len(result_1x2)), result_1x2], 1e-12, 1))
                     - np.log(np.clip(np.where(over == 1, overs, 1 - overs), 1e-12, 1))) / 2
        goal_ece = (baseline.expected_calibration_error(probabilities, result_1x2)
                    + baseline.expected_calibration_error(baseline.binary(overs), over)) / 2
        corner_mean = (means["corner_home"] + means["corner_away"]) * factors["corner"]
        card_mean = means["cards"] * factors["cartellini"]
        corner_over = count_sf(9.5, corner_mean, corner_shape)
        card_over = count_sf(4.5, card_mean, card_shape)
        return {"gol": (goal_loss, goal_ece),
                "corner": (-count_logpmf(corners, corner_mean, corner_shape),
                           baseline.expected_calibration_error(baseline.binary(corner_over), (corners > 9.5).astype(int))),
                "cartellini": (-count_logpmf(cards, card_mean, card_shape),
                               baseline.expected_calibration_error(baseline.binary(card_over), (cards > 4.5).astype(int)))}

    neutral = {key: np.ones(len(features)) for key in ("gol_casa", "gol_ospite", "corner", "cartellini")}
    before = losses(neutral)
    report = {"partite": len(features), "con_schede": int(sum(h is not None and a is not None for h, a in zip(homes, aways))),
              "regole": {}}
    for rule in rules:
        fields = set(rule["condizione"].get("attacco", {})) | set(rule["condizione"].get("difesa", {}))
        if not fields <= VERIFIABLE:
            report["regole"][rule["id"]] = {"verificabile": False,
                                            "motivo": "manca nei dati Understat: " + ", ".join(sorted(fields - VERIFIABLE))}
            continue
        settings = _settings_with({rule["id"]}, rules, base)
        factors = {key: np.ones(len(features)) for key in neutral}
        applied = 0
        for index, (home, away) in enumerate(zip(homes, aways)):
            values, notes = tactical_sheets.crossing_adjustment(home, away, settings=settings)
            applied += bool(notes)
            for key, value in values.items():
                factors[key][index] = value
        after = losses(factors)
        rows = {}
        for key in rule["effetto"]:
            difference = after[key][0] - before[key][0]
            touched = difference != 0
            standard_error = float(difference.std(ddof=1) / np.sqrt(len(difference)))
            rows[key] = {"prima": float(before[key][0].mean()), "dopo": float(after[key][0].mean()),
                         "differenza": float(difference.mean()), "due_es": 2 * standard_error,
                         "ece_prima": before[key][1], "ece_dopo": after[key][1], "toccate": int(touched.sum())}
        keep = applied > 0 and all(row["differenza"] < -row["due_es"] and row["ece_dopo"] <= row["ece_prima"] + 0.0005
                                   for row in rows.values())
        report["regole"][rule["id"]] = {"verificabile": True, "partite_con_regola": applied, "mercati": rows, "tenuta": keep}
    return report


def run(limit: int | None = None) -> tuple[dict, dict, dict]:
    settings = tactical_sheets.load_rules()
    rules = settings["regole"]
    estimates = estimate(statsbomb_rows(), rules)
    # Le regole stimabili usano la stima (nei limiti), le altre il valore prudente.
    for rule in rules:
        found = estimates[rule["id"]]
        if found.get("stimabile"):
            low, high = settings["limiti"]
            rule["effetto"] = {key: round(float(np.clip(value, low, high)), 3) for key, value in found["effetto"].items()}
            rule["valore_da"] = "stimato su StatsBomb Open Data 2015/16"
        else:
            rule["valore_da"] = "prudente (" + found["motivo"] + ")"
    from tools.goleade import rates as goal_rates

    features = baseline.load_usable_features()
    features = features[features["league"].isin(UNDERSTAT_CODES)].dropna(
        subset=["close_home", "close_draw", "close_away", "home_corners", "away_corners", "home_yellows", "away_yellows",
                "referee_yellow_avg", "referee_fouls_avg"])
    if limit:
        features = features.tail(limit)
    features = features.reset_index(drop=True)
    homes, aways = attach_sheets(features, understat_profiles())
    report = verify(features, goal_rates(features), homes, aways, rules, settings)
    return settings, estimates, report


def render(settings: dict, estimates: dict, report: dict) -> str:
    lines = ["## Incroci di stile delle schede tattiche (fase Q, punti 5 e 7)", "",
             f"Generato il {date.today():%d/%m/%Y} con `python -m tools.tactical_cross`. Stima su StatsBomb Open Data "
             "2015/16 (Premier, Liga, Serie A, Ligue 1; schede dai valori di stagione senza la partita; cartellini "
             "misurati con i falli), verifica su football-data.co.uk + Understat 2019-27 "
             f"({report['partite']} partite, {report['con_schede']} con le schede di entrambe le squadre). Fattori dopo "
             "l'ancoraggio alle quote di chiusura; regola severa: log-loss appaiata giù di oltre 2 errori standard ED "
             "ECE non peggiore.", "",
             "| Regola | Casi StatsBomb | Effetto stimato (± e.s.) | Valore usato | Verifica | Esito |", "|---|---|---|---|---|---|"]
    for rule in settings["regole"]:
        found, checked = estimates[rule["id"]], report["regole"][rule["id"]]
        estimate_text = (", ".join(f"{key} {value:.3f} ± {found['errore'][key]:.3f}" for key, value in found["effetto"].items())
                         if found.get("stimabile") else f"non stimabile: {found['motivo']}")
        used = ", ".join(f"{key} {value}" for key, value in rule["effetto"].items())
        if checked.get("verificabile"):
            check = "; ".join(f"{key}: {row['prima']:.4f} → {row['dopo']:.4f} ({row['differenza']:+.5f} ± {row['due_es']:.5f}), "
                              f"ECE {row['ece_prima']:.4f} → {row['ece_dopo']:.4f}" for key, row in checked["mercati"].items())
            check = f"{checked['partite_con_regola']} partite; {check}"
            verdict = "accesa" if checked["tenuta"] else "spenta"
        else:
            check, verdict = f"non verificabile: {checked['motivo']}", "spenta"
        lines.append(f"| {rule['nome']} | {found.get('partite', 0)} | {estimate_text} | {used} ({rule['valore_da']}) | "
                     f"{check} | **{verdict}** |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--salva", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    settings, estimates, report = run(args.limit)
    for rule in settings["regole"]:
        checked = report["regole"][rule["id"]]
        rule["attiva"] = bool(checked.get("tenuta"))
        rule["verifica"] = {"data": date.today().isoformat(), "verificabile": bool(checked.get("verificabile")),
                            **({"partite": checked["partite_con_regola"],
                                "mercati": {key: {name: round(value, 6) for name, value in row.items()}
                                            for key, row in checked["mercati"].items()}}
                               if checked.get("verificabile") else {"motivo": checked["motivo"]})}
    markdown = render(settings, estimates, report)
    print(markdown)
    if args.output:
        with args.output.open("a", encoding="utf-8") as handle:
            handle.write(markdown + "\n")
    if args.salva:
        tactical_sheets.CONFIG_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
