# Fase AO – giocatori e formazione nel motore a eventi

Understat, 3677 squadre-partita (1839 partite, D1, E0, F1, I1, SP1), dal 2025-09-23 al 2026-10-26; solo gare precedenti per tassi, XI tipo e concessioni. Quasi-Poisson con offset, errori robusti per partita.

## Tiri (fase offensiva e difensiva)

| termine | stima | e.s. | IC 95% |
|---|---|---|---|
| intercetta | -0.0679 | 0.0139 | -0.0952 … -0.0407 |
| casa | +0.2160 | 0.0137 | +0.1890 … +0.2429 |
| attacco | +0.5766 | 0.0777 | +0.4243 … +0.7288 |
| difesa_POR | +0.0324 | 0.0204 | -0.0076 … +0.0725 |
| difesa_DIF | +0.0436 | 0.0292 | -0.0137 … +0.1009 |
| difesa_CEN | +0.0603 | 0.0297 | +0.0021 … +0.1185 |

## Qualità: npxG per tiro

| termine | stima | e.s. | IC 95% |
|---|---|---|---|
| intercetta | -0.0042 | 0.0167 | -0.0370 … +0.0286 |
| casa | +0.0302 | 0.0157 | -0.0005 … +0.0609 |
| attacco | +0.4199 | 0.1308 | +0.1635 … +0.6763 |
| difesa_POR | +0.0384 | 0.0251 | -0.0108 … +0.0876 |
| difesa_DIF | -0.0142 | 0.0351 | -0.0831 … +0.0546 |
| difesa_CEN | +0.0223 | 0.0372 | -0.0507 … +0.0952 |

«attacco» = esponente del rapporto XI atteso / XI tipo (tiri o npxG per tiro); «difesa_RUOLO» = effetto sul logaritmo per quota di minuti di ruolo mancanti nell'AVVERSARIO (1 = tutto il reparto dell'XI tipo assente).
Nel motore entrano i valori stimati così come sono (anche se vicini a zero), con l'intervallo nella scheda.
