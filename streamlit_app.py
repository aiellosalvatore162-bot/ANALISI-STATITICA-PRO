"""Minimal on-demand Streamlit interface."""

import hashlib
from datetime import date

import pandas as pd
import altair as alt
import streamlit as st

from engine import config_from_input, final_goal_rates, simulate_match
from historical import (
    HistoricalDataError,
    fetch_public_match_history,
    load_football_data_uploads,
    predict_historical_match,
    predict_manual_only,
    run_walk_forward,
)
from market_catalog import MARKET_GROUPS, definition_for_event, definitions_for_group
from datasources.builder import plausibility_warnings
from parser import MatchInputError, MatchInput, parse_match_input
from ui_data import (
    render_automatic, render_claude, render_create, render_registry, render_style, render_tactical, show_provenance,
)
from ui_performance import render_performance


EXAMPLE = """CASA: Inter
Attacco: 1.34 | Difesa: 1.25 | Elo: 1835 | Forma: W-W-D-W-W | xG Fatti: 2.15 | xG Subiti: 0.85 | Corner pro/sub: 5.8/4.2 | Cartellini pro: 1.60

OSPITE: Milan
Attacco: 1.22 | Difesa: 1.10 | Elo: 1765 | Forma: W-W-L-D-W | xG Fatti: 1.85 | xG Subiti: 1.10 | Corner pro/sub: 5.1/4.8 | Cartellini pro: 1.85

ARBITRO: Gialli medi 4.5 | Falli medi 24
"""

st.set_page_config(page_title="Simulpro · Analisi on-demand", page_icon="⚽", layout="wide")


@st.cache_data(ttl=24 * 60 * 60, show_spinner=False)
def _cached_automatic_history(home_name: str, away_name: str) -> dict:
    return fetch_public_match_history(home_name, away_name, seasons=7)


def _mark_input_touched() -> None:
    st.session_state["input_touched"] = True


