# Stato Fase AH (stili e report dell'Analista come input del motore, riquadro «Stile»)

Ramo: `fase-ah-stili-analista`.

## Stadio 1 – grafo delle chiamate (fatto)
- `analyst.parse_full(text, day)` → `parse_report` (blocchi PARTITA + CORREZIONI_CLAUDE + FORMA + CHIAVI_MATCH), `analyst.parse_outcomes` (blocchi ESITO), `analyst.parse_profiles` (che chiama `tactical_sheets.parse_profiles` su ogni regione PROFILO_TATTICO e poi imposta origine «Analista» e data).
- `tactical_sheets.parse_profiles(text)` è anche usato da `ui_tactical` (scheda tattica, origine «Claude (da confermare)»).
- ESITI_CLAUDE: `today.parse_outcomes(text, targets)` (testo con ID E1.., usato da `ui_performance`) — formato e colonne ripetuti rispetto a `analyst.OUTCOME_FIELDS`.
- Differenze: ESITO ha header «Casa - Ospite | competizione | data», righe per tempo (`corner_1t`…), errore per blocco; ESITI_CLAUDE ha ID, solo 5 voci, ignora blocchi senza fonte/risultato con avviso, lancia `ResponseError` se non ci sono blocchi.
- Duplicazione reale: (a) la lettura delle coppie «x-y» e della fonte (due copie), (b) l'impostazione di origine/data dei profili (solo in `analyst`).
- `settle_leg` (Fase AA) NON esiste su main: `outcomes.lookup` è il punto di aggancio.

## Stadi
2. `outcomes.py` (CSV > ESITO > ESITI_CLAUDE, conflitti visibili): DA FARE
3. Parser profili unico (`tactical_sheets.parse_profiles(origin, day)`): DA FARE
4. Campi PARTITA ASSENTI_PESATI / RIPOSO / TURNOVER (`match_extras.py`, `docs/formato_analista.md`, fixture): DA FARE
5. `match_context.py` + `config/stile_prior.json`: DA FARE
6. Dataset Analista (profili ed esiti con data e fonte): DA FARE
7. Riquadro «Stile» (`ui_style.py`), vista compatta in Oggi, foglio «Stile»: DA FARE
8. Test, suite, merge, push: DA FARE
