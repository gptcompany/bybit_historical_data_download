# ByBit Data Downloader

A high-performance Python package for downloading historical data from ByBit exchange.

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

## Installation

### From Source
```bash
git clone https://github.com/AdityaLakkad/bybit_data_downloader.git
cd bybit_data_downloader
pip install -r requirements.txt
```

### Dependencies
- Python 3.8+
- httpx>=0.24.0

## Quick Start

### Basic Usage

#### Historical Trade/Orderbook Data
```python
from bybit_data_downloader import ByBitHistoricalDataDownloader

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
    output_dir='./bybit_data'
)

print(f"Downloaded {stats['downloaded']}/{stats['total_files']} files successfully")
```

#### Market Metrics Data (NEW!)

##### Open Interest Data
```python
from bybit_data_downloader import ByBitOpenInterestDownloader

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
from bybit_data_downloader import ByBitLongShortRatioDownloader

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
    days_back=30,
    output_dir='./sentiment_data'
)
```

##### Implied Volatility Data (Options Analysis)
```python
from bybit_data_downloader import ByBitImpliedVolatilityDownloader

# Initialize implied volatility downloader
iv_downloader = ByBitImpliedVolatilityDownloader(timeout=30)

# Get current volatility
current_iv = iv_downloader.get_implied_volatility('BTC', 'USD', period=30)
if current_iv['result']:
    volatility = float(current_iv['result'][0]['value'])
    print(f"BTC 30-day IV: {volatility:.2%}")

# Download historical volatility
file_path = iv_downloader.download_and_save(
    base_coin='ETH',
    quote_coin='USD',
    period=7,
    days_back=30,
    output_dir='./volatility_data'
)
```

##### Funding Rate History (Perpetual Contracts)
```python
from bybit_data_downloader import ByBitFundingRateDownloader

# Initialize funding rate downloader
fr_downloader = ByBitFundingRateDownloader(timeout=30)

# Get current funding rate
current_rate = fr_downloader.get_funding_rate('BTCUSDT', 'linear')
funding_rate = float(current_rate['result']['list'][0]['fundingRate'])
print(f"Current Funding Rate: {funding_rate:.4%}")

# Download historical funding rates with trend analysis
file_path = fr_downloader.download_and_save(
    symbol='BTCUSDT',
    category='linear',
    days_back=90,
    output_dir='./funding_rate_data'
)

# Analyze funding trends
historical_data = fr_downloader.get_historical_funding_rate('BTCUSDT', 'linear', 30)
trends = fr_downloader.analyze_funding_trends(historical_data)
print(f"Trend: {trends['trend_direction']}, Avg: {trends['recent_average']:.4%}")
```

### Import Options
```python
# Import all downloader classes directly
from bybit_data_downloader import (
    ByBitHistoricalDataDownloader,     # Trade/Orderbook data
    ByBitOpenInterestDownloader,       # Open interest data
    ByBitLongShortRatioDownloader,     # Sentiment analysis
    ByBitImpliedVolatilityDownloader,  # Options volatility
    ByBitFundingRateDownloader         # Funding rates
)

# Import from submodules
from bybit_data_downloader.historical import ByBitHistoricalDataDownloader
from bybit_data_downloader.live import (
    ByBitOpenInterestDownloader,
    ByBitLongShortRatioDownloader,
    ByBitImpliedVolatilityDownloader,
    ByBitFundingRateDownloader
)

# Import entire module
import bybit_data_downloader
historical_downloader = bybit_data_downloader.ByBitHistoricalDataDownloader()
oi_downloader = bybit_data_downloader.ByBitOpenInterestDownloader()
lsr_downloader = bybit_data_downloader.ByBitLongShortRatioDownloader()
iv_downloader = bybit_data_downloader.ByBitImpliedVolatilityDownloader()
fr_downloader = bybit_data_downloader.ByBitFundingRateDownloader()
```

## API Reference

### ByBitHistoricalDataDownloader

Main class for downloading historical trade and orderbook data.

#### Constructor Parameters
- `parallel_downloads` (int): Number of concurrent downloads (1-20 recommended, default: 5)
- `timeout` (int): Request timeout in seconds (default: 30)

