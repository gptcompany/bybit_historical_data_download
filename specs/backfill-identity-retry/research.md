# Backfill recovery: source evidence and design

## Mapping and selection
`backfill.main` calls `execute`; `execute` wraps `download_file` in `RetryPolicy.run`.
Archive downloads enter `scan` / `_validate`; API downloads enter `api_rows`.
`validate` also invokes the shared scanner for cached and rewritten files.
The selected boundary is cold archive identity and cold API response classification;
legacy live downloader interfaces remain outside this task.

## Observed source cause
Read the public ZIP at
https://quote-saver.bycsi.com/orderbook/linear/BTCUSDT/2026-07-02_BTCUSDT_ob200.data.zip
without invoking the downloader, tests, builds, or services.
At positions 863208 and 863209 the source contains respectively a delta and snapshot:
`ts=1783036800728`, `u=36830300`, `seq=651698590008`, `cts=1783036800726`.
The delta contains 41 bid / 36 ask levels; the snapshot contains 200 / 200.
They are distinct events with the same synthetic identity because `_validate`
omits the event type. Both occur in the permitted midnight tail at +728 ms.
This is an identity bug, not an exact duplicate record at the source.
No source message or topic value is included here.

`ydl-bf1-t1/t2/t3.json` show failures at `properties/retCode/const`.
The old envelope schema requires zero before the retry policy sees an API error.
Those sanitized summaries do not retain the actual upstream numeric retCode;
it is not possible to assert which transient code those historical calls returned.

## Reuse
Reuse SQLite uniqueness, the existing bounded retry budget, Retry-After handling,
retry event emission, atomic publication, CRC/schema checks and UTC coverage.
No new dependencies and no externally copied code.
Official status meanings: https://bybit-exchange.github.io/docs/v5/error
Snapshot/delta semantics: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook

## Rules and plan
1. Include `type` in orderbook identity; same-type duplicates still fail.
2. Validate the API envelope before classifying numeric status; validate the
   existing closed result schema before accepting any successful response.
3. Retry only 429 (load), 10000 (timeout), 10006 (rate limit), 10016 (server error).
   Permanent/unknown codes fail immediately with only the numeric code in logs.
4. Reuse bounded attempts and exponential capped delay, respecting Retry-After;
   API retries wait the configured ceiling so zero jitter cannot cause a busy retry.
5. Restart the whole day on retry, retaining atomic publication and pagination safety.

## Verification
Regression tests were committed before production changes. CI is the only test
execution environment, per operator instruction; no local tests or builds run.
The regression checks source-shaped snapshot/delta collisions inside the day and
in its midnight tail, same-type duplicate rejection, cold-cache reuse, retry
recovery/exhaustion, permanent and unknown codes, waiting with/without headers,
sanitized logs, interrupted pagination, and absence of partial publication.
B5 owns deployment, build/manifest generation and real backfill resumption.
