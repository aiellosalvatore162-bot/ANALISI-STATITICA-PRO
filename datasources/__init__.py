"""Livello dati: download, cache e normalizzazione delle fonti gratuite.

Ogni valore restituito porta con sé fonte e data. Quando una fonte non
risponde si usa l'ultimo dato in cache e si restituisce un avviso; se non c'è
nulla in cache il campo resta vuoto, mai inventato.
"""
