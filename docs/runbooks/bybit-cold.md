# Bybit cold: consegna F-649

Solo B5 esegue installazione, attivazione e backfill dopo review e merge.
Il SÌ dell'operatore del 10 novembre copre il backfill; il ritiro GitOps con
prune dev/staging richiede il SÌ aggiuntivo richiesto da B5. Nessuna procedura
modifica `/media/sam/1TB/bybit_data_downloader`, checkout runtime in sola lettura.
Nessun componente live viene installato sul Dell.

## Autorità e versione

Sorgenti uniche: `deploy/cold.json` e `scripts/cold_deploy.py` in questo repo.
Il manifest fissa digest immagine, SHA della sorgente immagine, UID/GID, utente
e mount cold, DNS IPv4 espliciti; niente override host o segreti. Le unit sono rendering, non
un'altra configurazione. Default Dell: sam, 1000:1000, cold
`/data/cold/12TB/bybit_data_downloader/data`.

Prima di installare, B5 verifica il ritiro versionato del trigger proprietario,
del deploy/Rollout/Kargo in progressive-deploy e delle unit legacy in
monitoring-stack. Le Application Argo devono avere il refresh anche sulla base;
il solo merge non certifica la scomparsa degli oggetti runtime Kargo/Argo.

B5 prepara una nuova release Git `/opt/bybit-cold/<SHA approvato>` dal merge
finale e la sua `.venv` con `requirements.txt`; HEAD deve corrispondere al nome.
Il manifest fa parte di quello SHA. La sorgente dell'immagine è invece lo SHA
registrato nel manifest, precedente al commit che ne fissa il digest.
B5 acquisisce esplicitamente l'immagine per digest prima del run: `--pull=never`
impedisce pull impliciti; l'entrypoint Python bypassa il vecchio comando live.

## Provenienza dei DNS

Incidente Dell del 2026-11-10 alle 21:50 UTC, release `92d51df` con drift
success: il piano `backfill --types trade --dry-run` falliva con `ConnectError`.
Nell'immagine approvata `socket.getaddrinfo` non risolveva `public.bybit.com`
né `api.bybit.com` con il DNS ereditato `192.168.1.1`; un altro dominio
risolveva. Il resolver locale host `127.0.2.2` non è raggiungibile dal bridge
Docker. Le controprove con `docker run --dns 1.1.1.1` e `--dns 9.9.9.9`
risolvevano `public.bybit.com` (evidenza operativa fornita da B5).

Per questo `deploy/cold.json` registra `dns: ["1.1.1.1", "9.9.9.9"]`:
indirizzi pubblici, non segreti. Lo schema richiede almeno due IPv4 distinti;
Docker riceve un `--dns <ip>` per ciascuno, in ordine, anche in dry-run.
Nessun override host: inventario e codice provengono dallo stesso snapshot Git
approvato; installazione e drift continuano a usare unit byte-identiche al
rendering di quello SHA. Questa modifica non certifica un nuovo piano runtime:
B5 lo verifica dopo review, merge e nuova release approvata.

## Provenienza della build

