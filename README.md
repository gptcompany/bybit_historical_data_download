# ByBit Data Downloader

A high-performance Python package for downloading historical data from ByBit exchange with comprehensive market metrics support.

## Features

- ✅ Download historical trade and orderbook data
- ✅ **NEW: Download open interest data for liquidation analysis**
- ✅ **NEW: Download long-short ratio data for sentiment analysis**
- ✅ **NEW: Download implied volatility data for options analysis**
- ✅ **NEW: Download funding rate history for perpetual contracts**
- ✅ Support for spot and contract markets
- ✅ High-performance parallel downloads using threading
- ✅ Automatic date range splitting for large requests (7-day chunks)
- ✅ Robust error handling and retry logic with exponential backoff
- ✅ File size verification and duplicate detection
- ✅ Comprehensive logging and progress tracking
- ✅ Easy-to-use Python module with clean API

## Project Structure

```
bybit_data_downloader/
├── src/                                    # Core source code
│   ├── bybit_data_downloader/             # Main package
│   │   ├── __init__.py                    # Package initialization
│   │   ├── historical/                    # Historical data downloaders
│   │   │   ├── __init__.py
│   │   │   └── ByBitHistoricalDataDownloader.py
│   │   └── live/                          # Real-time market metrics
│   │       ├── __init__.py
│   │       ├── ByBitUnifiedDownloader.py  # Unified downloader interface
│   │       ├── ByBitOpenInterestDownloader.py
│   │       ├── ByBitLongShortRatioDownloader.py
│   │       ├── ByBitFundingRateDownloader.py
│   │       └── ByBitImpliedVolatilityDownloader.py
│   └── setup.py                           # Package setup configuration
├── tests/                                 # Test suite
│   ├── test_historical_data_comprehensive.py
│   ├── test_unified_downloader.py
│   ├── test_bybit_open_interest.py
│   ├── test_quick_metrics.py
│   ├── test_input_validation.py
│   ├── test_retry_logic.py
│   └── test_backward_compatibility.py
├── scripts/                               # Usage examples and utilities
│   ├── example_download.py               # Basic download example
│   ├── example_all_metrics.py            # Comprehensive metrics demo
│   └── example_open_interest.py          # Open interest analysis
├── docs/                                  # Documentation
│   ├── COMPREHENSIVE_TEST_REPORT.md      # Testing documentation
│   ├── HISTORICAL_DATA_AVAILABILITY.md   # Data availability guide
│   ├── OPEN_INTEREST_DATA_SOURCES.md     # Open interest documentation
│   ├── REFACTOR_CLASSES_PLAN.md          # Architecture documentation
│   ├── SESSION_RECOVERY.md               # Session management
│   └── SESSION_SUMMARY.md                # Usage summaries
├── config/                                # Configuration files (placeholder)
├── requirements.txt                       # Python dependencies
├── .gitignore                            # Git ignore rules
└── README.md                             # This file
```

## Data Directories (Auto-created, Git-ignored)

The following directories are automatically created during execution and excluded from git:

- `downloaded_data/` - Historical trade and orderbook data
- `open_interest_data/` - Open interest historical data
- `funding_rate_data/` - Funding rate historical data
- `long_short_ratio_data/` - Long-short ratio sentiment data
- `implied_volatility_data/` - Options implied volatility data
- `test_output/` - Test result files
- `test_data/` - Test dataset files

## Installation

### From Source
```bash
git clone https://github.com/gptprojectmanager/bybit_historical_data_download.git
cd bybit_historical_data_download
pip install -r requirements.txt
```

### Dependencies
- Python 3.8+
- httpx>=0.24.0

## Quick Start

### Basic Usage

#### Historical Trade/Orderbook Data
```python
from src.bybit_data_downloader import ByBitHistoricalDataDownloader

# Initialize downloader with custom parallel downloads
downloader = ByBitHistoricalDataDownloader(parallel_downloads=10, timeout=30)

# Show help information
downloader.help()

# Fetch available symbols for a market
symbols = downloader.fetch_symbols('spot', 'trade')
print(f"Available symbols: {symbols[:10]}")

# Download historical data
stats = downloader.download_data(
    symbol='BTCUSDT',
    start_date='2025-07-01',
    end_date='2025-07-07',
    biz_type='spot',
    product_id='trade',
    output_dir='./downloaded_data'
)

print(f"Downloaded {stats['downloaded']}/{stats['total_files']} files successfully")
```

#### Market Metrics Data

