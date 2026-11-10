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

Il trigger `trigger-progressive-deploy.yml` è ritirato: un merge del codice cold
non deve inviare repository_dispatch né aggiornare manifest di deploy.
Controprova osservata dopo #4: trigger 42836738544, progressive-deploy 42836761868,
update-manifest riuscito e wait-for-sync fallito. La build immagine resta in CI
self-hosted di progressive-deploy, separata dal deploy; il runner CI Dell è
ammesso da B5, mentre il writer non esegue build locali. Il digest risultante
verrà fissato nel manifest dello scheduler. Nessuna attivazione in questa PR.

## Piano prima dei dati

`PYTHONPATH=src python -m bybit_data_downloader.backfill --start-date 2026-06-29 --end-date 2026-11-09 --symbols BTCUSDT,ETHUSDT --types trade,orderbook,klines,funding,openinterest,longshortratio --intervals 1m,5m,15m --data-root /data/cold/12TB/bybit_data_downloader/data --dry-run`

HEAD soltanto per trade CSV.GZ e orderbook ob200 ZIP; dimensioni API ignote,
mai inventate. Il piano non certifica record e non crea directory o file.
L'esecutore dovrà validare schema, simbolo, giorno UTC, duplicati e griglie prima
di pubblicare atomicamente file e manifest; file esistente non implica completo.
Ogni run dovrà registrare esito e conteggi e lasciare incompleto un giorno fallito.

L'esecutore si invoca con lo stesso comando senza `--dry-run`; esclusione con
flock, staging sul filesystem di destinazione, fsync e rename prima del manifest.
`complete` certifica una sola serie/giorno selezionata, mai l'intero dataset.
Un file presente è riverificato prima di essere riutilizzato; nessuna append.
Archivi: ID univoci su SQLite temporaneo, timestamp ordinati e almeno un record
per minuto UTC (criterio conservativo per BTC/ETH); ZIP con un solo membro `.data`.
API: klines 1/5/15m, OI e ratio 1d, funding BTC/ETH alle 00/08/16 UTC;
altre griglie funding non certificate vengono rifiutate. Log JSONL in `logs/`.
Un errore interrompe il run con esito failure e nessun manifest della serie fallita.

## Integrità: limite esplicito Bybit

Bybit non fornisce un checksum ufficiale nei percorsi archivi verificati.
B5 accetta decompressione completa con CRC gzip/ZIP, validazione dei record,
quindi SHA256 locale nel manifest: **non equivale a un checksum upstream**.
Un errore di integrità/schema impedisce sempre il completamento del giorno.
HEAD del 10 novembre: trade e ob200 BTCUSDT del 9 novembre HTTP 200;
suffix `.CHECKSUM`, `.sha256`, `.md5` HTTP 404, nessun header digest osservato.

## Contratto di rendering del deploy cold

`scripts/cold_deploy.py` rende le unit senza scrivere o avviare alcunché.
L'inventario JSON chiuso richiede immagine `ghcr.io/gptcompany/bybit-downloader`
per digest SHA256, SHA sorgente dell'immagine, utente, UID/GID e `cold_root`.
Default previsti per Dell: sam, 1000:1000 e il cold indicato sopra. I valori
reali saranno versionati nel manifest con il digest della build-only di B5.
Nessun file host di override; nessun segreto necessario agli archivi pubblici.
Il comando Docker usa `--mount` (directory preesistente), `--pull=never`, UTC
ed entrypoint Python esplicito sul modulo backfill, senza il comando live.
La release sarà separata dal checkout storico e identificata dallo SHA approvato.
Il suo interprete `.venv/bin/python` richiederà jsonschema già usato nel repo.
Un solo timer scarica alle 03:15 UTC; un timer di controllo alle 02:45 UTC
confronta tutte le unit col rendering, anche se il timer dati è alterato.
Queste sono funzioni pure: i sottocomandi run/drift e l'installer sono la fetta
successiva, necessaria prima di installazione e attivazione da parte di B5.


## Installer e drift da release approvata

Il manifest unico sarà `deploy/cold.json`: nessun override host. La directory
`/opt/bybit-cold/<SHA>` deve avere HEAD uguale allo SHA e file tracciati puliti;
l'installer richiede anche `--approved-sha <SHA>`. La `.venv` non tracciata è
il solo ambiente dell'interprete, non una sorgente di configurazione.
Comando previsto: `<release>/.venv/bin/python <release>/scripts/cold_deploy.py install <release> --approved-sha <SHA>`.
L'installer scrive quattro unit e maschera service/timer `bybit-sync` e
`bybit-sync-docker`; non esegue daemon-reload, enable, start o stop.
Prima dell'attivazione B5 arresta/disabilita entrambe le coppie legacy, poi
esegue daemon-reload. Le unit Docker legacy non sono più versionate qui;
monitoring-stack ritira l'altra coppia in una PR dedicata.
Il controllo drift confronta byte delle quattro unit, maschere e metadati
systemd: FragmentPath esatto, nessun DropInPaths, NeedDaemonReload=no;
le unit legacy devono risultare inactive e masked, altrimenti failure F-649.
Output JSON nel journal, exit nonzero su drift o sorgente non verificabile;
non vengono lette Environment o altre proprietà potenzialmente segrete.
Il comando run e il manifest reale restano necessari prima dell'installazione.

Il gate condiviso confronta inoltre i byte di `deploy/cold.json` con
`git show <SHA>:deploy/cold.json`, senza dipendere dai flag di ottimizzazione
dell'indice: assume-unchanged e skip-worktree non autorizzano un override host.
La stessa verifica protegge installer e certificazione drift.
