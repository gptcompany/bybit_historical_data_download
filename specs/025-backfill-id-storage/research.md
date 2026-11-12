# Ricerca #25

Mappa: `validate -> scan -> _validate`, chiamati da download, cache e
pubblicazione order book; API usa griglie in memoria e non SQLite.
Fetta: solo indice temporaneo degli ID degli archivi. Regole: unicità esatta,
ordine UTC, tutti i 1440 minuti, CRC e schema invariati.
Riuso: SQLite, tempfile e contextlib della libreria standard; nessun codice
esterno copiato, nessuna dipendenza. Set in memoria scartato perché cresce
senza limite; ordinare tutto richiederebbe memoria o un secondo passaggio.
Transazione già unica; il problema è il doppio B-tree casuale sul cold USB.
Caratterizzazione prima della modifica: commit 74cca83, CI 43237729183 verde.
