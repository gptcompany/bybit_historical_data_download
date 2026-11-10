# F-649: cold Bybit, un solo scheduler

B5 approva il 10 novembre 2026 il disegno con il SÌ dell'operatore.
Il cold resta sul Dell; nessun componente live viene collocato sul Dell.
L'attivazione e il download spettano a B5 dopo merge e review di tutte le fette.

## Decisione e consegna progressiva

Unico scheduler: timer systemd alle 03:15 UTC, sorgente nel repo proprietario.
Installer Python manifest-driven da SHA approvato, directory nuova separata da
`/media/sam/1TB/bybit_data_downloader`, runtime storico sempre in sola lettura.
Immagine fissata per digest, bind esplicito del cold
`/data/cold/12TB/bybit_data_downloader/data`; nessun default verso altri dischi.
Confronto anti-drift giornaliero fra unit installate e rendering del medesimo SHA,
con digest e mount previsti, esito nonzero e finding/allarme per divergenze.
PR successive consegnano esecuzione/validazione, installer e controllo drift.
PR mirate in progressive-deploy e monitoring-stack ritirano rispettivamente
Rollout/trigger e unit legacy Bybit prima dell'attivazione; niente Ansible nuovo.

## Piano prima dei dati

`PYTHONPATH=src python -m bybit_data_downloader.backfill --start-date 2026-06-29 --end-date 2026-11-09 --symbols BTCUSDT,ETHUSDT --types trade,orderbook,klines,funding,openinterest,longshortratio --intervals 1m,5m,15m --data-root /data/cold/12TB/bybit_data_downloader/data --dry-run`

HEAD soltanto per trade CSV.GZ e orderbook ob200 ZIP; dimensioni API ignote,
mai inventate. Il piano non certifica record e non crea directory o file.
L'esecutore dovrà validare schema, simbolo, giorno UTC, duplicati e griglie prima
di pubblicare atomicamente file e manifest; file esistente non implica completo.
Ogni run dovrà registrare esito e conteggi e lasciare incompleto un giorno fallito.

## Integrità: limite esplicito Bybit

Bybit non fornisce un checksum ufficiale nei percorsi archivi verificati.
B5 accetta decompressione completa con CRC gzip/ZIP, validazione dei record,
quindi SHA256 locale nel manifest: **non equivale a un checksum upstream**.
Un errore di integrità/schema impedisce sempre il completamento del giorno.
HEAD del 10 novembre: trade e ob200 BTCUSDT del 9 novembre HTTP 200;
suffix `.CHECKSUM`, `.sha256`, `.md5` HTTP 404, nessun header digest osservato.