##### Open Interest Data
```python
from src.bybit_data_downloader import ByBitOpenInterestDownloader

# Initialize open interest downloader
oi_downloader = ByBitOpenInterestDownloader(timeout=30)

# Get current open interest
current_oi = oi_downloader.get_open_interest('BTCUSDT', 'linear')
print(f"Current BTC Open Interest: {current_oi['result']['list'][0]['openInterest']}")

# Download historical open interest (last 30 days)
historical_data = oi_downloader.get_historical_open_interest(
    symbol='BTCUSDT',
    category='linear',
    interval_time='1d',
    days_back=30
)
```

##### Long-Short Ratio Data (Sentiment Analysis)
```python
from src.bybit_data_downloader import ByBitLongShortRatioDownloader

# Initialize long-short ratio downloader
lsr_downloader = ByBitLongShortRatioDownloader(timeout=30)

# Get current sentiment
current_ratio = lsr_downloader.get_long_short_ratio('BTCUSDT', 'linear')
buy_ratio = float(current_ratio['result']['list'][0]['buyRatio'])
sell_ratio = float(current_ratio['result']['list'][0]['sellRatio'])
print(f"Long: {buy_ratio:.1%}, Short: {sell_ratio:.1%}")

# Download historical sentiment data
file_path = lsr_downloader.download_and_save(
    symbol='BTCUSDT',
    category='linear',
    period='1d',
    limit=200
)
```

##### Funding Rate Data
```python
from src.bybit_data_downloader import ByBitFundingRateDownloader

# Initialize funding rate downloader
fr_downloader = ByBitFundingRateDownloader(timeout=30)

# Get current funding rate
current_rate = fr_downloader.get_funding_rate('BTCUSDT', 'linear')
rate = float(current_rate['result']['list'][0]['fundingRate'])
print(f"Current BTC Funding Rate: {rate:.6%}")

# Download historical funding rates
file_path = fr_downloader.download_and_save(
    symbol='BTCUSDT',
    category='linear',
    limit=200
)
```

##### Implied Volatility Data (Options)
```python
from src.bybit_data_downloader import ByBitImpliedVolatilityDownloader

# Initialize implied volatility downloader
iv_downloader = ByBitImpliedVolatilityDownloader(timeout=30)

# Get current implied volatility
current_iv = iv_downloader.get_implied_volatility('BTC', 'option')
print(f"Current BTC Implied Volatility: {current_iv}")

# Download historical implied volatility
file_path = iv_downloader.download_and_save(
    baseCoin='BTC',
    category='option',
    limit=200
)
```

### Unified Downloader Interface

For convenience, you can use the unified interface to access all downloaders:

```python
from src.bybit_data_downloader import ByBitUnifiedDownloader

# Initialize unified downloader
unified = ByBitUnifiedDownloader()

# Access all downloaders through unified interface
historical_data = unified.historical.download_data(...)
open_interest = unified.open_interest.get_open_interest(...)
funding_rates = unified.funding_rate.get_funding_rate(...)
long_short = unified.long_short_ratio.get_long_short_ratio(...)
implied_vol = unified.implied_volatility.get_implied_volatility(...)
```

## Available Examples

Run the example scripts to see the downloaders in action:

```bash
# Basic download example
python scripts/example_download.py

# Comprehensive metrics demo
python scripts/example_all_metrics.py

# Open interest analysis example
python scripts/example_open_interest.py
```

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test categories
python tests/test_historical_data_comprehensive.py
python tests/test_unified_downloader.py
python tests/test_quick_metrics.py
```

## Performance & Reliability

- **High-Performance**: Parallel downloads with configurable concurrency
- **Robust Error Handling**: Automatic retries with exponential backoff
- **Data Integrity**: File size verification and duplicate detection
- **Rate Limiting**: Respects ByBit API rate limits
- **Comprehensive Logging**: Detailed progress tracking and error reporting

## Supported Data Types

### Historical Data
- **Trade Data**: Individual trade records with price, quantity, and timestamp
- **Orderbook Data**: Level 2 order book snapshots at regular intervals

### Market Metrics
- **Open Interest**: Total number of outstanding derivative contracts
- **Long-Short Ratio**: Market sentiment indicator showing long vs short positions
- **Funding Rate**: Periodic payments between long and short positions
- **Implied Volatility**: Options market volatility expectations

### Market Categories
- **Spot**: Spot trading pairs
- **Linear**: USDT-margined perpetual contracts
- **Inverse**: Coin-margined perpetual contracts
- **Option**: Options contracts

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is open source and available under the MIT License.