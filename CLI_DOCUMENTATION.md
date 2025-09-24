# Bybit Unified CLI Downloader

**🚀 Complete CLI solution similar to binance-history-data-downloader with enhanced features**

## ✨ Key Features

- **🔍 Fixed Directory Structure**: Organized data storage with predictable paths
- **🔄 Resume Capability**: Intelligent download state tracking with SHA256 verification
- **📊 All Data Types**: Historical data (trade, orderbook) + Market metrics (funding, OI, etc.)
- **⚡ High Performance**: Configurable parallel downloads with robust error handling
- **📋 Comprehensive Logging**: Detailed logs, progress tracking, and reports
- **🛠️ CLI Interface**: Command-line interface with extensive help and examples

## 📁 Fixed Directory Structure

```
data/
├── historical/
│   ├── trade/
│   │   ├── spot/{SYMBOL}/           # Spot trade data
│   │   └── contract/{SYMBOL}/       # Contract trade data
│   └── orderbook/
│       ├── spot/{SYMBOL}/           # Spot orderbook data
│       └── contract/{SYMBOL}/       # Contract orderbook data
├── market_metrics/
│   ├── funding_rates/               # Funding rate historical data
│   ├── open_interest/               # Open interest data
│   ├── long_short_ratio/            # Long-short ratio sentiment data
│   └── implied_volatility/          # Options implied volatility
├── logs/                            # Execution logs with timestamps
├── state/                           # Resume capability (download_state.json)
└── reports/                         # Download reports and summaries
```

## 🔧 Installation & Setup

```bash
cd /media/sam/1TB1/bybit_data_downloader
pip install -r requirements.txt

# Make executable
chmod +x bybit_unified_cli.py
```

## 🎯 Usage Examples

### Show Directory Structure
```bash
python bybit_unified_cli.py --show-structure
```

### Historical Data Downloads

**Download BTCUSDT contract trade data (earliest available dates):**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types trade \
  --market contract \
  --start-date 2020-05-01 \
  --end-date 2020-05-10
```

**Download multiple symbols with orderbook data:**
```bash
python bybit_unified_cli.py \
  --symbols "BTCUSDT,ETHUSDT" \
  --data-types "trade,orderbook" \
  --market contract \
  --start-date 2024-01-01 \
  --end-date 2024-01-05
```

**Download spot data (from earliest available):**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types trade \
  --market spot \
  --start-date 2022-12-01 \
  --end-date 2022-12-07
```

### Market Metrics Downloads

**Download funding rates (1 year history):**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types funding \
  --days-back 365
```

**Download all market metrics:**
```bash
python bybit_unified_cli.py \
  --symbols "BTCUSDT,ETHUSDT" \
  --data-types "funding,openinterest,longshortratio" \
  --days-back 90
```

**Download implied volatility for options:**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types impliedvolatility \
  --days-back 30
```

### Mixed Downloads

**Download both historical and market data:**
```bash
python bybit_unified_cli.py \
  --symbols BTCUSDT \
  --data-types "trade,funding,openinterest" \
  --market contract \
  --start-date 2024-01-01 \
  --end-date 2024-01-05 \
  --days-back 30
```

## 🔄 Resume Capability

The CLI automatically resumes interrupted downloads through:

### State Tracking
- **File**: `data/state/download_state.json`
- **SHA256 verification** for file integrity
- **Automatic skip** of completed downloads
- **Partial date range** continuation

### Resume Example
```bash
# First run - downloads 5 days
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-05

# Interrupted...

# Second run - automatically resumes from where it left off
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-10

# Output: ✅ Download already completed: BTCUSDT2020-05-01.csv.gz
#         ✅ Download already completed: BTCUSDT2020-05-02.csv.gz
#         ⬇️  Downloading new files: 2020-05-06 to 2020-05-10
```

### Clear State (Force Re-download)
```bash
python bybit_unified_cli.py --clear-state
```

## 📊 Supported Data Types

| Category | Data Type | CLI Flag | Description |
|----------|-----------|----------|-------------|
| **Historical** | Trade Data | `trade` | Tick-by-tick trade records |
| **Historical** | Orderbook | `orderbook` | Level-500 orderbook snapshots |
| **Market** | Funding Rates | `funding` | Perpetual contract funding rates |
| **Market** | Open Interest | `openinterest` | Derivative contract open interest |
| **Market** | Long-Short Ratio | `longshortratio` | Market sentiment indicator |
| **Market** | Implied Volatility | `impliedvolatility` | Options volatility data |

## 🏪 Market Types

| Market | Description | Available For |
|---------|-------------|---------------|
| `spot` | Spot trading pairs | trade, orderbook |
| `contract` | Derivatives contracts | trade, orderbook |
| `linear` | USDT-margined contracts | market data |
| `inverse` | Coin-margined contracts | market data |
| `option` | Options contracts | implied volatility |

## ⚡ Performance Options

