FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY bybit_unified_cli.py /app/bybit_unified_cli.py
COPY bybit_cli_downloader.py /app/bybit_cli_downloader.py
COPY README.md /app/README.md
COPY CLI_DOCUMENTATION.md /app/CLI_DOCUMENTATION.md
COPY QUICK_START_EXAMPLES.sh /app/QUICK_START_EXAMPLES.sh
COPY src /app/src
COPY scripts /app/scripts

RUN chmod +x /app/scripts/run-sync.sh /app/scripts/run-sync-with-notify.sh /app/QUICK_START_EXAMPLES.sh && \
    mkdir -p /app/data/historical /app/data/market_metrics /app/data/logs /app/data/state /app/data/reports

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["bash", "scripts/run-sync.sh"]
