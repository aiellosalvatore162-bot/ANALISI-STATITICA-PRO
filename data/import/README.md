# Dati aggiunti (fase AN)

Modelli CSV in `modelli/`: stile squadra, giocatori, formazioni/assenti, arbitri, quote. Le intestazioni accettano nomi italiani e
inglesi. Importare con `python -m tools.importa_dati <file> [--fonte "nome"]`; il registro delle importazioni è `registro.json`
(fonte, data, righe importate e scartate), le scelte dei nomi squadra sono in `nomi.json`. I dati importati vivono in
`data/cache/importati/` (cache dell'app, non versionata).

Regole: `data_dati` = data a cui i dati sono aggiornati; il motore usa solo righe con `data_dati` PRECEDENTE alla partita.
Per lo stile, `xg`/`xga`/`partite` sostituiscono il proxy dai tiri nella forma reale, e `tiri_transizione`,
`quota_xg_palle_inattive`, `cross` riempiono i campi «non disponibile». Le altre colonne (possesso, ppda…) sono salvate e
consultabili ma oggi il motore non le legge; giocatori, formazioni, arbitri e quote sono importati e consultabili.