st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&family=Space+Grotesk:wght@500;600;700&display=swap');
    :root {
        --ink: #f0f5fa;
        --muted: #9eb1c2;
        --pitch: #3bd18b;
        --pitch-soft: #123b3b;
        --coral: #ff6e68;
        --yellow: #f4c95d;
        --paper: #071727;
        --surface: #10263a;
        --line: #294258;
    }
    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; letter-spacing: 0; }
    .stApp { background-color: var(--paper); color: var(--ink); background-image: repeating-linear-gradient(90deg, rgba(49,111,135,.045) 0, rgba(49,111,135,.045) 9%, transparent 9%, transparent 18%); }
    [data-testid="stHeader"] { background: rgba(7, 23, 39, .94); }
    [data-testid="stMain"] > div { background-image: linear-gradient(90deg, transparent calc(50% - 1px), rgba(147,185,204,.075) 50%, transparent calc(50% + 1px)); }
    .block-container { max-width: 1600px; padding-top: 1.2rem; padding-bottom: 4rem; }
    h1, h2, h3, [data-testid="stMetricValue"] { font-family: 'Space Grotesk', sans-serif !important; color: var(--ink); letter-spacing: 0 !important; }
    h1 { font-size: 2.15rem !important; line-height: 1.1 !important; margin-bottom: .25rem !important; }
    h2, h3 { line-height: 1.2 !important; }
    p, label, [data-testid="stCaptionContainer"] { color: var(--muted); }
    .brand-strip { display: flex; align-items: center; gap: .7rem; margin: 0 0 .85rem; color: var(--muted); font: 500 .72rem 'DM Mono', monospace; }
    .brand-mark { color: var(--pitch); font: 700 .78rem 'Space Grotesk', sans-serif; }
    .brand-divider { width: 1px; height: 14px; background: var(--line); }
    .brand-status { margin-left: auto; padding: .28rem .5rem; color: var(--pitch); background: var(--pitch-soft); border: 1px solid rgba(59,209,139,.18); border-radius: 4px; }
    .score-card {
        background: linear-gradient(150deg, rgba(20,45,65,.98), rgba(12,32,49,.98));
        border: 1px solid var(--line);
        border-top: 2px solid var(--pitch);
        border-radius: 6px;
        padding: 15px 17px;
        min-height: 142px;
        margin-bottom: 12px;
        animation: rise-in .35s ease-out both;
        box-shadow: 0 12px 30px rgba(0,0,0,.13);
    }
    .score-card .eyebrow { color: var(--muted); font: 500 .7rem 'DM Mono', monospace; text-transform: uppercase; }
    .score-card .market { color: var(--ink); font-size: 1rem; font-weight: 750; margin: 6px 0 9px; }
    .score-card .prob { color: var(--pitch); font: 700 2rem/1 'Space Grotesk', sans-serif; }
    .score-card .meta { color: var(--muted); font-size: .76rem; line-height: 1.6; margin-top: 10px; }
    .score-card .confidence { color: var(--muted); font-size: .74rem; font-weight: 650; }
    .score-card .badge { display: inline-block; border-radius: 4px; padding: 4px 8px; margin-top: 9px; font: 500 .68rem 'DM Mono', monospace; }
    .score-card .positive { color: var(--pitch); background: rgba(59,209,139,.12); }
    .score-card .negative { color: var(--coral); background: rgba(255,110,104,.12); }
    .score-card .neutral { color: var(--yellow); background: rgba(244,201,93,.12); }
    .score-card .suspicious { color: #1a1300; background: var(--yellow); font-weight: 700; }
    .score-card.suspicious-card { border-color: var(--yellow); box-shadow: 0 0 0 1px var(--yellow), 0 12px 30px rgba(0,0,0,.13); }
    .score-card .sources { color: var(--ink); font-size: .76rem; margin-top: 8px; }
    .section-kicker { color: var(--pitch); font: 500 .74rem 'DM Mono', monospace; text-transform: uppercase; margin: 18px 0 8px; }
    .input-card-title { color: var(--ink); font: 700 1.1rem 'Space Grotesk', sans-serif; margin-bottom: 2px; }
    .input-card-subtitle { color: var(--muted); font-size: .82rem; margin-bottom: 12px; }
    div[data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--line);
        border-radius: 6px;
        background: rgba(16,38,58,.93);
    }
    div[data-testid="stVerticalBlockBorderWrapper"] > div { padding: 0.8rem 1rem; }
    div[data-testid="stRadio"] label, div[data-testid="stNumberInput"] label,
    div[data-testid="stSlider"] label, div[data-testid="stTextInput"] label,
    div[data-testid="stTextArea"] label { color: var(--ink); font-weight: 650; }
    div[data-testid="stMetric"] { background: rgba(16,38,58,.96); border: 1px solid var(--line); border-bottom: 2px solid var(--yellow); border-radius: 5px; padding: .72rem .8rem; }
    div[data-testid="stMetricLabel"] { color: var(--muted); }
    div[data-testid="stMetricValue"] { color: var(--ink); }
    .stButton > button[kind="primary"] { background: #167b68; border-color: #2a9c82; color: white; border-radius: 5px; font-weight: 750; transition: transform .15s ease, background .15s ease; }
    .stButton > button[kind="primary"]:hover { background: #199378; border-color: #3bd18b; transform: translateY(-1px); }
    .stButton > button:not([kind="primary"]) { color: var(--ink); background: #142f45; border-color: var(--line); border-radius: 5px; }
    [data-baseweb="tab-list"] { gap: .3rem; border-bottom: 1px solid var(--line); }
    [data-baseweb="tab"] { color: var(--muted); }
    [aria-selected="true"][data-baseweb="tab"] { color: var(--pitch) !important; }
    [data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 5px; overflow: hidden; }
    [data-testid="stExpander"] { border-color: var(--line); background: rgba(16,38,58,.74); }
    [data-testid="stAlert"] { background: #102b40; color: var(--ink); border: 1px solid var(--line); }
    [data-testid="stMarkdownContainer"] strong { color: var(--ink); }
    [data-testid="stSelectbox"] label { color: var(--ink); }
    [data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { background: #0b1e30; border-color: var(--line); color: var(--ink); }
    [data-baseweb="input"] input, [data-baseweb="textarea"] textarea { color: var(--ink); -webkit-text-fill-color: var(--ink); }
    [data-testid="stNumberInput"] button { background: #18344a; color: var(--ink); border-color: var(--line); }
    [data-testid="stSlider"] [role="slider"] { background: var(--pitch); border-color: var(--pitch); }
    .pitch-rule { height: 1px; background: linear-gradient(90deg, transparent, rgba(151,190,207,.28), transparent); margin: .75rem 0 1.1rem; }
    @keyframes rise-in { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }
    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; } }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="brand-strip"><span class="brand-mark">SIMULPRO</span>'
    '<span class="brand-divider"></span><span>FOOTBALL MODEL LAB</span>'
    '<span class="brand-status">ON-DEMAND ENGINE</span></div>',
    unsafe_allow_html=True,
)
if st.sidebar.radio("Pagina", ["Simulatore", "Prestazioni"], key="page") == "Prestazioni":
    render_performance()
    st.stop()
st.title("Motore on-demand")
st.caption("Dashboard analitica senza calendario o database: input dichiarato, calcolo riproducibile e quote opzionali.")

with st.expander("Backtest storico gratuito · modello separato", expanded=False):
    st.markdown(
        "Carica CSV storici locali: il backtest non modifica la simulazione manuale e non usa API. "
        "Servono almeno tre stagioni per lega; una per addestrare, una per calibrare e una per testare. "
        "I file Football-Data.co.uk possono essere rinominati, ad esempio `E0_2020-21.csv`, oppure includere la colonna `Season`."
    )
    st.markdown(
        "Campi usati: `Date`, `HomeTeam`, `AwayTeam`, `FTHG`, `FTAG`; per il confronto bookmaker "
        "anche `B365H`, `B365D`, `B365A` (oppure quote `PSH`, `PSD`, `PSA`). Corner `HC/AC` e gialli `HY/AY` "
        "sono facoltativi. Fonte gratuita: [Football-Data.co.uk](https://www.football-data.co.uk/data.php)."
    )
    history_files = st.file_uploader(
        "CSV per stagione/lega",
        type=["csv"],
        accept_multiple_files=True,
        key="historical_csv_uploads",
        help="Puoi selezionare più stagioni. Se manca la colonna Season, il nome deve contenere l’anno, ad esempio E0_2020-21.csv.",
    )
    history_fingerprint = tuple(
        (uploaded.name, hashlib.sha256(uploaded.getvalue()).hexdigest())
        for uploaded in (history_files or [])
    )
    if st.session_state.get("historical_fingerprint") != history_fingerprint:
        st.session_state.pop("historical_result", None)
        st.session_state.pop("historical_matches", None)
        st.session_state.pop("historical_prediction", None)
        st.session_state["historical_fingerprint"] = history_fingerprint
    if st.button(
        "Esegui backtest walk-forward",
        type="secondary",
        disabled=not history_files,
        key="run_historical_backtest",
    ):
        try:
            historical_matches = load_football_data_uploads(history_files)
            st.session_state["historical_result"] = run_walk_forward(historical_matches)
            st.session_state["historical_matches"] = historical_matches
        except HistoricalDataError as exc:
            st.error(str(exc))

    historical_result = st.session_state.get("historical_result")
    if historical_result:
        st.markdown('<div class="pitch-rule"></div>', unsafe_allow_html=True)
        result_metrics = st.columns(3)
        result_metrics[0].metric("Partite out-of-sample", f'{historical_result["match_count"]:,}'.replace(",", "."))
        result_metrics[1].metric("Fold stagione/lega", historical_result["fold_count"])
        result_metrics[2].metric("Parametri calibrati su", "solo la stagione validation")
        st.dataframe(historical_result["metrics"].round(4), hide_index=True, width="stretch")
        comparison = historical_result["market_comparison"]
        if comparison:
            low, high = comparison["ci95_low"], comparison["ci95_high"]
            verdict = "differenza non conclusiva" if low <= 0.0 <= high else (
                "Dixon–Coles migliore" if comparison["mean_log_loss_delta"] < 0.0 else "mercato migliore"
            )
            st.info(
                f'Δ log-loss Dixon–Coles calibrato − mercato: {comparison["mean_log_loss_delta"]:+.4f}; '
                f'IC 95% [{low:+.4f}, {high:+.4f}] · {verdict}. '
                "Bootstrap appaiato per giornata; valori negativi favoriscono il modello."
            )
        if not historical_result["count_baselines"].empty:
            st.markdown("**Controllo conteggi corner e gialli**")
            st.dataframe(historical_result["count_baselines"].round(3), hide_index=True, width="stretch")
        if historical_result["skipped"]:
            with st.expander("Fold esclusi e motivi"):
                st.write("\n".join(historical_result["skipped"]))
        st.warning(
            "Il modello storico è un candidato di confronto: non sostituisce né altera il pronostico manuale. "
            "Il backtest non garantisce risultati futuri; controlla numero di partite, stagioni e completezza delle quote."
        )
        historical_matches = st.session_state.get("historical_matches")
        if historical_matches is not None:
            st.markdown("**Prova previsione storica candidata**")
            st.caption("Il modello usa risultati terminati prima della data impostata. La versione manuale resta invariata.")
            prediction_leagues = sorted(historical_matches["league"].dropna().unique())
            prediction_league = st.selectbox("Campionato", prediction_leagues, key="historical_prediction_league")
            prediction_teams = sorted(
                historical_matches.loc[historical_matches.league == prediction_league, ["home_team", "away_team"]]
                .to_numpy()
                .ravel()
            )
            team_columns = st.columns(2)
            prediction_home = team_columns[0].selectbox("Squadra casa", prediction_teams, key="historical_prediction_home")
            away_options = [team for team in prediction_teams if team != prediction_home]
            prediction_away = team_columns[1].selectbox("Squadra ospite", away_options, key="historical_prediction_away")
            prediction_date = st.date_input("Data della partita", value=date.today(), key="historical_prediction_date")
            prediction_signature = (
                history_fingerprint,
                prediction_league,
                prediction_home,
                prediction_away,
                prediction_date.isoformat(),
            )
            if st.session_state.get("historical_prediction_signature") != prediction_signature:
                st.session_state.pop("historical_prediction", None)
                st.session_state["historical_prediction_signature"] = prediction_signature
            if st.button("Calcola previsione storica", key="run_historical_prediction"):
                try:
                    st.session_state["historical_prediction"] = predict_historical_match(
                        historical_matches,
                        prediction_league,
                        prediction_home,
                        prediction_away,
                        prediction_date,
                    )
                except HistoricalDataError as exc:
                    st.error(str(exc))
            historical_prediction = st.session_state.get("historical_prediction")
            if historical_prediction:
                prediction_metrics = st.columns(5)
                prediction_metrics[0].metric("λ casa", f'{historical_prediction["lambda_home"]:.2f}')
                prediction_metrics[1].metric("λ ospite", f'{historical_prediction["lambda_away"]:.2f}')
                prediction_metrics[2].metric(
                    "Segno candidato",
                    f'{historical_prediction["favorite_sign"]} · '
                    f'{historical_prediction["probabilities_1x2_pct"][historical_prediction["favorite_sign"]]:.1f}%',
                )
                prediction_metrics[3].metric("Risultato fisso", historical_prediction["fixed_score"]["score"])
                prediction_metrics[4].metric("Dati storici usati", f'{historical_prediction["training_matches"]:,}'.replace(",", "."))
                st.caption(
                    f'Modello Dixon–Coles addestrato fino al {historical_prediction["data_through"].date()} · '
                    f'{historical_prediction["calibration_note"]} '
                    f'Temperatura {historical_prediction["calibration_temperature"]:.2f} · '
                    f'P(score fisso) {historical_prediction["fixed_score"]["unconditional_probability_pct"]:.2f}% '
                    f'(condizionata al segno favorito {historical_prediction["fixed_score"]["conditional_probability_pct"]:.2f}%).'
                )
                probability_rows = [
                    {"Esito": label, "Probabilità %": historical_prediction["probabilities_1x2_pct"][key]}
                    for key, label in (("1", "Vittoria casa"), ("X", "Pareggio"), ("2", "Vittoria ospite"))
                ]
                st.dataframe(pd.DataFrame(probability_rows), hide_index=True, width="stretch")
                st.dataframe(pd.DataFrame(historical_prediction["top_scorelines"]), hide_index=True, width="stretch")
                if historical_prediction["unseen_teams"]:
                    st.warning(
                        "Squadra/e non trovate nello storico: "
                        + ", ".join(historical_prediction["unseen_teams"])
                        + ". Per queste il modello usa forza media di lega."
                    )

if "input_text" not in st.session_state:
    st.session_state["input_text"] = EXAMPLE
st.session_state.setdefault("input_touched", False)

with st.container(border=True):
    st.markdown('<div class="input-card-title">Configurazione partita</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="input-card-subtitle">Scegli il flusso più rapido: incolla i dati oppure costruisci la partita campo per campo.</div>',
        unsafe_allow_html=True,
    )
    if "pending_input_mode" in st.session_state:
        st.session_state["input_mode"] = st.session_state.pop("pending_input_mode")
    input_mode = st.radio("Modalità input", ["Copia-incolla", "Dati automatici", "Crea partita"], horizontal=True, key="input_mode")
with st.expander("Quali dati inserire per un’analisi affidabile"):
    st.markdown(
        """
        - **Periodo e fonte:** usa la stessa competizione, stagione e fonte per entrambe le squadre; aggiorna i dati prima della partita. Se disponibili, usa i numeri della squadra in casa nelle gare casalinghe e quelli dell’ospite nelle trasferte.
        - **Attacco e difesa:** coefficienti relativi, non percentuali; intervallo `0.2–3.0`. `1.00` è la media della competizione. Attacco = gol fatti medi della squadra / media campionato; difesa = media campionato dei gol subiti / gol subiti medi della squadra. Una difesa più solida ha coefficiente maggiore di `1.00`.
        - **Elo:** rating assoluto (800–2400), calcolato con la stessa scala e fonte per entrambe le squadre.
        - **Forma:** gli ultimi 1–5 risultati, dal più vecchio al più recente, usando `W`, `D`, `L`.
        - **xG fatti/subiti:** expected goals medi per squadra e partita, dalla stessa fonte; intervallo `0–10`. Inserisci valori per gara, non totali stagionali.
        - **Corner pro/sub:** corner conquistati/concessi medi per squadra e partita, non coefficienti; intervallo `0–15` per squadra. Il motore incrocia i corner pro di ogni squadra con quelli subiti dall’avversaria. Il totale atteso del match è limitato a `20`; il campione d’esempio vale `9.95`, mentre `22 + 22` segnala unità o dati errati.
        - **Cartellini pro e arbitro:** usa gialli medi ricevuti per squadra e partita, massimo `10` per squadra; i rossi sono esclusi. L’arbitro riceve gialli e falli medi totali per partita; la media modellata è limitata a `20` gialli.
        - **Campione:** privilegia medie di stagione con almeno 8–10 gare; usa la forma recente solo per il campo `Forma`. Non mescolare totali, medie per 90 minuti e medie per partita.
        """
    )
if input_mode == "Copia-incolla":
    with st.container(border=True):
        st.markdown('<div class="input-card-title">Input dichiarato</div>', unsafe_allow_html=True)
        st.markdown('<div class="input-card-subtitle">Il testo viene passato al parser così com\'è; le righe che iniziano con # (fonti) sono ignorate.</div>', unsafe_allow_html=True)
        text = st.text_area(
            "Blocco CASA / OSPITE / ARBITRO",
            key="input_text",
            height=260,
            on_change=_mark_input_touched,
            help="Inserisci nome, attacco, difesa, Elo, forma, xG, corner pro/sub, cartellini pro e medie arbitro. Le quote non riconosciute o duplicate interrompono l’importazione: nessun campo viene scartato in silenzio.",
        )
    if st.session_state.get("auto_sheet_rows"):
        with st.expander("Fonti e date dei valori compilati automaticamente", expanded=True):
            st.caption("Relative all'ultima compilazione automatica; se modifichi il blocco a mano, i valori modificati non corrispondono più alle fonti indicate.")
            show_provenance(st.session_state["auto_sheet_rows"], st.session_state.get("auto_sheet_warnings", []))
    plausibility = plausibility_warnings(text)
    if plausibility:
        st.warning("Controllo di plausibilità:\n" + "\n".join(f"- {warning}" for warning in plausibility))
elif input_mode == "Dati automatici":
    with st.container(border=True):
        st.markdown('<div class="input-card-title">Dati automatici</div>', unsafe_allow_html=True)
        st.markdown('<div class="input-card-subtitle">Scegli competizione e partita, o scrivi le due squadre: il blocco si compila da solo con fonte e data accanto a ogni valore e resta modificabile.</div>', unsafe_allow_html=True)
        render_automatic()
    text = st.session_state["input_text"]
else:
    with st.container(border=True):
        st.markdown('<div class="input-card-title">Crea partita</div>', unsafe_allow_html=True)
        st.markdown('<div class="input-card-subtitle">Per le partite non presenti nei dati: i campi disponibili si compilano da soli, quelli mancanti restano vuoti ed evidenziati.</div>', unsafe_allow_html=True)
        render_create()
    text = st.session_state["input_text"]

parsed_preview: MatchInput | None = None
parse_error: str | None = None
try:
    parsed_preview = parse_match_input(text)
except MatchInputError as exc:
    parse_error = str(exc)

with st.expander("🔍 Diagnostica Parser & Quote", expanded=True):
    if parsed_preview is None:
        st.error(f"Parser non pronto: {parse_error}")
        st.caption("Completa i campi obbligatori per visualizzare i dati estratti.")
    else:
        st.caption("Anteprima live del risultato del parser sul blocco attualmente in input.")
        team_columns = st.columns(2)
        for column, label, team in (
            (team_columns[0], "Casa", parsed_preview.home),
            (team_columns[1], "Ospite", parsed_preview.away),
        ):
            with column:
                st.markdown(f"**{label}: {team.name}**")
                st.dataframe(
                    pd.DataFrame(
                        {
                            "Campo": ["Elo", "xG fatti / partita", "xG subiti / partita", "Forma", "Attacco", "Difesa", "Corner pro/sub per partita", "Gialli pro / partita"],
                            "Valore": [
                                str(team.elo),
                                str(team.xg_for),
                                str(team.xg_against),
                                team.form,
                                str(team.attack),
                                str(team.defense),
                                f"{team.corners_for:.2f} / {team.corners_against:.2f}",
                                str(team.cards_for),
                            ],
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                )
        referee_col, odds_col = st.columns(2)
        with referee_col:
            st.markdown("**Arbitro**")
            st.dataframe(
                pd.DataFrame(
                    {
                        "Campo": ["Gialli medi", "Falli medi"],
                        "Valore": [parsed_preview.referee.yellow_avg, parsed_preview.referee.fouls_avg],
                    }
                ),
                hide_index=True,
                width="stretch",
            )
        with odds_col:
            st.markdown(f"**Quote valide lette ({len(parsed_preview.odds)})**")
            if parsed_preview.odds:
                st.dataframe(
                    pd.DataFrame(
                        [{"Chiave": key, "Quota": value} for key, value in parsed_preview.odds.items()]
                    ),
                    hide_index=True,
                    width="stretch",
                )
            else:
                st.info("Nessuna quota valida nel testo.")
        if parsed_preview.warnings:
            st.warning("Warning e fallback: " + " · ".join(parsed_preview.warnings))
        else:
            st.success("Nessun warning: tutti i campi letti sono validi.")

if parsed_preview is not None and st.session_state.get("input_touched", False):
    automatic_signature = (hashlib.sha256(text.encode()).hexdigest(), date.today().isoformat())
    if st.session_state.get("automatic_prediction_signature") != automatic_signature:
        st.session_state.pop("automatic_prediction", None)
        st.session_state["automatic_prediction_signature"] = automatic_signature
        manual_config = config_from_input(parsed_preview)
        manual_lambda, manual_mu, _ = final_goal_rates(manual_config)
        manual_auxiliary = {
            "home_corners_for": parsed_preview.home.corners_for,
            "home_corners_against": parsed_preview.home.corners_against,
            "away_corners_for": parsed_preview.away.corners_for,
            "away_corners_against": parsed_preview.away.corners_against,
            "home_yellows_for": parsed_preview.home.cards_for,
            "away_yellows_for": parsed_preview.away.cards_for,
            "referee_yellow_avg": parsed_preview.referee.yellow_avg,
            "referee_fouls_avg": parsed_preview.referee.fouls_avg,
        }
        try:
            with st.spinner("Associo automaticamente le squadre e recupero lo storico gratuito…"):
                history_lookup = _cached_automatic_history(
                    parsed_preview.home.name,
                    parsed_preview.away.name,
                )
            if history_lookup["status"] != "ready":
                automatic_prediction = predict_manual_only(
                    parsed_preview,
                    reason=history_lookup["reason"],
                )
            else:
                try:
                    automatic_prediction = predict_historical_match(
                        history_lookup["history"],
                        history_lookup["code"],
                        history_lookup["home_team"],
                        history_lookup["away_team"],
                        date.today(),
                        manual_rates=(manual_lambda, manual_mu),
                        manual_rho=manual_config.dixon_coles_rho,
                        manual_weight=0.75,
                        manual_auxiliary=manual_auxiliary,
                    )
                except HistoricalDataError as exc:
                    automatic_prediction = predict_manual_only(parsed_preview, reason=str(exc))
        except HistoricalDataError as exc:
            automatic_prediction = predict_manual_only(parsed_preview, reason=str(exc))
        st.session_state["automatic_prediction"] = automatic_prediction

if parsed_preview is not None and st.session_state.get("input_touched", False):
    automatic_prediction = st.session_state.get("automatic_prediction")
    if automatic_prediction:
        with st.expander("Previsione automatica · storico se disponibile", expanded=True):
            manual_only = automatic_prediction["source_mode"] == "manual_only"
            if manual_only:
                st.warning(
                    f'{automatic_prediction["fallback_reason"]} Previsione calcolata al 100% con i dati manuali.'
                )
            else:
                st.caption(
                    f'Storico associato automaticamente: {automatic_prediction["league"]} · '
                    f'{automatic_prediction["home_team"]} vs {automatic_prediction["away_team"]} · '
                    f'dati fino al {automatic_prediction["data_through"].date()} '
                    f'({automatic_prediction["training_matches"]:,} partite). '
                    f'Dati inseriti manualmente: {automatic_prediction["manual_weight_pct"]:.0f}% · '
                    f'storico: {100 - automatic_prediction["manual_weight_pct"]:.0f}%.'
                )
            historical_probabilities = automatic_prediction.get("historical_probabilities_1x2_pct") or {}
            manual_probabilities = automatic_prediction.get("manual_probabilities_1x2_pct") or {}
            probability_rows = [
                {
                    "Esito": label,
                    "Storico calibrato %": historical_probabilities.get(key),
                    "Dati manuali %": manual_probabilities.get(key),
                    "Combinata %": automatic_prediction["probabilities_1x2_pct"][key],
                }
                for key, label in (("1", "Vittoria casa"), ("X", "Pareggio"), ("2", "Vittoria ospite"))
            ]
            result_columns = st.columns(3)
            result_columns[0].metric("Segno previsto", automatic_prediction["favorite_sign"])
            result_columns[1].metric("Risultato fisso", automatic_prediction["fixed_score"]["score"])
            result_columns[2].metric("Over 2.5", f'{automatic_prediction["over_2_5_pct"]:.1f}%')
            st.dataframe(pd.DataFrame(probability_rows), hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame(automatic_prediction["top_scorelines"]), hide_index=True, width="stretch")
            count_predictions = automatic_prediction["count_predictions"]
            count_columns = st.columns(4)
            count_columns[0].metric(
                "Corner attesi",
                f'{count_predictions["corner_mean_blended"]:.2f}'
                if count_predictions["corner_mean_blended"] is not None else "n/d",
            )
            count_columns[1].metric(
                "Over 8.5 corner",
                f'{count_predictions["corner_over_8_5_pct"]:.1f}%'
                if count_predictions["corner_over_8_5_pct"] is not None else "n/d",
            )
            count_columns[2].metric(
                "Gialli attesi",
                f'{count_predictions["yellow_mean_blended"]:.2f}'
                if count_predictions["yellow_mean_blended"] is not None else "n/d",
            )
            count_columns[3].metric(
                "Over 4.5 gialli",
                f'{count_predictions["yellow_over_4_5_pct"]:.1f}%'
                if count_predictions["yellow_over_4_5_pct"] is not None else "n/d",
            )
            count_rows = [
                {
                    "Misura": "Corner match",
                    "Storico": count_predictions["corner_mean_historical"],
                    "Manuale recente": count_predictions["corner_mean_manual"],
                    "Combinata": count_predictions["corner_mean_blended"],
                },
                {
                    "Misura": "Gialli match",
                    "Storico": count_predictions["yellow_mean_historical"],
                    "Manuale recente": count_predictions["yellow_mean_manual"],
                    "Combinata": count_predictions["yellow_mean_blended"],
                },
            ]
            st.dataframe(pd.DataFrame(count_rows).round(2), hide_index=True, width="stretch")
            if not manual_only:
                st.caption(automatic_prediction["calibration_note"])
                st.warning(
                    "La miscela ha sempre maggioranza manuale, ma il peso non è ancora calibrato su input manuali storici equivalenti. "
                    "Confronta le colonne prima di interpretare la previsione come accuratezza dimostrata."
                )

with st.container(border=True):
    st.markdown('<div class="input-card-title">Parametri simulazione</div>', unsafe_allow_html=True)
    st.markdown('<div class="input-card-subtitle">Controlla precisione e riproducibilità del calcolo.</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        simulations = st.number_input("Simulazioni Monte Carlo", min_value=1_000, max_value=200_000, value=100000, step=1_000)
    with col2:
        seed = st.number_input("Seed riproducibile", min_value=0, value=42, step=1)

with st.container(border=True):
    st.markdown('<div class="input-card-title">Quote e analisi valore</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="input-card-subtitle">Il testo viene importato automaticamente. '
        'Ogni campo valorizzato qui sotto sovrascrive la quota letta; lascia 0 per non inserirla.</div>',
        unsafe_allow_html=True,
    )
    quote_source = parsed_preview.odds if parsed_preview else {}
    quote_editor_token = str(abs(hash(text)))
    quote_categories = {
        "Esiti": ("1x2", "double_chance", "draw_no_bet", "first_half_1x2", "first_half_double_chance", "second_half_1x2", "second_half_double_chance"),
        "Goal": ("goal_no_goal", "first_half_goal_no_goal", "over_under", "first_half_over_under", "team_goals", "team_scoring"),
        "Multigol e somme": ("multigol_complete", "team_multigol", "goal_sums"),
        "Corner": ("corners", "corner_1x2", "team_corners"),
        "Cartellini": ("cards", "card_1x2", "team_cards"),
        "Combo": ("combos", "both_teams"),
    }
    odds_input: dict[str, float] = {}
    quote_tabs = st.tabs(list(quote_categories))
    for tab, groups in zip(quote_tabs, quote_categories.values()):
        with tab:
            for group in groups:
                definitions = definitions_for_group(group)
                if not definitions:
                    continue
                with st.expander(group.replace("_", " ").title(), expanded=group in {"1x2", "over_under"}):
                    for start in range(0, len(definitions), 3):
                        columns = st.columns(3)
                        for column, definition in zip(columns, definitions[start:start + 3]):
                            current = float(quote_source.get(definition.event_key, 0.0))
                            value = column.number_input(
                                definition.label,
                                min_value=0.0,
                                value=current,
                                step=0.01,
                                format="%.2f",
                                key=f"odd_{quote_editor_token}_{definition.key}",
                                help=f"Chiave motore: {definition.event_key}",
                            )
                            odds_input[definition.event_key] = float(value)

tactical_factors, tactical_switches = render_tactical(
    parsed_preview.home.name if parsed_preview else None, parsed_preview.away.name if parsed_preview else None
)
current_signature = (
    text,
    int(simulations),
    int(seed),
    tuple(sorted(odds_input.items())),
    tactical_factors,
    tactical_switches,
)

if st.button("Esegui simulazione", type="primary", width="stretch"):
    try:
        if parsed_preview is None:
            raise MatchInputError(parse_error or "Input non valido")
        parsed = parsed_preview
        config = config_from_input(parsed, simulations=int(simulations), seed=int(seed))
        merged_odds = dict(parsed.odds)
        for market, odd in odds_input.items():
            if odd > 1.0:
                merged_odds[market] = odd
            else:
                merged_odds.pop(market, None)
        config = config.__class__(**{**config.__dict__, "odds": merged_odds,
                                     "tactical": tactical_factors, "tactical_switches": tactical_switches})
        result = simulate_match(config)
        st.session_state["result"] = result
        st.session_state["result_config"] = config
        st.session_state["result_signature"] = current_signature
        st.session_state["warnings"] = parsed.warnings
    except MatchInputError as exc:
        st.error(str(exc))

if st.session_state.get("warnings"):
    st.warning("Fallback applicati: " + " · ".join(st.session_state["warnings"]))

def _source_probabilities(event_name: str | None) -> str:
    """Solo-mercato, solo-modello e finale per l'evento, dal risultato corrente."""
    components = (st.session_state.get("result") or {}).get("components") or {}
    if not event_name or event_name not in (components.get("finale") or {}):
        return ""

    def value(name: str) -> str:
        source = components.get(name)
        return f"{source[event_name]:.2f}%" if source and event_name in source else "—"

    return (
        f'<div class="sources">Solo mercato {value("mercato")} · Solo modello {value("modello")} · '
        f'Finale {value("finale")}</div>'
    )


def _card(
    eyebrow: str,
    label: str,
    market: dict,
    financial: dict,
    event_name: str | None = None,
) -> None:
    probability = float(market["percentage"])
    interval = market.get("confidence_interval_95", [0.0, 0.0])
    reliability = float(market.get("reliability_pct", 0.0))
    quote = financial.get("odds")
    implied = financial.get("implied_probability_pct")
    ev = financial.get("ev_pct")
    stake = financial.get("recommended_stake_pct")
    push = financial.get("push_probability_pct")
    fair_odds = market.get("fair_odds")
    if quote is None:
        comparison = "Quota bookmaker —"
        badge = '<span class="badge neutral">SOLO MODELLO</span>'
    else:
        comparison = f"Quota bookmaker {float(quote):.2f} · Implicita {float(implied):.2f}%"
        badge_class = "positive" if float(ev) > 0 else "negative"
        badge_text = f"VALORE +{float(ev):.2f}%" if float(ev) > 0 else f"EV {float(ev):.2f}%"
        if financial.get("value_excluded") and float(ev) > 0:
            badge_class = "neutral"
            badge_text = f"EV {float(ev):+.2f}% · VALORE non segnalato su questo mercato (storicamente in perdita)"
        if financial.get("suspicious_value"):
            badge_class = "suspicious"
            badge_text += f" · valore sospetto: verifica i dati (scarto modello/mercato {financial['model_market_gap_pct']:.1f} punti)"
        badge = f'<span class="badge {badge_class}">{badge_text}</span>'
    fair_meta = f" · Quota equa {float(fair_odds):.3f}" if fair_odds is not None else " · Quota equa —"
    ev_meta = f" · EV {float(ev):+.2f}%" if ev is not None else " · EV —"
    push_meta = f" · Push {float(push):.2f}%" if push is not None and float(push) > 0 else ""
    stake_meta = f" · Quarter-Kelly {float(stake):.2f}% bankroll" if stake is not None else " · Quarter-Kelly —"
    st.markdown(
        f"""
        <div class="score-card{' suspicious-card' if financial.get('suspicious_value') else ''}">
          <div class="eyebrow">{eyebrow}</div>
          <div class="confidence">Stabilità campionaria {reliability:.2f}% · Wilson 95% [{float(interval[0]):.2f}%, {float(interval[1]):.2f}%]</div>
          <div class="market">{label}</div>
          <div class="prob">{probability:.2f}%</div>
          {_source_probabilities(event_name)}
          <div class="meta">Probabilità finale · {comparison}{fair_meta}{ev_meta}{push_meta}{stake_meta}</div>
          {badge}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _cards_section(
    title: str,
    items: dict[str, dict],
    labels: dict[str, str],
    event_names: dict[str, str],
    financial_rows: dict[str, dict],
    columns: int = 3,
) -> None:
    st.markdown(f'<div class="section-kicker">{title}</div>', unsafe_allow_html=True)
    entries = list(items.items())
    for start in range(0, len(entries), columns):
        card_columns = st.columns(columns, gap="medium")
        for column, (key, market) in zip(card_columns, entries[start:start + columns]):
            event_name = event_names.get(key, key)
            financial = financial_rows.get(event_name, financial_rows.get(key.replace("_", " "), {}))
            finale = ((st.session_state.get("result") or {}).get("components") or {}).get("finale") or {}
            if event_name not in finale:
                event_name = key.replace("_", " ")
            with column:
                _card(title, labels.get(key, key), market, financial, event_name)


def _catalog_cards_section(group: str, result: dict, financial_rows: dict) -> None:
    definitions = definitions_for_group(group)
    catalog_group = result["markets"]["catalog"].get(group, {})
    entries = [
        (definition, catalog_group[definition.key])
        for definition in definitions
        if definition.key in catalog_group
    ]
    if not entries:
        return
    st.markdown(f'<div class="section-kicker">{group.replace("_", " ").title()}</div>', unsafe_allow_html=True)
    for definition, market in entries:
        financial = financial_rows.get(definition.event_key, {})
        _card(group.replace("_", " ").title(), definition.label, market, financial, definition.event_key)


result = st.session_state.get("result")
if result and st.session_state.get("result_signature") != current_signature:
    st.info("Configurazione modificata: riesegui la simulazione per aggiornare i risultati.")
    result = None
if result:
    model = result["model"]
    summary = result["summary"]
    st.subheader("Score-style match center")
    metrics = st.columns(5)
    metrics[0].metric("Casa λ", model["lambda"])
    metrics[1].metric("Ospite μ", model["mu"])
    metrics[2].metric(
        "Segno più probabile",
        f'{summary["favorite_sign"]} · {summary["favorite_sign_probability_pct"]:.2f}%',
    )
    metrics[3].metric(
        "Risultato fisso coerente",
        f'{summary["modal_score"]["home"]} - {summary["modal_score"]["away"]}',
        f'{summary["modal_score"]["share_pct"]:.2f}% del campione',
    )
    metrics[4].metric(
        "Calibrazione predittiva",
        "Non misurata",
        help="Il modello non è stato confrontato con risultati storici out-of-sample. La precisione Monte Carlo non equivale all’accuratezza delle previsioni.",
    )
    anchoring = result.get("market_anchoring", {})
    if anchoring.get("active"):
        fit = anchoring["market"]
        st.caption(
            f'Gol attesi · modello λ {anchoring["model_lambda"]:.3f} / μ {anchoring["model_mu"]:.3f} · '
            f'mercato λ {anchoring["market_lambda"]:.3f} / μ {anchoring["market_mu"]:.3f} '
            f'(margine tolto con metodo {fit["method"]}, errore di adattamento max {fit["max_fit_error_pct"]:.2f} punti) · '
            f'finale λ {model["lambda"]:.3f} / μ {model["mu"]:.3f}. {anchoring["reason"]}'
        )
    else:
        st.caption(f'Gol attesi solo dal modello: {anchoring.get("reason", "ancoraggio non disponibile.")}')
    global_score = summary["most_likely_exact_score"]
    st.caption(
        f'Score più frequente senza vincolo sul segno: '
        f'{global_score["home"]}-{global_score["away"]} '
        f'({global_score["share_pct"]:.2f}% del campione). Il risultato fisso è il punteggio '
        f'più frequente condizionato al segno {summary["favorite_sign"]}.'
    )

    st.subheader("Mercati coerenti col risultato fisso")
    st.caption(
        "Qui sono mostrate le conseguenze deterministiche del punteggio esatto selezionato. "
        "Corner e cartellini restano distribuzioni probabilistiche separate."
    )
    fixed_score_groups = {
        "1x2", "double_chance", "goal_no_goal", "over_under", "team_goals",
        "multigol_complete", "team_multigol", "goal_sums", "team_scoring", "combos",
    }
    fixed_score_rows = []
    for market, probability in result["fixed_score_scenario"]["markets"].items():
        definition = definition_for_event(market)
        if definition and definition.group in fixed_score_groups:
            fixed_score_rows.append({
                "Mercato": definition.label,
                "Esito col risultato fisso": "Sì" if probability == 100.0 else "No",
            })
    st.dataframe(
        pd.DataFrame(fixed_score_rows),
        hide_index=True,
        width="stretch",
        height=300,
    )

    financial_rows = {row["market"]: row for row in result["financial"]["markets"]}
    tabs = st.tabs([
        "Esiti & Doppia Chance",
        "Gol & Under/Over",
        "Multigol Totali & Squadra",
        "Corner",
        "Cartellini",
        "Dashboard",
        "Parziali",
        "Squadre",
        "Catalogo completo",
        "Stile",
    ])
    with tabs[0]:
        _cards_section(
            "1X2 finale",
            result["markets"]["1x2"],
            {"1": "Vittoria Casa", "X": "Pareggio", "2": "Vittoria Ospite"},
            {"1": "1", "X": "X", "2": "2"},
            financial_rows,
        )
        _cards_section(
            "1X2 primo tempo",
            result["markets"]["first_half_1x2"],
            {"1": "Casa 1° tempo", "X": "Pareggio 1° tempo", "2": "Ospite 1° tempo"},
            {"1": "1 1T", "X": "X 1T", "2": "2 1T"},
            financial_rows,
        )
    with tabs[1]:
        _cards_section(
            "Over / Under gol",
            result["markets"]["over_under"],
            {key: key.replace("_", " ") for key in result["markets"]["over_under"]},
            {key: f"{key.replace('_', ' ').replace('Over ', 'Over ').replace('Under ', 'Under ')} gol" for key in result["markets"]["over_under"]},
            financial_rows,
        )
    with tabs[2]:
        _cards_section(
            "Goal / No Goal",
            result["markets"]["goal_no_goal"],
            {"Goal": "Entrambe le squadre segnano", "No_Goal": "No Goal"},
            {"Goal": "Goal", "No_Goal": "No Goal"},
            financial_rows,
        )
        _cards_section(
            "Multigol",
            result["markets"]["multigol"],
            {key: f"Multigol {key}" for key in result["markets"]["multigol"]},
            {key: f"Multigol {key}" for key in result["markets"]["multigol"]},
            financial_rows,
        )
        _cards_section(
            "Multigol completo",
            result["markets"]["multigol_complete"],
            {key: f"Multigol totale {key}" for key in result["markets"]["multigol_complete"]},
            {key: f"Multigol {key}" for key in result["markets"]["multigol_complete"]},
            financial_rows,
        )
        team_multigol_tabs = st.tabs(["Multigol Casa", "Multigol Ospite"])
        for team_tab, team_name in zip(team_multigol_tabs, ("Casa", "Ospite")):
            with team_tab:
                team_items = {
                    key: market
                    for key, market in result["markets"]["team_multigol"].items()
                    if key.startswith(f"{team_name} ")
                }
                _cards_section(
                    f"Tutte le fasce · {team_name}",
                    team_items,
                    {key: f"Multigol {key}" for key in team_items},
                    {key: f"Multigol {key}" for key in team_items},
                    financial_rows,
                )
        _cards_section(
            "Combo",
            result["markets"]["combos"],
            {key: key for key in result["markets"]["combos"]},
            {key: key for key in result["markets"]["combos"]},
            financial_rows,
        )
    with tabs[3]:
        corner_labels = {key: key.replace("_", " ") for key in result["markets"]["corners"] if key != "mean"}
        _cards_section(
            f"Calci d'angolo · media {result['markets']['corners']['mean']}",
            {key: value for key, value in result["markets"]["corners"].items() if key != "mean"},
            corner_labels,
            {key: f"{key.replace('_', ' ')} corner" for key in corner_labels},
            financial_rows,
        )
        _cards_section(
            "1X2 corner",
            result["markets"]["corner_1x2"],
            {"1": "Più corner Casa", "X": "Parità corner", "2": "Più corner Ospite"},
            {"1": "1 corner", "X": "X corner", "2": "2 corner"},
            financial_rows,
        )
        _cards_section(
            "Corner per squadra",
            result["markets"]["team_corners"],
            {key: key.replace("_", " ") for key in result["markets"]["team_corners"]},
            {key: key.replace("_", " ") for key in result["markets"]["team_corners"]},
            financial_rows,
        )
    with tabs[4]:
        card_labels = {key: key.replace("_", " ") for key in result["markets"]["cards"] if key != "mean"}
        _cards_section(
            f"Cartellini · media {result['markets']['cards']['mean']}",
            {key: value for key, value in result["markets"]["cards"].items() if key != "mean"},
            card_labels,
            {key: f"{key.replace('_', ' ')} cartellini" for key in card_labels},
            financial_rows,
        )
        _cards_section(
            "1X2 cartellini",
            result["markets"]["card_1x2"],
            {"1": "Più cartellini Casa", "X": "Parità cartellini", "2": "Più cartellini Ospite"},
            {"1": "1 cartellini", "X": "X cartellini", "2": "2 cartellini"},
            financial_rows,
        )
        _cards_section(
            "Cartellini per squadra",
            result["markets"]["team_cards"],
            {key: key.replace("_", " ") for key in result["markets"]["team_cards"]},
            {key: key.replace("_", " ") for key in result["markets"]["team_cards"]},
            financial_rows,
        )
    with tabs[5]:
        st.markdown('<div class="pitch-rule"></div>', unsafe_allow_html=True)
        st.caption("MATCH INTELLIGENCE · probabilità derivate dagli stessi campioni")
        sign_order = ["1", "X", "2"]
        sign_labels = {"1": "Casa", "X": "Pareggio", "2": "Ospite"}
        sign_colors = {"Casa": "#3bd18b", "Pareggio": "#f4c95d", "Ospite": "#ff6e68"}
        sign_frame = pd.DataFrame([
            {
                "Esito": sign_labels[sign],
                "Probabilità": result["markets"]["1x2"][sign]["percentage"],
                "Wilson basso": summary["confidence_intervals_95"][sign][0],
                "Wilson alto": summary["confidence_intervals_95"][sign][1],
                "Campioni": result["markets"]["1x2"][sign]["count"],
            }
            for sign in sign_order
        ])
        chart_theme = {
            "background": "transparent",
            "axis": {"labelColor": "#b8c9d7", "titleColor": "#d9e4ed", "gridColor": "#294258", "domainColor": "#496175", "tickColor": "#496175"},
            "legend": {"labelColor": "#d9e4ed", "titleColor": "#d9e4ed"},
            "title": {"color": "#f0f5fa", "font": "Space Grotesk", "fontSize": 15, "anchor": "start"},
            "view": {"stroke": None},
        }
        sign_scale = alt.Scale(domain=["Casa", "Pareggio", "Ospite"], range=[sign_colors["Casa"], sign_colors["Pareggio"], sign_colors["Ospite"]])
        sign_bars = alt.Chart(sign_frame).mark_bar(size=56, cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("Esito:N", sort=["Casa", "Pareggio", "Ospite"], axis=alt.Axis(title=None, labelAngle=0)),
            y=alt.Y("Probabilità:Q", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(title="Probabilità (%)", values=[0, 20, 40, 60, 80, 100])),
            color=alt.Color("Esito:N", scale=sign_scale, legend=None),
            tooltip=[alt.Tooltip("Esito:N"), alt.Tooltip("Probabilità:Q", format=".2f"), alt.Tooltip("Wilson basso:Q", format=".2f"), alt.Tooltip("Wilson alto:Q", format=".2f"), alt.Tooltip("Campioni:Q", format=",")],
        )
        sign_intervals = alt.Chart(sign_frame).mark_rule(color="#f0f5fa", strokeWidth=2).encode(
            x=alt.X("Esito:N", sort=["Casa", "Pareggio", "Ospite"]),
            y=alt.Y("Wilson basso:Q"),
            y2=alt.Y2("Wilson alto:Q"),
        )
        sign_points = alt.Chart(sign_frame).mark_point(color="#f0f5fa", filled=True, size=72, stroke="#071727", strokeWidth=1).encode(
            x=alt.X("Esito:N", sort=["Casa", "Pareggio", "Ospite"]),
            y=alt.Y("Probabilità:Q"),
        )
        sign_chart = (sign_bars + sign_intervals + sign_points).properties(height=260, title="Esito finale · con intervallo Wilson 95%").configure(**chart_theme)

        goals = result["dashboard"]["goals_distribution"]
        goal_frame = pd.DataFrame({"Gol": goals["goals"], "Casa": goals["home"], "Ospite": goals["away"]}).melt(
            id_vars="Gol", var_name="Squadra", value_name="Probabilità"
        )
        goal_chart = alt.Chart(goal_frame).mark_line(point=alt.OverlayMarkDef(filled=True, size=65), strokeWidth=3).encode(
            x=alt.X("Gol:N", sort=goals["goals"], axis=alt.Axis(title="Gol segnati · fascia 8+ inclusa")),
            y=alt.Y("Probabilità:Q", scale=alt.Scale(zero=True), axis=alt.Axis(title="Probabilità (%)")),
            color=alt.Color("Squadra:N", scale=alt.Scale(domain=["Casa", "Ospite"], range=["#3bd18b", "#ff6e68"])),
            tooltip=[alt.Tooltip("Squadra:N"), alt.Tooltip("Gol:N"), alt.Tooltip("Probabilità:Q", format=".2f")],
        ).properties(height=260, title="Distribuzione gol per squadra").configure(**chart_theme)

        chart_col1, chart_col2 = st.columns(2, gap="large")
        with chart_col1:
            st.altair_chart(sign_chart, width="stretch", theme=None)
        with chart_col2:
            st.altair_chart(goal_chart, width="stretch", theme=None)

        exact = result["dashboard"]["exact_score_distribution"]
        score_rows = [
            {"Gol Casa": home_score, "Gol Ospite": away_score, "Probabilità": exact["probabilities_pct"][home_index][away_index]}
            for home_index, home_score in enumerate(exact["labels"])
            for away_index, away_score in enumerate(exact["labels"])
        ]
        score_frame = pd.DataFrame(score_rows)
        score_heatmap = alt.Chart(score_frame).mark_rect(stroke="#17334a", strokeWidth=1).encode(
            x=alt.X("Gol Casa:N", sort=exact["labels"], axis=alt.Axis(title="Gol Casa")),
            y=alt.Y("Gol Ospite:N", sort=list(reversed(exact["labels"])), axis=alt.Axis(title="Gol Ospite")),
            color=alt.Color("Probabilità:Q", scale=alt.Scale(scheme="tealblues"), legend=alt.Legend(title="% simulazioni")),
            tooltip=[alt.Tooltip("Gol Casa:N"), alt.Tooltip("Gol Ospite:N"), alt.Tooltip("Probabilità:Q", format=".3f")],
        ).properties(height=360, title="Matrice punteggio esatto · valori percentuali").configure(**chart_theme)
        st.altair_chart(score_heatmap, width="stretch", theme=None)

        threshold_rows = []
        for side in ("Over", "Under"):
            for key, market in result["markets"]["over_under"].items():
                if key.startswith(side):
                    threshold_rows.append({
                        "Mercato": side,
                        "Soglia": float(key.split("_")[1]),
                        "Probabilità": market["percentage"],
                        "Wilson basso": market["confidence_interval_95"][0],
                        "Wilson alto": market["confidence_interval_95"][1],
                    })
        threshold_frame = pd.DataFrame(threshold_rows)
        threshold_encoding = {
            "x": alt.X("Soglia:Q", axis=alt.Axis(title="Soglia gol", format=".1f")),
            "color": alt.Color("Mercato:N", scale=alt.Scale(domain=["Over", "Under"], range=["#3bd18b", "#ff6e68"])),
        }
        threshold_errors = alt.Chart(threshold_frame).mark_rule(strokeWidth=2, opacity=.62).encode(
            **threshold_encoding,
            y=alt.Y("Wilson basso:Q", scale=alt.Scale(domain=[0, 100])),
            y2=alt.Y2("Wilson alto:Q"),
        )
        threshold_lines = alt.Chart(threshold_frame).mark_line(point=alt.OverlayMarkDef(filled=True, size=60), strokeWidth=3).encode(
            x=alt.X("Soglia:Q", axis=alt.Axis(title="Soglia gol", format=".1f")),
            y=alt.Y("Probabilità:Q", scale=alt.Scale(domain=[0, 100]), axis=alt.Axis(title="Probabilità (%)")),
            color=alt.Color("Mercato:N", scale=alt.Scale(domain=["Over", "Under"], range=["#3bd18b", "#ff6e68"])),
            tooltip=[alt.Tooltip("Mercato:N"), alt.Tooltip("Soglia:Q", format=".1f"), alt.Tooltip("Probabilità:Q", format=".2f"), alt.Tooltip("Wilson basso:Q", format=".2f"), alt.Tooltip("Wilson alto:Q", format=".2f")],
        )
        threshold_chart = (threshold_lines + threshold_errors).properties(
            height=250, title="Curve Over / Under · intervalli Wilson 95%"
        ).configure(**chart_theme)
        st.altair_chart(threshold_chart, width="stretch", theme=None)

        corner_cards_col, referee_col = st.columns(2, gap="large")
        with corner_cards_col:
            st.markdown('<div class="section-kicker">CALCI D’ANGOLO</div>', unsafe_allow_html=True)
            st.metric("Media match stimata", f'{result["markets"]["corners"]["mean"]:.2f}', "Corner Casa + Ospite")
            st.caption("Modello Poisson; il dato non è condizionato al segno finale.")
        with referee_col:
            st.markdown('<div class="section-kicker">CARTELLINI (PUNTI)</div>', unsafe_allow_html=True)
            st.metric("Media match stimata", f'{result["markets"]["cards"]["mean"]:.2f}', "Punti cartellini Casa + Ospite")
            st.caption(f'Regola: {result["model"]["card_rule"]}. Gialli attesi {result["model"]["card_yellow_mean"]:.2f} '
                       f'(medie squadra e arbitro), rossi attesi {result["model"]["card_red_mean"]:.2f} '
                       "(quota media dei rossi per giallo); nessuna dipendenza dal risultato.")

        favorite_sign = summary["favorite_sign"]
        favorite_interval = summary["confidence_intervals_95"][favorite_sign]
        interval_width = favorite_interval[1] - favorite_interval[0]
        st.markdown('<div class="section-kicker">LEGGERE L’AFFIDABILITÀ</div>', unsafe_allow_html=True)
        reliability_cols = st.columns(3)
        reliability_cols[0].metric("Esito favorito · Wilson 95%", f'{favorite_interval[0]:.2f}% – {favorite_interval[1]:.2f}%')
        reliability_cols[1].metric("Ampiezza intervallo", f'{interval_width:.2f} punti percentuali')
        reliability_cols[2].metric("Campioni Monte Carlo", f'{result["model"]["simulation_count"]:,}'.replace(",", "."))
        st.warning(
            "Questi intervalli descrivono soltanto l’errore di campionamento simulato. "
            "Non misurano se lambda, mu o le probabilità siano predittivamente corrette. "
            "La calibrazione richiede molte partite storiche non usate per tarare il modello."
        )
        with st.expander("Input effettivamente letti dal motore"):
            input_rows = []
            for team_label, team_data in (("Casa", result["input"]["home"]), ("Ospite", result["input"]["away"])):
                for key, value in team_data.items():
                    input_rows.append({"Soggetto": team_label, "Parametro": key, "Valore usato": str(value)})
            input_rows.extend([
                {"Soggetto": "Arbitro", "Parametro": "Gialli medi / partita", "Valore usato": str(result["input"]["referee_yellow_avg"])},
                {"Soggetto": "Arbitro", "Parametro": "Falli medi / partita", "Valore usato": str(result["input"]["referee_fouls_avg"])},
            ])
            st.dataframe(pd.DataFrame(input_rows), hide_index=True, width="stretch")
        st.caption(summary["reliability"]["warning"])
    with tabs[6]:
        _cards_section("1X2 e doppia chance 1° tempo", result["markets"]["first_half_1x2"], {}, {key: f"{key} 1T" for key in ("1", "X", "2")}, financial_rows)
        _cards_section("Doppia chance 1° tempo", result["markets"]["first_half_double_chance"], {}, {key: f"{key} 1T" for key in ("1X", "X2", "12")}, financial_rows)
        _cards_section("1X2 e doppia chance 2° tempo", result["markets"]["second_half_1x2"], {}, {key: f"{key} 2T" for key in ("1", "X", "2")}, financial_rows)
        _cards_section("Doppia chance 2° tempo", result["markets"]["second_half_double_chance"], {}, {key: f"{key} 2T" for key in ("1X", "X2", "12")}, financial_rows)
        _cards_section("Draw No Bet", result["markets"]["draw_no_bet"], {"Casa": "Casa DNB", "Ospite": "Ospite DNB"}, {"Casa": "Casa DNB", "Ospite": "Ospite DNB"}, financial_rows)
        _cards_section("Over / Under 1° tempo", result["markets"]["first_half_over_under"], {}, {key: f"{key.replace('_', ' ')} gol 1T" for key in result["markets"]["first_half_over_under"]}, financial_rows)
        _cards_section("Goal / No Goal 1° tempo", result["markets"]["first_half_goal_no_goal"], {"Goal": "Entrambe segnano 1° tempo", "No_Goal": "No Goal 1° tempo"}, {"Goal": "Goal 1T", "No_Goal": "No Goal 1T"}, financial_rows)
    with tabs[7]:
        _cards_section("Goal squadra", result["markets"]["team_scoring"], {"Casa segna": "Casa segna", "Casa non segna": "Casa non segna", "Ospite segna": "Ospite segna", "Ospite non segna": "Ospite non segna"}, {}, financial_rows)
        _cards_section("Goal squadra · Over / Under", result["markets"]["team_goals"], {key: key for key in result["markets"]["team_goals"]}, {key: key for key in result["markets"]["team_goals"]}, financial_rows)
        _cards_section("Somma gol esatta", result["markets"]["goal_sums"], {key: f"Somma gol {key}" for key in result["markets"]["goal_sums"]}, {key: f"Somma gol {key}" for key in result["markets"]["goal_sums"]}, financial_rows)
        _cards_section("BTTS nei tempi", result["markets"]["both_teams"], {key: key for key in result["markets"]["both_teams"]}, {}, financial_rows)
    with tabs[8]:
        st.caption("Catalogo centrale: le card sono generate dalle definizioni condivise da parser, motore e dashboard.")
        for group in MARKET_GROUPS:
            _catalog_cards_section(group, result, financial_rows)
    with tabs[9]:
        render_style(result["input"]["home"]["name"], result["input"]["away"]["name"])

    st.subheader("Scenario condizionato al segno")
    st.caption(
        "Probabilità dei mercati osservate solo nelle simulazioni con il segno selezionato. "
        "Le probabilità base e l’analisi delle quote restano incondizionate."
    )
    most_likely_sign = max(
        result["markets"]["1x2"],
        key=lambda key: result["markets"]["1x2"][key]["percentage"],
    )
    scenario_col, group_col = st.columns(2)
    with scenario_col:
        scenario_sign = st.selectbox(
            "Esito finale ipotizzato",
            ("1", "X", "2"),
            index=("1", "X", "2").index(most_likely_sign),
            format_func=lambda sign: {"1": "1 · Vittoria Casa", "X": "X · Pareggio", "2": "2 · Vittoria Ospite"}[sign],
            key="conditional_scenario_sign",
        )
    with group_col:
        scenario_group = st.selectbox(
            "Gruppo mercati",
            ("Tutti", *MARKET_GROUPS, "Altri"),
            key="conditional_scenario_group",
        )
    scenario = result["conditional_scenarios"][scenario_sign]
    st.metric(
        f"Campioni con segno {scenario_sign}",
        f'{scenario["sample_count"]:,} · {scenario["sample_share_pct"]:.2f}%'.replace(",", "."),
    )
    if scenario["sample_count"] == 0:
        st.warning("Nessun campione ha prodotto questo segno: aumenta il numero di simulazioni per stimarlo.")
    else:
        scenario_rows = []
        for market, probability in scenario["markets"].items():
            definition = definition_for_event(market)
            group = definition.group if definition else "Altri"
            if scenario_group != "Tutti" and group != scenario_group:
                continue
            scenario_rows.append({
                "Mercato": definition.label if definition else market,
                "Probabilità condizionata": probability,
                "Gruppo": group.replace("_", " ").title(),
            })
        scenario_frame = pd.DataFrame(scenario_rows).sort_values(
            "Probabilità condizionata", ascending=False, na_position="last"
        )
        st.dataframe(scenario_frame, hide_index=True, width="stretch")

    st.subheader("Schedina mista")
    st.write(result["smart_combo"]["message"])
    recommendation = result["smart_combo"].get("recommendation")
    if recommendation:
        combo_interval = recommendation["confidence_interval_95"]
        combo_label = " + ".join(recommendation["legs"])
        st.markdown(
            f"""
            <div class="score-card">
              <div class="eyebrow">Schedina mista · 2 leg</div>
              <div class="confidence">Stabilità campionaria {recommendation["reliability_pct"]:.2f}% · Wilson 95% [{combo_interval[0]:.2f}%, {combo_interval[1]:.2f}%]</div>
              <div class="market">{combo_label}</div>
              <div class="prob">{recommendation["simulated_probability_pct"]:.2f}%</div>
              <div class="meta">Quota combinata {recommendation["combined_odds"]:.3f} · EV {recommendation["ev_pct"]:+.2f}% · Quarter-Kelly {recommendation["recommended_stake_pct"]:.2f}% bankroll</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe(pd.DataFrame([recommendation]), width="stretch")
    else:
        st.info(result["smart_combo"]["message"])

    st.subheader("Value bet e rischio")
    value_bets = result["financial"].get("value_bets", [])
    if value_bets:
        best_value = result["financial"]["best_value"]
        st.success(
            f"Consigliato per il Profitto: {best_value['market']} · "
            f"EV {best_value['ev_pct']:+.2f}% · Quarter-Kelly "
            f"{best_value['recommended_stake_pct']:.2f}% del bankroll"
        )
        value_frame = pd.DataFrame(value_bets)
        st.dataframe(
            value_frame.style.apply(
                lambda row: ["background-color: rgba(244,201,93,.35)" if row.get("suspicious_value") else "" for _ in row],
                axis=1,
            ),
            width="stretch",
        )
        if value_frame.get("suspicious_value", pd.Series(dtype=bool)).any():
            st.warning("Righe in giallo: valore sospetto, verifica i dati. Modello e mercato divergono di oltre 10 punti.")
        st.caption(
            "Mostrate solo quote con EV positivo, ordinate dal valore atteso più alto. "
            "La quota equa dei mercati binari è 1 / probabilità simulata; per il DNB il calcolo include il push."
        )
    else:
        st.info("Nessuna Value Bet a EV positivo tra le quote inserite.")
    with st.expander("Audit completo delle quote"):
        if result["financial"]["markets"]:
            st.dataframe(pd.DataFrame(result["financial"]["markets"]), width="stretch")
        else:
            st.info("Nessuna quota valida inserita.")
    st.caption(result["financial"]["risk_note"])

    if st.session_state.get("result_config") is not None:
        claude_result, claude_note = render_claude(result, st.session_state["result_config"], text)
        render_registry(result, st.session_state["result_config"], claude_result, claude_note)

    st.subheader("Sintesi statistica del modello")
    st.write(result["statistical_report"])
    st.subheader("Lettura guidata dei risultati")
    question = st.selectbox(
        "Seleziona una domanda",
        ("Qual è l'esito più frequente?", "Il modello vede una partita da Over 2.5?", "Qual è il rischio principale?"),
    )
    if question == "Qual è l'esito più frequente?":
        one_x_two = result["markets"]["1x2"]
        best = max(one_x_two, key=lambda key: one_x_two[key]["percentage"])
        st.info(f"Il mercato più frequente è {best} con {one_x_two[best]['percentage']:.2f}% sui campioni.")
    elif question == "Il modello vede una partita da Over 2.5?":
        over = result["markets"]["over_under"]["Over_2.5"]["percentage"]
        st.info(f"Over 2.5: {over:.2f}%. La risposta è descrittiva; non equivale a una raccomandazione.")
    else:
        st.info(
            f"Il rischio principale è l'incertezza del campione: l'indice campionario è "
            f"{result['summary']['reliability']['index_pct']:.2f}% e non valuta la qualità degli input."
        )

    with st.expander("Audit del calcolo"):
        st.json({"model": model, "input": result["input"], "confidence_intervals_95": summary["confidence_intervals_95"]})