#### Methods

##### `help() -> None`
Display comprehensive usage information and parameter details.

##### `fetch_symbols(biz_type: str, product_id: str) -> List[str]`
Fetch available trading symbols for specified market.

**Parameters:**
- `biz_type`: Market type ('spot' or 'contract')
- `product_id`: Data type ('trade' or 'orderbook')

**Returns:** List of available symbol strings

**Raises:** 
- `ValueError`: Invalid parameters
- `httpx.RequestError`: API request failure

##### `download_data(symbol, start_date, end_date, biz_type, product_id, output_dir) -> Dict[str, int]`
Download historical data with automatic chunking and parallel processing.

**Parameters:**
- `symbol` (str): Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
- `start_date` (str): Start date in 'YYYY-MM-DD' format
- `end_date` (str): End date in 'YYYY-MM-DD' format  
- `biz_type` (str): Market type ('spot' or 'contract')
- `product_id` (str): Data type ('trade' or 'orderbook')
- `output_dir` (str): Directory to save files (default: './data')

**Returns:** Dictionary with download statistics:
```python
{
    'total_files': int,    # Total files found
    'downloaded': int,     # Successfully downloaded
    'failed': int         # Failed downloads
}
```

**Features:**
- Automatic 7-day date range splitting (API limitation)
- Parallel downloads using ThreadPoolExecutor
- File size verification and duplicate detection
- Retry logic with exponential backoff (3 attempts)
- Creates organized directory structure: `{output_dir}/{biz_type}/{product_id}/{symbol}/`

### ByBitOpenInterestDownloader

**NEW**: Class for downloading open interest data for liquidation analysis.

#### Constructor Parameters
- `timeout` (int): Request timeout in seconds (default: 30)

#### Methods

##### `help() -> None`
Display comprehensive usage information for open interest functionality.

##### `get_open_interest(symbol, category, interval_time, limit, start_time, end_time) -> Dict`
Get open interest data from Bybit API v5.

**Parameters:**
- `symbol` (str): Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
- `category` (str): Contract type ('linear' or 'inverse')
- `interval_time` (str): Time interval ('5min', '15min', '30min', '1h', '4h', '1d')
- `limit` (int): Number of data points (1-200, default: 50)
- `start_time` (int, optional): Start timestamp in milliseconds
- `end_time` (int, optional): End timestamp in milliseconds

**Returns:** Dictionary with API response containing open interest data

##### `get_historical_open_interest(symbol, category, interval_time, days_back) -> List[Dict]`
Get historical open interest data for a specified number of days with automatic pagination.

**Parameters:**
- `symbol` (str): Trading pair symbol
- `category` (str): Contract type ('linear' or 'inverse')
- `interval_time` (str): Time interval
- `days_back` (int): Number of days to go back from current time

**Returns:** List of all open interest data points

##### `download_and_save(symbol, category, interval_time, days_back, output_file, output_dir) -> str`
Download open interest data and save to JSON file with metadata.

**Parameters:**
- `symbol` (str): Trading pair symbol
- `category` (str): Contract type
- `interval_time` (str): Time interval
- `days_back` (int): Number of days to download
- `output_file` (str, optional): Custom filename
- `output_dir` (str): Output directory (default: './open_interest_data')

**Returns:** Path to saved file

##### `bulk_download(symbols, category, interval_time, days_back, output_dir) -> Dict[str, str]`
Download open interest data for multiple symbols.

**Parameters:**
- `symbols` (List[str]): List of trading pair symbols
- `category` (str): Contract type
- `interval_time` (str): Time interval
- `days_back` (int): Number of days to download
- `output_dir` (str): Output directory

**Returns:** Dictionary mapping symbol to saved file path

### ByBitLongShortRatioDownloader

**NEW**: Class for downloading long-short ratio data for sentiment analysis.

#### Constructor Parameters
- `timeout` (int): Request timeout in seconds (default: 30)

#### Methods

##### `help() -> None`
Display comprehensive usage information for long-short ratio functionality.

