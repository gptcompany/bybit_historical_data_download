#!/bin/bash
# Bybit data sync — replaces N8N workflow qqOUaacTGFPWtRr4
# Runs 4 sequential download calls (idempotent via SHA256 state)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

START_DATE="${START_DATE:-2020-05-01}"
END_DATE="${END_DATE:-$(date -d "yesterday" +%Y-%m-%d)}"
DAYS_BACK="${DAYS_BACK:-365}"
PYTHON="${PYTHON:-python3}"
SYMBOLS="${SYMBOLS:-BTCUSDT,ETHUSDT}"

echo "[$(date -Iseconds)] Bybit sync: ${START_DATE} → ${END_DATE}, days_back=${DAYS_BACK}"

# Klines data (linear contracts) - 1m, 5m, 15m
echo "[$(date -Iseconds)] Syncing klines (1m)..."
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types klines --market linear --interval 1m --start-date "$START_DATE" --end-date "$END_DATE"

echo "[$(date -Iseconds)] Syncing klines (5m)..."
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types klines --market linear --interval 5m --start-date "$START_DATE" --end-date "$END_DATE"

echo "[$(date -Iseconds)] Syncing klines (15m)..."
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types klines --market linear --interval 15m --start-date "$START_DATE" --end-date "$END_DATE"

# Trade data (contract market)
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types trade --market contract --start-date "$START_DATE" --end-date "$END_DATE"

# Funding rate
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types funding --days-back "$DAYS_BACK"

# Open interest
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types openinterest --days-back "$DAYS_BACK"

# Long/short ratio
$PYTHON bybit_unified_cli.py --symbols "$SYMBOLS" --data-types longshortratio --days-back "$DAYS_BACK"

echo "[$(date -Iseconds)] Bybit sync completed"