Build-only B5: [run 42939765677](https://github.com/gptcompany/progressive-deploy/actions/runs/42939765677),
job `130258523351`, conclusione success. Sorgente immagine:
`975930e22505cf314dd609809fdce8940a98c27c` (merge proprietario #14: schema RPI, diagnostica e coda ob200).
Immagine approvata, registrata anche nel manifest:
`ghcr.io/gptcompany/bybit-downloader@sha256:13255f647e4dead0b191d159d37084fd982d1992a65f1384a1dca75b3f0876f2`.
Il digest è `containerimage.digest` della fase Build and push, confermato da B5;
non usare un tag mobile o lo SHA del workflow progressive-deploy come sorgente.

## Installazione e controllo

Non esiste un installer Ansible Bybit da estendere: l'installer proprietario
Python è il percorso scelto. B5, con i privilegi operativi già previsti, arresta
e disabilita service/timer `bybit-sync` e `bybit-sync-docker`, poi installa:

```text
<release>/.venv/bin/python -I -c "import subprocess;exec(subprocess.check_output(['git','--no-replace-objects','-C','<release>','show','<SHA>:scripts/cold_deploy.py']))" install <release> --approved-sha <SHA>
```

`<release>` è `/opt/bybit-cold/<SHA>`; non usare direttamente lo script del
working tree. Bootstrap e letture Git dello snapshot ignorano `refs/replace`
con `--no-replace-objects`: l'identità dello SHA approvato resta invariata.
L'installer estrae il Git object tree approvato in una directory
0700 temporanea, usa codice e inventario di quello snapshot e lo elimina.
Scrive quattro unit e quattro maschere legacy; non avvia né ricarica systemd.
B5 esegue daemon-reload e lo stesso bootstrap con `drift <release>`: esito
success, nessun mismatch; unit byte-identiche al rendering, nessun drop-in,
NeedDaemonReload=no, FragmentPath esatto, entrambe le coppie legacy masked/inactive.
Il mount deve esistere sul Dell e contenere i dati cold attesi.

Il timer dati è `bybit-cold.timer`, 03:15 UTC, ieri UTC; quello indipendente di
controllo è `bybit-cold-drift.timer`, 02:45 UTC. B5 abilita/avvia solo dopo la
verifica. Ogni run dati ripete il gate drift prima di Docker. Una divergenza
produce finding F-649 e exit nonzero; B5 tratta il journal come finding operativo,
senza introdurre nuovi topic o credenziali. Non ci sono file riscritti dal servizio o chiavi gestite che richiedano
eccezioni al confronto: le unit sono confrontate per byte.

## Piano e backfill del buco

Usare sempre il bootstrap Git sopra, sostituendo l'azione install con backfill.
Selezioni BTCUSDT,ETHUSDT; giorni chiusi UTC e intervalli espliciti:

```text
backfill <release> --start-date 2026-06-30 --end-date 2026-11-09 --symbols BTCUSDT,ETHUSDT --types trade,klines --intervals 1m,5m,15m --dry-run
backfill <release> --start-date 2026-06-29 --end-date 2026-11-09 --symbols BTCUSDT,ETHUSDT --types orderbook,funding,openinterest,longshortratio --intervals 1m,5m,15m --dry-run
```

Il backfill trade riconosce due intestazioni esatte, la versione originale a dieci colonne e la versione con `RPI` finale. Negli archivi BTCUSDT ed ETHUSDT il 2 aprile 2025 UTC ha l'intestazione originale e il 3 aprile 2025 UTC ha `RPI`. Verifica effettuata con HEAD (200) e GET Range dei primi 8192 byte (206) su entrambi i giorni e simboli. Ogni riga della seconda versione deve avere `RPI` pari a `0` o `1`.

La regola order book scarta soltanto una coda contigua finale, ordinata, con timestamp oltre la fine del giorno UTC richiesto (mezzanotte successiva inclusa). Dopo la prima riga della coda non è ammessa nessuna riga del giorno richiesto. Restano errori le righe prima dell'inizio del giorno, i timestamp non ordinati e gli offset oltre il limite; il file e il manifest non vengono pubblicati.

Il limite di sicurezza predefinito, versionato in `ORDERBOOK_TAIL_MAX_MS`, è 60000 ms (60 s), inclusi. È configurabile tramite `--orderbook-tail-max-ms` (intero positivo) o il parametro omonimo di `execute`; eventuali valori del servizio devono essere versionati nella configurazione condivisa, mai introdotti con override per host. Non è una soglia di validità ricavata da un singolo simbolo: la struttura finale e l'ordine rimangono obbligatori. Nei casi osservati il 2026-11-11, BTCUSDT del 29 giugno 2026 aveva otto righe da +28 a +728 ms; ETHUSDT dello stesso giorno ne aveva undici da +50 a +1051 ms. Il precedente limite di 1000 ms, derivato dal solo BTC, rifiutava ETH per 51 ms. I 60 s costituiscono un limite di sicurezza finito con margine rispetto a entrambi i casi, non una durata osservata.

Gli errori indicano `max_offset_ms` massimo osservato fino al rifiuto, `rows_seen`, `position` (riga a base 1), `tail_start`, `tail_rows` e `limit_ms`; il controllo si arresta alla prima violazione. Lo ZIP pubblicato contiene esclusivamente i record del giorno richiesto. Per compatibilità il manifest conserva `discarded_orderbook_tail_v1`, mantiene in `expected_bytes` la dimensione dell'archivio sorgente e calcola l'hash sullo ZIP pubblicato. Il journal e il JSONL riportano gli scarti dei nuovi download in `discarded_orderbook_tail`. La verifica dei file pubblicati o in cache continua a rifiutare qualunque riga fuori giorno.

Questa modifica interessa `src/`: richiede il rebuild dell'immagine. Build e aggiornamento del manifest di distribuzione sono gestiti da B5 insieme alle PR #17/#18, senza attivazione in questa modifica.

In caso di errore, il record nel journal e `logs/backfill.jsonl` riportano la classe (`error`), il messaggio diagnostico (`error_message`), la serie (`error_type`), il giorno UTC (`error_day`), il simbolo (`error_symbol`) e il percorso relativo (`error_target`). I campi della serie sono nulli per gli errori senza un file associato. Se il log su disco non è scrivibile, il journal riporta anche `log_error`.


Primo piano: 133 giorni, 1064 file. Secondo: 134 giorni, 1072 file.
HEAD soltanto per gli archivi trade/ob200: dimensioni attese reali, errore se
mancanti. Le API riportano dimensioni ignote separatamente. Nessun GET,
creazione di directory o file in dry-run; il gate drift resta obbligatorio.
B5 conserva i due piani e, verificati esiti/date/spazio cold, ripete gli stessi
comandi senza `--dry-run`. Non eseguire contemporaneamente backfill e timer:
il flock sul cold rifiuta una seconda esecuzione, senza conteggi inventati.

## Quando un giorno è completo

Completezza per simbolo/tipo/intervallo/giorno, mai implicita per tutto il dataset.
Riutilizzo solo dopo manifest chiuso, SHA256 e record riverificati; niente append.
File/manifest discordanti sono messi in quarantena con motivo. Staging e rename
atomico sul filesystem cold pubblicano solo dati validati; un errore interrompe
il run e non certifica la serie fallita. Riavviare lo stesso intervallo è
idempotente: le serie già validate risultano skipped.

Archivi: decompressione completa e CRC gzip/ZIP, ID univoci, timestamp ordinati,
simbolo e data UTC corretti, presenza in ogni minuto per BTC/ETH. API: schema,
valori finiti, griglia esatta, klines 1/5/15m, OI/ratio 1d, funding 00/08/16 UTC.
Bybit non pubblica CHECKSUM upstream nei percorsi verificati: B5 ha accettato
CRC più validazione e SHA256 locale; quest'ultimo non è un checksum upstream.

Il journal del runner contiene un solo JSON con esito, date, UTC, digest, SHA
e conteggi validati. Il figlio registra JSONL in `<cold_root>/logs/`.
`counts_status=reported` indica conteggi effettivi; Docker non avviato usa
not_started/null, output non valido unknown/null. Non equiparare null a zero.
Dopo il backfill B5 verifica success e conteggi dei due run, assenza di serie
fallite o quarantene irrisolte, e ripete i comandi: downloaded=0, tutte le serie
skipped e record riverificati. Il primo run del timer deve coprire ieri UTC.

## Annullamento

B5 disabilita i timer cold e sceglie una precedente release/digest approvata
con inventario versionato; rerender, daemon-reload e drift prima di riattivare.
Nessuna cancellazione dei dati cold o riattivazione implicita dello scheduler
GitOps/legacy; il revert richiede una nuova decisione sullo stato runtime.
