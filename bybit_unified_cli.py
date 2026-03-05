#!/usr/bin/env python3
"""
Bybit Unified CLI Downloader - Complete CLI interface for Bybit data downloads
Similar to binance-history-data-downloader with enhanced features

Usage: python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-10

Features:
- Fixed directory structure for organized data storage
- Resume capability with download state tracking
- Comprehensive logging and error handling
- Support for all Bybit data types
- Progress tracking and reporting
"""

import argparse
import sys
import os
import json
import logging
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set, Any
import time

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'src'))

try:
    from bybit_data_downloader import (
        ByBitHistoricalDataDownloader,
        ByBitFundingRateDownloader,
        ByBitOpenInterestDownloader,
        ByBitLongShortRatioDownloader,
        ByBitImpliedVolatilityDownloader,
        ByBitKlineDownloader
    )
except ImportError as e:
    print(f"❌ Import error: {e}")
    print("Installing requirements...")
    os.system("pip install -r requirements.txt")
    from bybit_data_downloader import (
        ByBitHistoricalDataDownloader,
        ByBitFundingRateDownloader,
        ByBitOpenInterestDownloader,
        ByBitLongShortRatioDownloader,
        ByBitImpliedVolatilityDownloader,
        ByBitKlineDownloader
    )

class BybitUnifiedCLI:
    """Unified CLI for Bybit data downloads with resume capability."""

    # Fixed directory structure
    BASE_DATA_DIR = "data"
    DIRECTORIES = {
        'historical': 'data/historical',
        'market_metrics': 'data/market_metrics',
        'logs': 'data/logs',
        'state': 'data/state',
        'reports': 'data/reports',
        'trade_spot': 'data/historical/trade/spot',
        'trade_contract': 'data/historical/trade/contract',
        'orderbook_spot': 'data/historical/orderbook/spot',
        'orderbook_contract': 'data/historical/orderbook/contract',
        'klines': 'data/historical/klines',
        'funding_rates': 'data/market_metrics/funding_rates',
        'open_interest': 'data/market_metrics/open_interest',
        'long_short_ratio': 'data/market_metrics/long_short_ratio',
        'implied_volatility': 'data/market_metrics/implied_volatility'
    }

    # Supported data types
    HISTORICAL_DATA_TYPES = ['trade', 'orderbook', 'klines']
    MARKET_DATA_TYPES = ['funding', 'openinterest', 'longshortratio', 'impliedvolatility']
    ALL_DATA_TYPES = HISTORICAL_DATA_TYPES + MARKET_DATA_TYPES
    MARKET_TYPES = ['spot', 'contract', 'linear', 'inverse', 'option']

    VALID_INTERVALS = ['1m', '3m', '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d', '1w', '1mo']

    def __init__(self):
        """Initialize CLI with logging and directory setup."""
        self.logger = logging.getLogger(__name__) # Default logger
        self.setup_directories()
        self.setup_logging()
        self.state_file = os.path.join(self.DIRECTORIES['state'], 'download_state.json')
        self.load_state()

    def setup_directories(self):
        """Create fixed directory structure."""
        for dir_name, dir_path in self.DIRECTORIES.items():
            os.makedirs(dir_path, exist_ok=True)

        self.logger = self.setup_logging()
        if hasattr(self, 'logger'):
            self.logger.info(f"Created directory structure: {list(self.DIRECTORIES.keys())}")

    def setup_logging(self):
        """Setup comprehensive logging system."""
        log_filename = f"bybit_unified_cli_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_path = os.path.join(self.DIRECTORIES['logs'], log_filename)

        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_path),
                logging.StreamHandler()
            ]
        )

        logger = logging.getLogger(__name__)
        logger.info("=== Bybit Unified CLI Started ===")
        logger.info(f"Log file: {log_path}")
        return logger

    def load_state(self):
        """Load download state for resume capability."""
        self.download_state = {}
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r') as f:
                    self.download_state = json.load(f)
                self.logger.info(f"Loaded download state: {len(self.download_state)} entries")
            except Exception as e:
                self.logger.warning(f"Could not load state file: {e}")
                self.download_state = {}

    def save_state(self):
        """Save download state for resume capability."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.download_state, f, indent=2)
        except Exception as e:
            self.logger.error(f"Could not save state file: {e}")

    def get_file_hash(self, file_path: str) -> Optional[str]:
        """Calculate SHA256 hash of file for integrity checking."""
        if not os.path.exists(file_path):
            return None
        try:
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(chunk)
            return sha256_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating hash for {file_path}: {e}")
            return None

    def is_download_complete(self, key: str, file_path: str) -> bool:
        """Check if download is already completed and valid."""
        if key not in self.download_state:
            return False

        state_entry = self.download_state[key]

        # Check if file exists
        if not os.path.exists(file_path):
            self.logger.debug(f"File not found: {file_path}")
            return False

        # Check file size
        current_size = os.path.getsize(file_path)
        if current_size != state_entry.get('file_size', -1):
            self.logger.debug(f"File size mismatch: {current_size} vs {state_entry.get('file_size')}")
            return False

        # Check hash if available
        if 'file_hash' in state_entry:
            current_hash = self.get_file_hash(file_path)
            if current_hash != state_entry['file_hash']:
                self.logger.debug(f"File hash mismatch for {file_path}")
                return False

        # Check completion status
        if not state_entry.get('completed', False):
            return False

        self.logger.info(f"✅ Download already completed: {os.path.basename(file_path)}")
        return True

    def mark_download_complete(self, key: str, file_path: str, metadata: Dict):
        """Mark download as complete in state."""
        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        file_hash = self.get_file_hash(file_path) if os.path.exists(file_path) else None

        self.download_state[key] = {
            'completed': True,
            'file_path': file_path,
            'file_size': file_size,
            'file_hash': file_hash,
            'completed_at': datetime.now().isoformat(),
            'metadata': metadata
        }
        self.save_state()

    def download_historical_data(self, symbols: List[str], data_types: List[str],
                                market: str, start_date: str, end_date: str,
                                parallel: int = 5, timeout: int = 60,
                                interval: str = '1m') -> Dict:
        """Download historical trade/orderbook/klines data."""

        self.logger.info(f"🚀 Starting historical data download")
        self.logger.info(f"📊 Symbols: {symbols}")
        self.logger.info(f"📈 Data types: {data_types}")
        self.logger.info(f"🏪 Market: {market}")
        self.logger.info(f"📅 Date range: {start_date} to {end_date}")
        if 'klines' in data_types:
            self.logger.info(f"⏱️  Interval: {interval}")

        results = {}

        # Initialize downloaders
        historical_downloader = ByBitHistoricalDataDownloader(parallel_downloads=parallel, timeout=timeout)
        kline_downloader = ByBitKlineDownloader(timeout=timeout)

        for symbol in symbols:
            for data_type in data_types:
                if data_type not in self.HISTORICAL_DATA_TYPES:
                    self.logger.warning(f"❌ Invalid historical data type: {data_type}")
                    continue

                if data_type == 'klines':
                    # For klines, 'contract' maps to 'linear'
                    kline_market = 'linear' if market == 'contract' else market
                    
                    # Create state key including interval
                    state_key = f"historical_{symbol}_klines_{kline_market}_{interval}_{start_date}_{end_date}"
                    
                    try:
                        self.logger.info(f"⬇️  Downloading {symbol} klines ({kline_market}) - {interval} from {start_date} to {end_date}")
                        
                        stats = kline_downloader.download_range(
                            symbol=symbol,
                            start_date=start_date,
                            end_date=end_date,
                            interval=interval,
                            category=kline_market,
                            output_dir=self.DIRECTORIES['klines']
                        )
                        
                        # Note: download_range already handles daily idempotency
                        # but we mark the overall task as complete in state
                        if stats.get('successful_days', 0) > 0:
                            self.mark_download_complete(state_key, "N/A", {
                                'symbol': symbol,
                                'data_type': 'klines',
                                'market': kline_market,
                                'interval': interval,
                                'date_range': f"{start_date}_to_{end_date}",
                                'stats': stats
                            })
                            
                        results[f"{symbol}_klines_{interval}_{kline_market}"] = {"status": "completed", "stats": stats}
                        self.logger.info(f"✅ Completed: {symbol} klines {interval} - {stats}")
                        
                    except Exception as e:
                        error_msg = f"❌ Failed to download {symbol} klines: {e}"
                        self.logger.error(error_msg)
                        results[f"{symbol}_klines_{interval}_{kline_market}"] = {"status": "failed", "error": str(e)}
                    
                    continue

                # Original logic for trade/orderbook
                # Determine output directory based on data type and market
                if data_type == 'trade':
                    if market == 'spot':
                        output_dir = os.path.join(self.DIRECTORIES['trade_spot'], symbol)
                    else:
                        output_dir = os.path.join(self.DIRECTORIES['trade_contract'], symbol)
                elif data_type == 'orderbook':
                    if market == 'spot':
                        output_dir = os.path.join(self.DIRECTORIES['orderbook_spot'], symbol)
                    else:
                        output_dir = os.path.join(self.DIRECTORIES['orderbook_contract'], symbol)

                os.makedirs(output_dir, exist_ok=True)

                # Create state key for resume capability
                state_key = f"historical_{symbol}_{data_type}_{market}_{start_date}_{end_date}"

                # Check if already downloaded
                expected_files = self.get_expected_historical_files(symbol, data_type, market,
                                                                 start_date, end_date, output_dir)
                all_complete = all(self.is_download_complete(f"{state_key}_{os.path.basename(f)}", f)
                                 for f in expected_files)

                if all_complete and expected_files:
                    self.logger.info(f"✅ Historical data already complete: {symbol} {data_type} {market}")
                    results[f"{symbol}_{data_type}_{market}"] = {"status": "already_completed", "files": len(expected_files)}
                    continue

                # Download data
                try:
                    self.logger.info(f"⬇️  Downloading {symbol} {data_type} ({market}) from {start_date} to {end_date}")

                    stats = historical_downloader.download_data(
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        biz_type=market,
                        product_id=data_type,
                        output_dir=output_dir
                    )

                    # Mark successful downloads as complete
                    if stats.get('downloaded', 0) > 0:
                        downloaded_files = self.find_downloaded_files(output_dir, symbol, start_date, end_date)
                        for file_path in downloaded_files:
                            file_key = f"{state_key}_{os.path.basename(file_path)}"
                            self.mark_download_complete(file_key, file_path, {
                                'symbol': symbol,
                                'data_type': data_type,
                                'market': market,
                                'date_range': f"{start_date}_to_{end_date}"
                            })

                    results[f"{symbol}_{data_type}_{market}"] = {"status": "completed", "stats": stats}
                    self.logger.info(f"✅ Completed: {symbol} {data_type} - {stats}")

                except Exception as e:
                    error_msg = f"❌ Failed to download {symbol} {data_type} ({market}): {e}"
                    self.logger.error(error_msg)
                    results[f"{symbol}_{data_type}_{market}"] = {"status": "failed", "error": str(e)}

        return results

    def get_expected_historical_files(self, symbol: str, data_type: str, market: str,
                                    start_date: str, end_date: str, output_dir: str) -> List[str]:
        """Get list of expected files for date range (for resume checking)."""
        expected_files = []

        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        current = start

        while current <= end:
            date_str = current.strftime('%Y-%m-%d')

            # Different file naming conventions for different data types/markets
            if data_type == 'trade':
                if market == 'spot':
                    filename = f"{symbol}_{date_str.replace('-', '')}.csv.gz"
                else:
                    filename = f"{symbol}{date_str.replace('-', '')}.csv.gz"
            elif data_type == 'orderbook':
                filename = f"{date_str}_{symbol}_ob500.data.zip"

            expected_files.append(os.path.join(output_dir, filename))
            current += timedelta(days=1)

        return expected_files

    def find_downloaded_files(self, output_dir: str, symbol: str, start_date: str, end_date: str) -> List[str]:
        """Find files that were actually downloaded."""
        downloaded_files = []
        if os.path.exists(output_dir):
            for file in os.listdir(output_dir):
                file_path = os.path.join(output_dir, file)
                if os.path.isfile(file_path) and symbol.upper() in file.upper():
                    downloaded_files.append(file_path)
        return downloaded_files

    def download_market_data(self, symbols: List[str], data_types: List[str],
                           days_back: int = 30) -> Dict:
        """Download market metrics data (funding, OI, etc.)."""

        self.logger.info(f"📈 Starting market data download")
        self.logger.info(f"📊 Symbols: {symbols}")
        self.logger.info(f"📉 Data types: {data_types}")
        self.logger.info(f"📅 Days back: {days_back}")

        results = {}

        for symbol in symbols:
            for data_type in data_types:
                if data_type not in self.MARKET_DATA_TYPES:
                    self.logger.warning(f"❌ Invalid market data type: {data_type}")
                    continue

                state_key = f"market_{symbol}_{data_type}_{days_back}d"

                try:
                    if data_type == 'funding':
                        result = self.download_funding_rates(symbol, days_back, state_key)
                    elif data_type == 'openinterest':
                        result = self.download_open_interest(symbol, days_back, state_key)
                    elif data_type == 'longshortratio':
                        result = self.download_long_short_ratio(symbol, days_back, state_key)
                    elif data_type == 'impliedvolatility':
                        result = self.download_implied_volatility(symbol, days_back, state_key)
                    else:
                        result = {"status": "invalid_type"}

                    results[f"{symbol}_{data_type}"] = result

                except Exception as e:
                    error_msg = f"❌ Failed to download {symbol} {data_type}: {e}"
                    self.logger.error(error_msg)
                    results[f"{symbol}_{data_type}"] = {"status": "failed", "error": str(e)}

        return results

    def download_funding_rates(self, symbol: str, days_back: int, state_key: str) -> Dict:
        """Download funding rate data."""
        output_dir = self.DIRECTORIES['funding_rates']
        filename = f"{symbol}_fundingrate_{days_back}d_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(output_dir, filename)

        # Check if already downloaded
        if self.is_download_complete(state_key, file_path):
            return {"status": "already_completed", "file": file_path}

        self.logger.info(f"💰 Downloading funding rates: {symbol} ({days_back} days)")

        downloader = ByBitFundingRateDownloader(timeout=30)

        # Get current rate for verification
        current_rate = downloader.get_funding_rate(symbol, 'linear')
        if current_rate.get('result', {}).get('list'):
            rate_value = float(current_rate['result']['list'][0].get('fundingRate', 0))
            self.logger.info(f"📊 Current {symbol} funding rate: {rate_value:.8f} ({rate_value*100:.6f}%)")

        # Download historical data
        saved_file = downloader.download_and_save(
            symbol=symbol,
            category='linear',
            days_back=days_back,
            output_dir=output_dir
        )

        # Mark as complete
        if saved_file and os.path.exists(saved_file):
            self.mark_download_complete(state_key, saved_file, {
                'symbol': symbol,
                'data_type': 'funding_rate',
                'days_back': days_back
            })

            # Get file stats
            file_size = os.path.getsize(saved_file) / 1024  # KB
            self.logger.info(f"✅ Funding rates saved: {saved_file} ({file_size:.1f} KB)")

            return {"status": "completed", "file": saved_file, "size_kb": file_size}

        return {"status": "failed", "error": "File not created"}

    def download_open_interest(self, symbol: str, days_back: int, state_key: str) -> Dict:
        """Download open interest data."""
        output_dir = self.DIRECTORIES['open_interest']
        filename = f"{symbol}_openinterest_{days_back}d_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(output_dir, filename)

        if self.is_download_complete(state_key, file_path):
            return {"status": "already_completed", "file": file_path}

        self.logger.info(f"📊 Downloading open interest: {symbol} ({days_back} days)")

        downloader = ByBitOpenInterestDownloader(timeout=30)

        # Get current OI
        current_oi = downloader.get_open_interest(symbol, 'linear')
        if current_oi.get('result', {}).get('list'):
            oi_value = current_oi['result']['list'][0].get('openInterest', 'N/A')
            self.logger.info(f"📊 Current {symbol} open interest: {oi_value}")

        # Get historical data
        historical_data = downloader.get_historical_open_interest(
            symbol=symbol,
            category='linear',
            interval_time='1d',
            days_back=days_back
        )

        # Save to file
        with open(file_path, 'w') as f:
            json.dump(historical_data, f, indent=2)

        # Mark as complete
        if os.path.exists(file_path):
            records_count = len(historical_data) if isinstance(historical_data, list) else 0
            file_size = os.path.getsize(file_path) / 1024  # KB

            self.mark_download_complete(state_key, file_path, {
                'symbol': symbol,
                'data_type': 'open_interest',
                'days_back': days_back,
                'records_count': records_count
            })

            self.logger.info(f"✅ Open interest saved: {file_path} ({records_count} records, {file_size:.1f} KB)")
            return {"status": "completed", "file": file_path, "records": records_count, "size_kb": file_size}

        return {"status": "failed", "error": "File not created"}

    def download_long_short_ratio(self, symbol: str, days_back: int, state_key: str) -> Dict:
        """Download long-short ratio data."""
        output_dir = self.DIRECTORIES['long_short_ratio']

        # Check for existing files first
        existing_files = [f for f in os.listdir(output_dir) if symbol in f and 'longshortratio' in f]
        if existing_files:
            latest_file = max(existing_files, key=lambda f: os.path.getmtime(os.path.join(output_dir, f)))
            file_path = os.path.join(output_dir, latest_file)
            if self.is_download_complete(state_key, file_path):
                return {"status": "already_completed", "file": file_path}

        self.logger.info(f"⚖️  Downloading long-short ratio: {symbol} ({days_back} days)")

        downloader = ByBitLongShortRatioDownloader(timeout=30)

        # Get current ratio
        current_ratio = downloader.get_long_short_ratio(symbol, 'linear')
        result_list = current_ratio.get('result', {}).get('list', [])
        if result_list:
            buy_ratio = float(result_list[0].get('buyRatio', 0))
            sell_ratio = float(result_list[0].get('sellRatio', 0))
            self.logger.info(f"📊 Current {symbol} sentiment - Long: {buy_ratio:.1%}, Short: {sell_ratio:.1%}")

        # Download historical data - fix the method call
        saved_file = downloader.download_and_save(
            symbol=symbol,
            category='linear',
            period='1d',
            days_back=days_back,
            output_dir=output_dir
        )

        # Mark as complete
        if saved_file and os.path.exists(saved_file):
            file_size = os.path.getsize(saved_file) / 1024  # KB

            self.mark_download_complete(state_key, saved_file, {
                'symbol': symbol,
                'data_type': 'long_short_ratio',
                'days_back': days_back
            })

            self.logger.info(f"✅ Long-short ratio saved: {saved_file} ({file_size:.1f} KB)")
            return {"status": "completed", "file": saved_file, "size_kb": file_size}

        return {"status": "failed", "error": "File not created"}

    def download_implied_volatility(self, symbol: str, days_back: int, state_key: str) -> Dict:
        """Download implied volatility data."""
        output_dir = self.DIRECTORIES['implied_volatility']
        filename = f"{symbol}_impliedvol_{days_back}d_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        file_path = os.path.join(output_dir, filename)

        if self.is_download_complete(state_key, file_path):
            return {"status": "already_completed", "file": file_path}

        self.logger.info(f"📉 Downloading implied volatility: {symbol} ({days_back} days)")

        try:
            downloader = ByBitImpliedVolatilityDownloader(timeout=30)

            # Get base coin (BTC from BTCUSDT)
            base_coin = symbol.replace('USDT', '').replace('USD', '')

            # Get current IV
            current_iv = downloader.get_implied_volatility(base_coin, 'option')
            self.logger.info(f"📊 Current {base_coin} implied volatility: {current_iv}")

            # Download historical data
            saved_file = downloader.download_and_save(
                baseCoin=base_coin,
                category='option',
                days_back=days_back,
                output_dir=output_dir
            )

            # Mark as complete
            if saved_file and os.path.exists(saved_file):
                file_size = os.path.getsize(saved_file) / 1024  # KB

                self.mark_download_complete(state_key, saved_file, {
                    'symbol': symbol,
                    'base_coin': base_coin,
                    'data_type': 'implied_volatility',
                    'days_back': days_back
                })

                self.logger.info(f"✅ Implied volatility saved: {saved_file} ({file_size:.1f} KB)")
                return {"status": "completed", "file": saved_file, "size_kb": file_size}

            return {"status": "failed", "error": "File not created"}

        except Exception as e:
            return {"status": "failed", "error": str(e)}

    def generate_report(self, results: Dict):
        """Generate comprehensive download report."""
        report_filename = f"download_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_path = os.path.join(self.DIRECTORIES['reports'], report_filename)

        # Analyze results
        total_downloads = len(results)
        successful = len([r for r in results.values() if r.get('status') in ['completed', 'already_completed']])
        failed = len([r for r in results.values() if r.get('status') == 'failed'])

        report = {
            'timestamp': datetime.now().isoformat(),
            'summary': {
                'total_downloads': total_downloads,
                'successful': successful,
                'failed': failed,
                'success_rate': f"{(successful/total_downloads)*100:.1f}%" if total_downloads > 0 else "0%"
            },
            'results': results,
            'directory_structure': self.DIRECTORIES,
            'state_entries': len(self.download_state)
        }

        # Save report
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        # Print summary
        self.logger.info(f"\n📋 DOWNLOAD SUMMARY")
        self.logger.info(f"{'='*50}")
        self.logger.info(f"Total downloads: {total_downloads}")
        self.logger.info(f"✅ Successful: {successful}")
        self.logger.info(f"❌ Failed: {failed}")
        self.logger.info(f"📊 Success rate: {(successful/total_downloads)*100:.1f}%")
        self.logger.info(f"📄 Report saved: {report_path}")

        return report_path


def parse_arguments():
    """Parse command line arguments with comprehensive help."""
    parser = argparse.ArgumentParser(
        description='Bybit Unified CLI Downloader - Complete data download solution with resume capability',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
EXAMPLES:

Historical Data:
  # Download BTCUSDT trade data (contracts)
  python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-10

  # Download multiple symbols, multiple data types
  python bybit_unified_cli.py --symbols "BTCUSDT,ETHUSDT" --data-types "trade,orderbook" --market contract --start-date 2024-01-01 --end-date 2024-01-05

  # Download spot data
  python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market spot --start-date 2022-12-01 --end-date 2022-12-07

Klines Data:
  # Download 1m klines for BTCUSDT (linear contracts)
  python bybit_unified_cli.py --symbols BTCUSDT --data-types klines --market linear --interval 1m --start-date 2024-01-01 --end-date 2024-01-05

  # Download multiple intervals
  python bybit_unified_cli.py --symbols BTCUSDT --data-types klines --interval 1h --start-date 2024-01-01 --end-date 2024-01-31

Market Data:
  # Download funding rates (365 days)
  python bybit_unified_cli.py --symbols BTCUSDT --data-types funding --days-back 365

  # Download all market metrics
  python bybit_unified_cli.py --symbols "BTCUSDT,ETHUSDT" --data-types "funding,openinterest,longshortratio" --days-back 90

Mixed Downloads:
  # Download both historical and market data
  python bybit_unified_cli.py --symbols BTCUSDT --data-types "trade,funding,openinterest" --market contract --start-date 2024-01-01 --end-date 2024-01-05 --days-back 30

DIRECTORY STRUCTURE:
  data/
  ├── historical/
  │   ├── trade/spot/{SYMBOL}/
  │   ├── trade/contract/{SYMBOL}/
  │   ├── orderbook/spot/{SYMBOL}/
  │   ├── orderbook/contract/{SYMBOL}/
  │   └── klines/{MARKET}/{SYMBOL}/{INTERVAL}/
  ├── market_metrics/
  │   ├── funding_rates/
  │   ├── open_interest/
  │   ├── long_short_ratio/
  │   └── implied_volatility/
  ├── logs/
  ├── state/           # Resume capability
  └── reports/

RESUME CAPABILITY:
  The script automatically resumes interrupted downloads by:
  - Tracking completed files in data/state/download_state.json
  - Verifying file integrity with SHA256 checksums
  - Skipping already downloaded and verified files
  - Allowing partial date range completion

DATA TYPES:
  Historical: trade, orderbook
  Market:     funding, openinterest, longshortratio, impliedvolatility
  Markets:    spot, contract, linear, inverse, option

PERFORMANCE:
  --parallel N     Parallel downloads (default: 5)
  --timeout N      Request timeout seconds (default: 60)
        """
    )

    # Required arguments (but not for utility commands)
    parser.add_argument('--symbols',
                       help='Trading symbols (comma-separated, e.g., BTCUSDT,ETHUSDT)')
    parser.add_argument('--data-types',
                       help='Data types to download (comma-separated): trade,orderbook,funding,openinterest,longshortratio,impliedvolatility')

    # Historical data arguments
    parser.add_argument('--market', choices=['spot', 'contract', 'linear', 'inverse', 'option'],
                       default='contract', help='Market type for historical data (default: contract)')
    parser.add_argument('--start-date', help='Start date for historical data (YYYY-MM-DD)')
    parser.add_argument('--end-date', help='End date for historical data (YYYY-MM-DD)')
    parser.add_argument('--interval', default='1m', 
                       help='Kline interval (1m, 5m, 1h, 1d, etc. Default: 1m)')

    # Market data arguments
    parser.add_argument('--days-back', type=int, default=30,
                       help='Days back for market data (default: 30)')

    # Performance arguments
    parser.add_argument('--parallel', type=int, default=5,
                       help='Number of parallel downloads (default: 5)')
    parser.add_argument('--timeout', type=int, default=60,
                       help='Request timeout in seconds (default: 60)')

    # Output arguments
    parser.add_argument('--verbose', action='store_true',
                       help='Enable verbose logging')

    # Utility arguments
    parser.add_argument('--show-structure', action='store_true',
                       help='Show directory structure and exit')
    parser.add_argument('--clear-state', action='store_true',
                       help='Clear download state (force re-download)')

    return parser.parse_args()


