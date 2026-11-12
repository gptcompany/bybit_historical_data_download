# Spec #25

Il database temporaneo usa filesystem locale configurabile via BYBIT_ID_TMPDIR,
con default tempfile.gettempdir(); non ricade sul cold in caso di errore.
Unicità e copertura restano obbligatorie per trade e order book, su download
e cache. Connessione e directory vengono eliminate anche su errore.
Cache SQLite 64 MiB, indice su disco per giorni grandi; nessun deploy.


Errori di configurazione o ambiente dello scratch (directory assente, permessi,
spazio, SQLite, pulizia) interrompono esplicitamente il run come errore operativo.
Con cache valida, archivio e manifest restano identici e non parte alcun download.
Solo il fallimento dei controlli della cache causa quarantena e recupero.
