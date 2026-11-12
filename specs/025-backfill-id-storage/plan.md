# Piano #25

1. Caratterizzazione duplicati/buchi -> verifica: CI 43237729183.
2. Regressione volume temporaneo e pulizia -> verifica: CI RED prima del fix.
3. Spostare scratch, chiudere connessione, singolo B-tree, cache 64 MiB ->
   verifica: stessi test GREEN e diff coverage >=85% in CI.
4. Confrontare release b1327ed e head sullo stesso gzip da 4,32 milioni di
   ID pseudocasuali e giornata UTC intera -> verifica: step CI dedicato, tempi
   e dimensioni nel body PR; nessuna misura locale.
Rischio: spazio locale insufficiente, fallimento chiuso. Analisi: API esclusa,
nessun caller aggirato, stesso controllo INSERT per riga, memoria non illimitata.
