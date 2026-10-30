# Formato del report dell'Analista (campi facoltativi della fase AH)

Il report resta FACOLTATIVO: senza report la giornata gira come prima. I campi sotto stanno dentro il blocco
`PARTITA: Casa - Ospite | competizione | gg/mm/aaaa hh:mm`, prima di `CORREZIONI_CLAUDE:`. Un report senza questi campi dà
lo stesso risultato di prima. Una riga non valida viene scartata con un avviso (il resto del blocco non cambia). Ogni
riga vuole una **fonte con link**.

```
ASSENTI_PESATI:
casa: Nome Cognome | ruolo: ATT | peso: 0.12 | fonte: https://...
ospite: Nome Cognome | ruolo: DIF | peso: 0.05 | fonte: https://...
RIPOSO:
casa: 3 | ospite: 7 | fonte: https://...
TURNOVER:
casa: probabile | fonte: https://...
ospite: no | fonte: https://...
```

- **ASSENTI_PESATI**: solo per i giocatori che Understat non ha (campionati fuori dai 5 grandi, coppe). `ruolo` = POR/DIF/CEN/ATT,
  `peso` = quota di produzione offensiva persa (0-1). Un peso sopra 0.35 è riportato a 0.35 con avviso. Se il giocatore è già
  in `assenti_casa/ospite` e Understat lo conosce, conta UNA volta sola (vale Understat).
- **RIPOSO**: giorni dall'ultima partita; serve solo se manca il calendario (altrimenti vale il calendario).
- **TURNOVER**: `probabile` o `no`. Se probabile, la forza della formazione attesa si riduce (effetto dichiarato in scheda).
- I profili tattici restano nei blocchi `PROFILO_TATTICO:` (formato della fase Q); gli esiti in `ESITO:` (fase Y) o
  `ESITI_CLAUDE:` (testo con ID E1…). Con più fonti per lo stesso esito vale CSV > ESITO > ESITI_CLAUDE e i conflitti sono mostrati.

Esempio: `tests/fixtures/analista/report_ah.md`.
