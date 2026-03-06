# Bybit Data Downloader & Unified CLI

![CI](https://github.com/gptcompany/bybit_historical_data_download/actions/workflows/ci.yml/badge.svg?branch=main)
![Python](https://img.shields.io/badge/python-3.10%2B-blue?style=flat-square&logo=python)
![License](https://img.shields.io/github/license/gptcompany/bybit_historical_data_download?style=flat-square)
![Last Commit](https://img.shields.io/github/last-commit/gptcompany/bybit_historical_data_download?style=flat-square)
![Issues](https://img.shields.io/github/issues/gptcompany/bybit_historical_data_download?style=flat-square)

A high-performance Python package and **complete CLI solution** for downloading historical data from Bybit exchange with comprehensive market metrics support and resume capability.

## ✨ Key Features

- **🚀 Complete CLI Interface**: Command-line downloader similar to binance-history-data-downloader
- **🔄 Resume Capability**: Intelligent download state tracking with SHA256 verification
- **📁 Fixed Directory Structure**: Organized data storage with predictable paths
- **📊 All Data Types**: Historical data (trade, orderbook) + Market metrics (funding, OI, etc.)
- **⚡ High Performance**: Configurable parallel downloads with robust error handling
- **📋 Comprehensive Logging**: Detailed logs, progress tracking, and reports
- **🛠️ Production Ready**: Extensive testing and error handling

## 📦 Project Structure

```
bybit_data_downloader/
├── src/                                    # Core Python library
│   ├── bybit_data_downloader/             # Main package
│   │   ├── __init__.py                    # Package initialization
│   │   ├── historical/                    # Historical data downloaders
│   │   │   └── ByBitHistoricalDataDownloader.py
├── live/                          # Real-time market metrics
│       │       ├── ByBitOpenInterestDownloader.py
│       │       ├── ByBitLongShortRatioDownloader.py
│       │       ├── ByBitFundingRateDownloader.py
│       │       ├── ByBitImpliedVolatilityDownloader.py
│       │       └── ByBitKlineDownloader.py
│       └── setup.py                           # Package setup

├── CLI Interface                          # NEW: Complete CLI solution
│   ├── bybit_unified_cli.py               # Main CLI script
│   ├── CLI_DOCUMENTATION.md               # Complete CLI documentation
│   └── QUICK_START_EXAMPLES.sh            # Automated test examples
├── tests/                                 # Test suite
├── scripts/                               # Python API examples
├── docs/                                  # Documentation & analysis
├── requirements.txt                       # Dependencies
├── Dockerfile                             # Container image for production sync
├── docker-compose.yml                     # Container runtime definition
├── .dockerignore                          # Docker build exclusions
├── deploy/systemd/                        # Optional systemd units for Docker runs
└── data/                                  # CLI download directory (auto-created)
    ├── historical/                        # Historical trade/orderbook data
    ├── market_metrics/                    # Market data (funding, OI, etc.)
    ├── logs/                              # Execution logs
    ├── state/                             # Resume capability
    └── reports/                           # Download reports
```

## 📁 Data Directory Structure (Auto-created)

The CLI creates a fixed, organized directory structure:

```
data/
├── historical/
│   ├── trade/
│   │   ├── spot/{SYMBOL}/           # Spot trade data (CSV.gz)
│   │   └── contract/{SYMBOL}/       # Contract trade data (CSV.gz)
└── orderbook/
│       ├── spot/{SYMBOL}/           # Spot orderbook data (ZIP/JSON)
│       └── contract/{SYMBOL}/       # Contract orderbook Level-500 (ZIP/JSON)
│   └── klines/
│       └── {MARKET}/{SYMBOL}/{INTERVAL}/ # Daily kline data (JSON)
├── market_metrics/

│   ├── funding_rates/               # Funding rate historical data (JSON)
│   ├── open_interest/               # Open interest data (JSON)
│   ├── long_short_ratio/            # Long-short ratio sentiment (JSON)
│   └── implied_volatility/          # Options implied volatility (JSON)
├── logs/                            # Timestamped execution logs
├── state/                           # Resume capability (download_state.json)
└── reports/                         # JSON download reports with statistics
```

## 🚀 Quick Start

### Installation
```bash
cd bybit_data_downloader
pip install -r requirements.txt
```

### Docker (Production)
```bash
# Optional: customize runtime parameters
cp .env.example .env

# Build image
docker compose build bybit-sync

# Run one sync job
docker compose run --rm bybit-sync
```

Data persistence is controlled by `BYBIT_DATA_ROOT` (volume mount in `docker-compose.yml`).
On this host, set `BYBIT_REPO_ROOT` and `BYBIT_DATA_ROOT` in `/etc/downloader-sync.env` and use the
`deploy/systemd/bybit-sync-docker.service` unit, which reads those variables via `EnvironmentFile=`.

### Docker-First Execution (CI)
These services are intended to run **inside Docker** (CI actions launch Docker services, not systemd).
The compose service runs `scripts/run-sync-with-notify.sh`, which captures the original run summary and
sends it to Discord when `DISCORD_WEBHOOK_HISTORY` is set.

#### Migrate Existing systemd Timer To Docker
```bash
# Install docker-based units from this repository
sudo cp deploy/systemd/bybit-sync-docker.service /etc/systemd/system/
sudo cp deploy/systemd/bybit-sync-docker.timer /etc/systemd/system/
sudo systemctl daemon-reload

# Disable old host-python timer/service
sudo systemctl disable --now bybit-sync.timer bybit-sync.service

# Enable new docker timer
sudo systemctl enable --now bybit-sync-docker.timer

# Verify schedule and last run
sudo systemctl status bybit-sync-docker.timer --no-pager
sudo systemctl list-timers --all --no-pager | grep bybit-sync-docker
```

### Notifications
Healthchecks pings are emitted by `cron-wrapper.sh` (monitoring-stack).
Discord delivery is configured via environment (no hardcoded webhook). On this host, the webhook is read
from `/media/sam/1TB/.env` via `dotenvx` (use `DISCORD_WEBHOOK_HISTORY` for run results), and
`DISCORD_NOTIFY_ON_SUCCESS=1` enables per-run success alerts.
To (re)configure the Healthchecks Discord webhook on this host, run:
```bash
dotenvx run -f /media/sam/1TB/.env -- /media/sam/1TB/monitoring-stack/scripts/configure-healthchecks-discord.sh
```

### CLI Usage Examples

**Show help and directory structure:**
```bash
python bybit_unified_cli.py --help
python bybit_unified_cli.py --show-structure
```

**Download BTCUSDT funding rates (365 days):**
```bash
python bybit_unified_cli.py --symbols BTCUSDT --data-types funding --days-back 365
```

**Download historical trade data from earliest available:**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types trade \
  --market contract \
  --start-date 2020-05-01 \
  --end-date 2020-05-10
```

**Download orderbook data (Level-500):**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types orderbook \
  --market contract \
  --start-date 2024-01-01 \
  --end-date 2024-01-03
```

**Download historical klines (OHLCV):**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types klines \
  --market linear \
  --interval 1m \
  --start-date 2024-01-01 \
  --end-date 2024-01-05
```

**Download mixed data types with resume capability:**
```bash
python bybit_unified_cli.py \
  --symbols "BTCUSDT,ETHUSDT" \
  --data-types "trade,funding,openinterest" \
  --market contract \
  --start-date 2024-01-01 \
  --end-date 2024-01-05 \
  --days-back 30
```

### Quick Test Suite
```bash
./QUICK_START_EXAMPLES.sh    # Runs automated test examples
```

## 📊 Supported Data Types & Availability

| Data Type | Markets | Earliest Available | File Format | CLI Flag |
|-----------|---------|-------------------|-------------|----------|
| **Klines (OHLCV)** | Spot, Linear, Inverse | Real-time + historical | JSON | `klines` |
| **Trade Data** | Spot, Contract | 2020-05-01 (Contract), 2022-12-01 (Spot) | CSV.gz | `trade` |
| **Orderbook** | Spot, Contract | 2024-01-01 (Contract) | ZIP/JSON | `orderbook` |
| **Funding Rates** | Linear, Inverse | Real-time + ~3 years | JSON | `funding` |
| **Open Interest** | Linear, Inverse | Real-time + historical | JSON | `openinterest` |
| **Long-Short Ratio** | Linear | Real-time + historical | JSON | `longshortratio` |
| **Implied Volatility** | Option | Real-time + historical | JSON | `impliedvolatility` |

## 🔄 Resume Capability

The CLI automatically resumes interrupted downloads:

- **State Tracking**: `data/state/download_state.json` tracks completed files
- **SHA256 Verification**: Ensures file integrity before skipping
- **Partial Completion**: Continues from last completed file in date range
- **Clear State**: `--clear-state` flag forces re-download

**Resume Example:**
```bash
# First run (interrupted)
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-10

# Second run (automatically resumes)
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-10
# Output: ✅ Download already completed: BTCUSDT2020-05-01.csv.gz
```

## 📋 Comprehensive Reporting

Every CLI execution generates:

- **Execution Log**: `data/logs/bybit_unified_cli_TIMESTAMP.log`
- **Download Report**: `data/reports/download_report_TIMESTAMP.json`

**Sample Report:**
```json
{
  "timestamp": "2025-09-25T00:10:06",
  "summary": {
    "total_downloads": 3,
    "successful": 3,
    "failed": 0,
    "success_rate": "100.0%"
  },
  "results": {
    "BTCUSDT_trade_contract": {
      "status": "completed",
      "stats": {"total_files": 10, "downloaded": 10, "failed": 0}
    }
  }
}
```

## ⚡ Performance & Reliability

- **Parallel Downloads**: Configurable concurrent downloads (default: 5)
- **Timeout Protection**: Configurable request timeouts (default: 60s)
- **Retry Logic**: Automatic retries with exponential backoff
- **Rate Limiting**: Respects Bybit API limits
- **File Integrity**: Size verification and duplicate detection
- **Error Handling**: Comprehensive error recovery

## 🛠️ Python Library API

For programmatic access, use the Python library:

```python
from bybit_data_downloader import ByBitHistoricalDataDownloader
from bybit_data_downloader import ByBitFundingRateDownloader

# Historical data
downloader = ByBitHistoricalDataDownloader(parallel_downloads=5)
stats = downloader.download_data(
    symbol='BTCUSDT',
    start_date='2020-05-01',
    end_date='2020-05-10',
    biz_type='contract',
    product_id='trade'
)

# Funding rates
fr_downloader = ByBitFundingRateDownloader()
file_path = fr_downloader.download_and_save(
    symbol='BTCUSDT',
    category='linear',
    days_back=365
)
```

## 📖 Documentation

- **CLI_DOCUMENTATION.md**: Complete CLI reference with examples
- **docs/HISTORICAL_DATA_AVAILABILITY.md**: Data availability analysis
- **docs/OPEN_INTEREST_DATA_SOURCES.md**: Market data sources guide

## 🧪 Testing & CI/CD

### Local Testing
```bash
# Run Python library tests
python -m pytest tests/ -v

# Run tests with coverage
PYTHONPATH=src:. pytest tests/ -v --cov=src/bybit_data_downloader --cov-report=term --cov-report=xml:coverage.xml
```

### CI/CD Pipeline
This project uses **GitHub Actions** for automated testing and **Codecov** for coverage reporting.

- **Automated Tests**: Runs on every push and pull request to `main`.
- **Security**: Coverage reports are uploaded to Codecov using **OIDC (OpenID Connect)**, eliminating the need for sensitive upload tokens in the repository.
- **Badge Support**: Coverage percentage is dynamically updated via GitHub Actions.

## 🎯 Use Cases

### For Nautilus Trader
- **Order Book Deltas**: Level-500 orderbook data for backtesting
- **Trade Ticks**: Tick-by-tick execution data
- **Funding Rates**: Perpetual contract funding history
- **Quote Ticks**: Derivable from orderbook bid1/ask1 prices

### For Research & Analysis
- **Liquidation Analysis**: Open interest + funding rates
- **Market Sentiment**: Long-short ratios and positioning
- **Options Analysis**: Implied volatility historical data
- **Price Discovery**: Complete trade execution history

### For Production Trading
- **Resume Capability**: Robust data collection pipelines
- **Organized Structure**: Predictable file locations for automation
- **Comprehensive Logging**: Audit trails and error tracking
- **Performance**: High-speed parallel downloads

## 🆚 Comparison with Binance Downloader

| Feature | Bybit Unified CLI | Binance Downloader |
|---------|------------------|-------------------|
| CLI Interface | ✅ Full featured | ✅ Full featured |
| Resume Capability | ✅ SHA256 + State | ✅ Basic resume |
| Directory Structure | ✅ Fixed organized | ✅ Organized |
| Data Types | ✅ Historical + Market | ✅ Historical focus |
| Market Metrics | ✅ Full support | ❌ Limited |
| Error Handling | ✅ Production grade | ✅ Robust |

## 📄 License

This project is open source and available under the MIT License.

---

## 🎉 Status: Production Ready

**Gap successfully filled!** This CLI provides the same functionality as binance-history-data-downloader with enhanced features specifically for Bybit data.