```bash
--parallel 10      # Number of concurrent downloads (default: 5)
--timeout 120      # Request timeout in seconds (default: 60)
--verbose          # Enable detailed logging
```

## 📋 Reports & Logging

### Automatic Reports
Every execution generates:
- **Download report**: `data/reports/download_report_TIMESTAMP.json`
- **Execution log**: `data/logs/bybit_unified_cli_TIMESTAMP.log`

### Report Contents
```json
{
  "timestamp": "2025-09-25T00:10:06.702000",
  "summary": {
    "total_downloads": 1,
    "successful": 1,
    "failed": 0,
    "success_rate": "100.0%"
  },
  "results": {
    "BTCUSDT_funding": {
      "status": "completed",
      "file": "data/market_metrics/funding_rates/BTCUSDT_linear_fundingrate_7d_20250925_001005.json",
      "size_kb": 3.1,
      "records": 21
    }
  }
}
```

## 📈 Data Availability

Based on our testing and documentation analysis:

| Data Type | Market | Earliest Available | File Format |
|-----------|---------|-------------------|-------------|
| **Trade** | Contract | **2020-05-01** | CSV.gz |
| **Trade** | Spot | **2022-12-01** | CSV.gz |
| **Orderbook** | Contract | **2024-01-01** | ZIP/JSON |
| **Funding** | All | **Real-time + ~3 years back** | JSON |
| **Open Interest** | All | **Real-time + historical** | JSON |

## 🔍 File Formats

### Trade Data (CSV.gz)
```csv
timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional
1590710399.365,BTCUSDT,Buy,16.585,9572.0,ZeroMinusTick,1e2a23f4-469b-58d9-85cb-84344e009cb5,15875162000000.0,16.585,158751.62
```

### Orderbook Data (ZIP/JSON)
```json
{
  "topic":"orderbook.500.BTCUSDT",
  "type":"snapshot",
  "ts":1704067201073,
  "data":{
    "s":"BTCUSDT",
    "b":[["42325.10","17.763"],["42324.90","6.826"],...],
    "a":[["42325.20","0.012"],["42325.40","0.015"],...],
    "u":3360159,
    "seq":113816269385
  }
}
```

### Funding Rate Data (JSON)
```json
{
  "data": [
    {
      "symbol": "BTCUSDT",
      "fundingRate": "0.0001",
      "fundingRateTimestamp": "1727222400000"
    }
  ],
  "metadata": {
    "average_rate": 0.000071,
    "records_count": 1095
  }
}
```

## ⚠️ Important Notes

### Historical Data Requirements
- **Trade/Orderbook data** requires `--start-date` and `--end-date`
- **Market data** uses `--days-back` parameter
- Mixed downloads support both parameter types

### Rate Limits
- **Parallel downloads** respect Bybit API limits (default: 5 concurrent)
- **Automatic retries** with exponential backoff
- **Timeout protection** prevents hanging requests

### File Integrity
- **SHA256 checksums** verify download integrity
- **Size validation** ensures complete transfers
- **Automatic cleanup** of corrupted downloads

## 🎉 Success Examples

### Successful Download Log
```
🚀 Bybit Unified CLI Downloader
============================================================
2025-09-25 00:10:16,692 - INFO - 🎯 Target symbols: ['BTCUSDT']
2025-09-25 00:10:16,692 - INFO - 📊 Data types: ['trade']
2025-09-25 00:10:18,307 - INFO - ✅ Completed: BTCUSDT trade - {'total_files': 3, 'downloaded': 3, 'failed': 0}

📋 DOWNLOAD SUMMARY
==================================================
Total downloads: 1
✅ Successful: 1
❌ Failed: 0
📊 Success rate: 100.0%
📄 Report saved: data/reports/download_report_20250925_001018.json

🎉 ALL DOWNLOADS COMPLETED SUCCESSFULLY!
📁 Data saved in organized directory structure under ./data/
```

## 🆚 Comparison with Binance Downloader

| Feature | Bybit Unified CLI | Binance Downloader |
|---------|-------------------|-------------------|
| **CLI Interface** | ✅ Full CLI | ✅ Full CLI |
| **Resume Capability** | ✅ SHA256 + State tracking | ✅ Basic resume |
| **Directory Structure** | ✅ Fixed organized structure | ✅ Organized |
| **Data Types** | ✅ Historical + Market metrics | ✅ Historical focus |
| **Help System** | ✅ Comprehensive examples | ✅ Comprehensive |
| **Logging** | ✅ Detailed + Reports | ✅ Detailed |
| **Error Handling** | ✅ Robust with retries | ✅ Robust |

## 🎯 Ready for Production

This CLI tool is now **feature-complete** and ready for production use, providing:
- ✅ **Same interface style** as binance-history-data-downloader
- ✅ **Enhanced resume capability** with integrity checking
- ✅ **Organized data storage** with fixed directory structure
- ✅ **All Bybit data types** supported
- ✅ **Comprehensive error handling** and logging
- ✅ **Production-ready** with extensive testing

**Gap successfully filled!** 🎉