##### `get_long_short_ratio(symbol, category, period, limit, start_time, end_time) -> Dict`
Get long-short ratio data from Bybit API v5.

**Parameters:**
- `symbol` (str): Trading pair symbol (e.g., 'BTCUSDT')
- `category` (str): Contract type ('linear' or 'inverse')
- `period` (str): Time period ('5min', '15min', '30min', '1h', '4h', '1d')
- `limit` (int): Number of data points (1-500, default: 50)
- `start_time` (int, optional): Start timestamp in milliseconds
- `end_time` (int, optional): End timestamp in milliseconds

**Returns:** Dictionary with API response containing ratio data

##### `get_historical_long_short_ratio(symbol, category, period, days_back) -> List[Dict]`
Get historical long-short ratio data with automatic pagination.

**Returns:** List of ratio data points with buyRatio and sellRatio values

##### `download_and_save(...) -> str`
Download and save ratio data with sentiment statistics.

##### `bulk_download(...) -> Dict[str, str]`
Download ratio data for multiple symbols.

### ByBitImpliedVolatilityDownloader

**NEW**: Class for downloading implied volatility data for options analysis.

#### Constructor Parameters
- `timeout` (int): Request timeout in seconds (default: 30)

#### Methods

##### `get_implied_volatility(base_coin, quote_coin, period, start_time, end_time) -> Dict`
Get implied volatility data from Bybit API v5.

**Parameters:**
- `base_coin` (str): Base cryptocurrency (e.g., 'BTC', 'ETH')
- `quote_coin` (str): Quote currency (default: 'USD')
- `period` (int): Volatility calculation period in days (e.g., 7, 30)
- `start_time` (int, optional): Start timestamp in milliseconds
- `end_time` (int, optional): End timestamp in milliseconds

**Returns:** Dictionary with volatility data

**Note:** Limited to 30-day historical ranges per API restrictions.

##### `get_historical_implied_volatility(base_coin, quote_coin, period, days_back) -> List[Dict]`
Get historical volatility data (max 30 days).

##### `download_and_save(...) -> str`
Download and save volatility data with statistical analysis.

##### `bulk_download(...) -> Dict[str, str]`
Download volatility data for multiple base coins.

### ByBitFundingRateDownloader

**NEW**: Class for downloading historical funding rate data for perpetual contracts.

#### Constructor Parameters
- `timeout` (int): Request timeout in seconds (default: 30)

#### Methods

##### `get_funding_rate(symbol, category, limit, start_time, end_time) -> Dict`
Get funding rate data from Bybit API v5.

**Parameters:**
- `symbol` (str): Trading pair symbol (e.g., 'BTCUSDT')
- `category` (str): Contract type ('linear' or 'inverse')
- `limit` (int): Number of data points (1-200, default: 200)
- `start_time` (int, optional): Start timestamp in milliseconds
- `end_time` (int, optional): End timestamp in milliseconds

**Returns:** Dictionary with funding rate history

##### `get_historical_funding_rate(symbol, category, days_back) -> List[Dict]`
Get historical funding rates with automatic pagination.

##### `download_and_save(...) -> str`
Download and save funding rate data with trend statistics.

##### `analyze_funding_trends(data) -> Dict`
Analyze funding rate trends for market insights.

**Returns:** Dictionary with trend analysis including direction, magnitude, and streaks

##### `bulk_download(...) -> Dict[str, str]`
Download funding rate data for multiple symbols.

## Supported Markets

### Historical Data (Trade/Orderbook)

| biz_type | product_id | Description |
|----------|------------|-------------|
| spot | trade | Spot market trading data |
| spot | orderbook | Spot market orderbook data |
| contract | trade | Futures/Derivatives trading data |
| contract | orderbook | Futures/Derivatives orderbook data |

### Market Metrics Data

#### Open Interest Data
| category | Description | Examples |
|----------|-------------|----------|
| linear | USDT/USDC perpetual contracts | BTCUSDT, ETHUSDT, ADAUSDT |
| inverse | Coin-margined contracts | BTCUSD, ETHUSD, EOSUSD |

**Supported Intervals:** 5min, 15min, 30min, 1h, 4h, 1d