def main():
    """Main CLI function."""
    print("🚀 Bybit Unified CLI Downloader")
    print("=" * 60)

    args = parse_arguments()

    # Initialize CLI
    cli = BybitUnifiedCLI()

    # Handle utility arguments
    if args.show_structure:
        print("\n📁 DIRECTORY STRUCTURE:")
        for name, path in cli.DIRECTORIES.items():
            status = "✅" if os.path.exists(path) else "❌"
            print(f"  {status} {name}: {path}")
        return

    if args.clear_state:
        if os.path.exists(cli.state_file):
            os.remove(cli.state_file)
            cli.logger.info("🗑️  Cleared download state - all files will be re-downloaded")
            cli.load_state()  # Reload empty state

    # Check required arguments for actual downloads
    if not args.symbols or not args.data_types:
        cli.logger.error("❌ --symbols and --data-types are required for downloads")
        cli.logger.error("Use --help for examples or --show-structure to see directory layout")
        sys.exit(1)

    # Parse arguments
    symbols = [s.strip().upper() for s in args.symbols.split(',')]
    data_types = [d.strip().lower() for d in args.data_types.split(',')]

    # Validate arguments
    invalid_types = [dt for dt in data_types if dt not in cli.ALL_DATA_TYPES]
    if invalid_types:
        cli.logger.error(f"❌ Invalid data types: {invalid_types}")
        cli.logger.error(f"Valid types: {cli.ALL_DATA_TYPES}")
        sys.exit(1)

    # Check requirements for historical data
    historical_types = [dt for dt in data_types if dt in cli.HISTORICAL_DATA_TYPES]
    if historical_types and (not args.start_date or not args.end_date):
        cli.logger.error(f"❌ --start-date and --end-date required for historical data types: {historical_types}")
        sys.exit(1)

    # Start downloads
    cli.logger.info(f"🎯 Target symbols: {symbols}")
    cli.logger.info(f"📊 Data types: {data_types}")

    all_results = {}

    # Download historical data
    if historical_types:
        # Validate interval if klines are requested
        if 'klines' in historical_types and args.interval not in cli.VALID_INTERVALS:
            cli.logger.error(f"❌ Invalid interval: {args.interval}")
            cli.logger.error(f"Valid intervals: {cli.VALID_INTERVALS}")
            sys.exit(1)

        cli.logger.info(f"\n📈 Starting historical data downloads...")
        historical_results = cli.download_historical_data(
            symbols=symbols,
            data_types=historical_types,
            market=args.market,
            start_date=args.start_date,
            end_date=args.end_date,
            parallel=args.parallel,
            timeout=args.timeout,
            interval=args.interval
        )
        all_results.update(historical_results)

    # Download market data
    market_types = [dt for dt in data_types if dt in cli.MARKET_DATA_TYPES]
    if market_types:
        cli.logger.info(f"\n📉 Starting market data downloads...")
        market_results = cli.download_market_data(
            symbols=symbols,
            data_types=market_types,
            days_back=args.days_back
        )
        all_results.update(market_results)

    # Generate final report
    cli.logger.info(f"\n📋 Generating final report...")
    report_path = cli.generate_report(all_results)

    # Final status
    success_count = len([r for r in all_results.values() if r.get('status') in ['completed', 'already_completed']])
    total_count = len(all_results)

    if success_count == total_count:
        cli.logger.info(f"\n🎉 ALL DOWNLOADS COMPLETED SUCCESSFULLY!")
        cli.logger.info(f"📁 Data saved in organized directory structure under ./data/")
        cli.logger.info(f"📄 Full report: {report_path}")
    else:
        cli.logger.warning(f"\n⚠️  SOME DOWNLOADS FAILED ({success_count}/{total_count} successful)")
        cli.logger.info(f"📄 Check report for details: {report_path}")
        sys.exit(1)


if __name__ == "__main__":
    main()