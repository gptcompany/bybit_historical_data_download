"""
Backward compatibility wrapper for ByBitOpenInterestDownloader.

This class now uses the unified ByBitUnifiedDownloader internally while
maintaining the exact same API for backward compatibility.
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional
from .ByBitUnifiedDownloader import ByBitUnifiedDownloader


class ByBitOpenInterestDownloader:
    """
    A high-performance downloader for Bybit open interest data using API v5.

    This class is now a thin wrapper around ByBitUnifiedDownloader for
    backward compatibility while eliminating code duplication.

    Supports downloading historical and real-time open interest data for
    linear and inverse contracts with automatic pagination and data export.
    """

    BASE_URL = "https://api.bybit.com/v5/market/open-interest"

    def __init__(self, timeout: int = 30):
        """
        Initialize the Bybit open interest downloader.

        Args:
            timeout: Request timeout in seconds (default: 30)
        """
        self.timeout = timeout

        # Create unified downloader instance
        self._downloader = ByBitUnifiedDownloader('open_interest', timeout=timeout)

        # Expose logging for backward compatibility
        self.logger = self._downloader.logger

        # Expose headers for backward compatibility
        self.headers = self._downloader.headers

    def help(self) -> None:
        """Display usage information and parameter details."""
        help_text = """
        Bybit Open Interest Downloader - Usage Guide
        ==========================================

        Parameters:
        -----------
        symbol: str
            - Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT', 'BTCUSD')
            - Must be uppercase format

        category: str
            - Contract type: 'linear' or 'inverse'
            - linear: USDT/USDC perpetual contracts
            - inverse: Coin-margined contracts (e.g., BTCUSD)

        interval_time: str
            - Time interval: '5min', '15min', '30min', '1h', '4h', '1d'
            - Determines granularity of open interest data

        start_time: int (optional)
            - Start timestamp in milliseconds
            - If not provided, fetches recent data

        end_time: int (optional)
            - End timestamp in milliseconds
            - If not provided, fetches up to current time

        limit: int
            - Data points per request (1-200, default: 50)
            - For pagination with large date ranges

        Example Usage:
        --------------
        downloader = ByBitOpenInterestDownloader()

        # Get current open interest
        current_oi = downloader.get_open_interest('BTCUSDT', 'linear')

        # Get historical data (last 30 days)
        historical_oi = downloader.get_historical_open_interest(
            symbol='BTCUSDT',
            category='linear',
            interval_time='1d',
            days_back=30
        )

        # Download and save to file
        downloader.download_and_save(
            symbol='ETHUSDT',
            category='linear',
            interval_time='4h',
            days_back=7,
            output_file='eth_open_interest.json'
        )

        Supported Symbols:
        ------------------
        Linear (USDT/USDC):
        - BTCUSDT, ETHUSDT, ADAUSDT, SOLUSDT, etc.

        Inverse (Coin-margined):
        - BTCUSD, ETHUSD, EOSUSD, etc.

        Rate Limiting:
        --------------
        - Automatic rate limiting with 1-second delays
        - Respect Bybit API limits (600 requests/minute)
        """
        print(help_text)

    def get_open_interest(self,
                         symbol: str,
                         category: str = "linear",
                         interval_time: str = "1d",
                         limit: int = 50,
                         start_time: Optional[int] = None,
                         end_time: Optional[int] = None) -> Dict:
        """
        Get open interest data from Bybit API v5.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            category: Contract type ('linear' or 'inverse')
            interval_time: Time interval ('5min', '15min', '30min', '1h', '4h', '1d')
            limit: Number of data points (1-200)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Dict containing API response with open interest data
        """
        return self._downloader.get_data(
            symbol=symbol,
            category=category,
            interval_time=interval_time,
            limit=limit,
            start_time=start_time,
            end_time=end_time
        )

    def get_historical_open_interest(self,
                                   symbol: str,
                                   category: str = "linear",
                                   interval_time: str = "1d",
                                   days_back: int = 30) -> List[Dict]:
        """
        Get historical open interest data for a specified number of days.

        Args:
            symbol: Trading pair symbol
            category: Contract type
            interval_time: Time interval
            days_back: Number of days to go back from current time

        Returns:
            List of all open interest data points
        """
        return self._downloader.get_historical_data(
            symbol=symbol,
            category=category,
            interval_time=interval_time,
            days_back=days_back
        )

    def download_and_save(self,
                         symbol: str,
                         category: str = "linear",
                         interval_time: str = "1d",
                         days_back: int = 30,
                         output_file: Optional[str] = None,
                         output_dir: str = "./open_interest_data") -> str:
        """
        Download open interest data and save to JSON file.

        Args:
            symbol: Trading pair symbol
            category: Contract type
            interval_time: Time interval
            days_back: Number of days to download
            output_file: Custom filename (optional)
            output_dir: Output directory

        Returns:
            Path to saved file
        """
        return self._downloader.download_and_save(
            symbol=symbol,
            category=category,
            interval_time=interval_time,
            days_back=days_back,
            output_file=output_file,
            output_dir=output_dir
        )

    def get_supported_symbols(self, category: str = "linear") -> List[str]:
        """
        Get a list of commonly supported symbols for open interest.

        Args:
            category: Contract type ('linear' or 'inverse')

        Returns:
            List of supported symbol strings
        """
        if category == "linear":
            return [
                "BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
                "LINKUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT", "EOSUSDT",
                "ETCUSDT", "TRXUSDT", "QTUMUSDT", "XLMUSDT", "ATOMUSDT"
            ]
        elif category == "inverse":
            return [
                "BTCUSD", "ETHUSD", "EOSUSD", "XRPUSD", "LTCUSD",
                "BCHUSDT", "LINKUSD", "DOTUSD", "ADAUSD"
            ]
        else:
            self.logger.warning(f"Unknown category: {category}")
            return []

    def bulk_download(self,
                     symbols: List[str],
                     category: str = "linear",
                     interval_time: str = "1d",
                     days_back: int = 30,
                     output_dir: str = "./open_interest_bulk") -> Dict[str, str]:
        """
        Download open interest data for multiple symbols.

        Args:
            symbols: List of trading pair symbols
            category: Contract type
            interval_time: Time interval
            days_back: Number of days to download
            output_dir: Output directory

        Returns:
            Dictionary mapping symbol to saved file path
        """
        # Use the unified downloader's bulk_download method
        return self._downloader.bulk_download(
            symbols=symbols,
            category=category,
            interval=interval_time,
            days_back=days_back,
            output_dir=output_dir
        )

    def _validate_symbol(self, symbol: str) -> None:
        """Validate symbol parameter."""
        return self._downloader._validate_symbol(symbol)

    def _validate_category(self, category: str) -> None:
        """Validate category parameter."""
        return self._downloader._validate_category(category)