#### Long-Short Ratio Data
| category | Description | Data Points |
|----------|-------------|-------------|
| linear | USDT/USDC perpetual contracts | buyRatio, sellRatio |
| inverse | Coin-margined contracts | buyRatio, sellRatio |

**Supported Periods:** 5min, 15min, 30min, 1h, 4h, 1d
**Interpretation:** buyRatio + sellRatio = 1.0 (percentage of long vs short positions)

#### Implied Volatility Data
| category | Description | Examples |
|----------|-------------|----------|
| option | Options contracts only | BTC/USD, ETH/USD |

**Supported Base Coins:** BTC, ETH, SOL, ADA, DOT, LINK, UNI, AVAX
**Supported Periods:** 7, 14, 30, 60, 90 days
**Limitations:** Max 30-day historical range per request

#### Funding Rate Data
| category | Description | Update Frequency |
|----------|-------------|------------------|
| linear | USDT/USDC perpetual contracts | Every 8 hours |
| inverse | Coin-margined perpetual contracts | Every 8 hours |

**Supported Symbols:** All perpetual contracts
**Data Points:** fundingRate, fundingRateTimestamp
**Interpretation:** Positive = Longs pay shorts, Negative = Shorts pay longs

## File Organization

### Historical Data Files
Downloaded files are automatically organized in this structure:
```
output_dir/
├── spot/
│   ├── trade/
│   │   └── BTCUSDT/
│   │       ├── BTCUSDT_2025-07-01_trade.csv.gz
│   │       └── BTCUSDT_2025-07-02_trade.csv.gz
│   └── orderbook/
│       └── BTCUSDT/
└── contract/
    ├── trade/
    └── orderbook/
```

### Market Metrics Data Files
All market metrics are saved as JSON with comprehensive metadata:

```
market_data/
├── open_interest_data/
│   ├── BTCUSDT_linear_1d_30d_oi_20250923_001153.json
│   └── ETHUSDT_linear_4h_7d_oi_20250923_001200.json
├── sentiment_data/
│   ├── BTCUSDT_linear_1d_30d_longshortratio_20250923_002000.json
│   └── ETHUSDT_linear_4h_7d_longshortratio_20250923_002030.json
├── volatility_data/
│   ├── BTCUSD_7d_iv_30d_20250923_002100.json
│   └── ETHUSD_30d_iv_30d_20250923_002130.json
└── funding_rate_data/
    ├── BTCUSDT_linear_fundingrate_90d_20250923_002200.json
    └── ETHUSDT_linear_fundingrate_90d_20250923_002230.json
```

**Universal File Structure:**
```json
{
  "metadata": {
    "symbol": "BTCUSDT",
    "category": "linear",
    "metric_type": "open_interest|long_short_ratio|implied_volatility|funding_rate",
    "total_data_points": 30,
    "download_timestamp": "2025-09-23T00:11:59.744614",
    "earliest_data": "2025-09-21T01:00:00",
    "latest_data": "2025-08-30T01:00:00",
    "statistics": {
      "avg_value": 0.123,
      "max_value": 0.456,
      "min_value": 0.001
    }
  },
  "data": [
    {
      "value_field": "metric_specific_value",
      "timestamp": "1756512000000"
    }
  ]
}
```

**Metric-Specific Data Fields:**
- **Open Interest**: `openInterest`, `timestamp`
- **Long-Short Ratio**: `buyRatio`, `sellRatio`, `timestamp`
- **Implied Volatility**: `value`, `time`, `period`
- **Funding Rate**: `fundingRate`, `fundingRateTimestamp`

## Advanced Features

### Error Handling
- Automatic retry with exponential backoff
- File size verification against API metadata
- Graceful handling of network timeouts
- Comprehensive logging for debugging

### Performance Optimization
- Parallel downloads using ThreadPoolExecutor
- Configurable concurrency levels
- Efficient memory usage with streaming downloads
- Smart duplicate file detection

### Date Range Management
- Automatic splitting of large date ranges into 7-day chunks
- Validation of date formats and logical ranges
- Efficient batch processing of multiple date ranges

## Examples

### Example 1: Basic Download
```python
from bybit_data_downloader import BybitDataDownloader

downloader = BybitDataDownloader()
stats = downloader.download_data(
    symbol='BTCUSDT',
    start_date='2025-07-01', 
    end_date='2025-07-07',
    biz_type='spot',
    product_id='trade',
    output_dir='./data'
)
```

### Example 2: High-Performance Bulk Download
```python
downloader = BybitDataDownloader(parallel_downloads=15, timeout=60)

# Download multiple months of data (automatically chunked)
stats = downloader.download_data(
    symbol='ETHUSDT',
    start_date='2025-01-01',
    end_date='2025-06-30', 
    biz_type='spot',
    product_id='trade',
    output_dir='/data/crypto'
)
```

### Example 3: Explore Available Markets
```python
downloader = BybitDataDownloader()

# Get all spot trading symbols
spot_symbols = downloader.fetch_symbols('spot', 'trade')
print(f"Spot trading symbols: {len(spot_symbols)}")

# Get contract symbols
contract_symbols = downloader.fetch_symbols('contract', 'trade')  
print(f"Contract symbols: {len(contract_symbols)}")
```

**Example Files:**
- `example_download.py` - Historical trade/orderbook data examples
- `example_open_interest.py` - Open interest data examples
- `example_all_metrics.py` - Comprehensive test of all market metrics
- `test_quick_metrics.py` - Quick verification test

## Development

### Running Tests
```bash
python3 test_import.py
```

### Project Structure
```
bybit_data_downloader/
├── bybit_data_downloader/
│   ├── __init__.py
│   ├── historical/
│   │   ├── __init__.py
│   │   └── ByBitDataDownloader.py    # Main implementation
│   └── live/
│       └── __init__.py               # Future live data features
├── example_download.py               # Working example
├── test_import.py                    # Import verification
├── setup.py                         # Package installation
├── requirements.txt                  # Dependencies
└── README.md
```

## Technical Details

### Threading Model
- Uses `ThreadPoolExecutor` for parallel downloads
- Configurable worker thread count
- Thread-safe logging and error handling

### API Interaction
- Direct integration with ByBit's historical data API
- Proper HTTP headers mimicking browser requests
- Automatic rate limiting through thread pool size

### Data Integrity
- SHA/size verification for downloaded files
- Automatic cleanup of corrupted downloads
- Resume capability for interrupted downloads

## Troubleshooting

### Common Issues
1. **Network Timeouts**: Increase `timeout` parameter
2. **Too Many Failures**: Reduce `parallel_downloads` count
3. **Disk Space**: Monitor free space for large date ranges
4. **API Rate Limits**: Use default `parallel_downloads=5` or lower

### Logging
Enable detailed logging to diagnose issues:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit changes (`git commit -am 'Add new feature'`)
4. Push to branch (`git push origin feature/new-feature`)
5. Create Pull Request

## Changelog

### Version 1.2.0 (Latest)
- **NEW**: Added long-short ratio data download for sentiment analysis
- **NEW**: Added implied volatility data download for options analysis
- **NEW**: Added funding rate history download for perpetual contracts
- **NEW**: Comprehensive market metrics suite (4 total downloaders)
- **NEW**: Advanced trend analysis for funding rates
- **NEW**: Sentiment statistics for long-short ratios
- **NEW**: Volatility statistics for implied volatility data
- **NEW**: Universal JSON metadata structure for all metrics
- **NEW**: Bulk download support for all metric types
- Enhanced rate limiting and error handling across all downloaders
- Complete test suite with historical data verification
- Professional-grade documentation with usage examples

### Version 1.1.0
- **NEW**: Added open interest data download functionality
- **NEW**: Support for linear and inverse contracts
- **NEW**: Historical open interest with automatic pagination
- **NEW**: Bulk download for multiple symbols
- **NEW**: JSON export with comprehensive metadata
- Enhanced documentation with open interest examples

### Version 1.0.0
- Initial release with historical data download
- Synchronous implementation with threading
- Automatic date range chunking
- Robust error handling and retry logic
- File organization and integrity verification
