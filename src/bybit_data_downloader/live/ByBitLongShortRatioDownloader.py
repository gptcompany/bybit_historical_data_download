import logging
import os
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union
from pathlib import Path
import httpx

class ByBitLongShortRatioDownloader:
    """
    A high-performance downloader for Bybit long-short ratio data using API v5.

    Supports downloading historical and real-time long-short ratio data for
    linear and inverse contracts with automatic pagination and data export.
    """

    BASE_URL = "https://api.bybit.com/v5/market/account-ratio"

    def __init__(self, timeout: int = 30):
        """
        Initialize the Bybit long-short ratio downloader.

        Args:
            timeout: Request timeout in seconds (default: 30)
        """
        self.timeout = timeout

        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

        # Browser-like headers to avoid detection
        self.headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'priority': 'u=1, i',
            'sec-ch-ua': '"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"macOS"',
            'sec-fetch-dest': 'empty',
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

    def help(self) -> None:
        """Display usage information and parameter details."""
        help_text = """
        Bybit Long-Short Ratio Downloader - Usage Guide
        ==============================================

        Parameters:
        -----------
        symbol: str
            - Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
            - Must be uppercase format

        category: str
            - Contract type: 'linear' or 'inverse'
            - linear: USDT/USDC perpetual contracts
            - inverse: Coin-margined contracts (e.g., BTCUSD)

        period: str
            - Time period: '5min', '15min', '30min', '1h', '4h', '1d'
            - Determines granularity of ratio data

        start_time: int (optional)
            - Start timestamp in milliseconds
            - If not provided, fetches recent data

        end_time: int (optional)
            - End timestamp in milliseconds
            - If not provided, fetches up to current time

        limit: int
            - Data points per request (1-500, default: 50)
            - For pagination with large date ranges

        Example Usage:
        --------------
        downloader = ByBitLongShortRatioDownloader()

        # Get current long-short ratio
        current_ratio = downloader.get_long_short_ratio('BTCUSDT', 'linear')

        # Get historical data (last 30 days)
        historical_ratio = downloader.get_historical_long_short_ratio(
            symbol='BTCUSDT',
            category='linear',
            period='1d',
            days_back=30
        )

        # Download and save to file
        downloader.download_and_save(
            symbol='ETHUSDT',
            category='linear',
            period='4h',
            days_back=7,
            output_file='eth_long_short_ratio.json'
        )

        Data Interpretation:
        -------------------
        - buyRatio: Percentage of users with long positions (0.0-1.0)
        - sellRatio: Percentage of users with short positions (0.0-1.0)
        - buyRatio + sellRatio = 1.0

        High buyRatio (>0.6): More traders are long (bullish sentiment)
        High sellRatio (>0.6): More traders are short (bearish sentiment)

        Rate Limiting:
        --------------
        - Automatic rate limiting with 1-second delays
        - Respect Bybit API limits (600 requests/minute)
        """
        print(help_text)

    def get_long_short_ratio(self,
                           symbol: str,
                           category: str = "linear",
                           period: str = "1d",
                           limit: int = 50,
                           start_time: Optional[int] = None,
                           end_time: Optional[int] = None) -> Dict:
        """
        Get long-short ratio data from Bybit API v5.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            category: Contract type ('linear' or 'inverse')
            period: Time period ('5min', '15min', '30min', '1h', '4h', '1d')
            limit: Number of data points (1-500)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Dict containing API response with long-short ratio data
        """
        # Validate inputs
        self._validate_symbol(symbol)
        self._validate_category(category)

        params = {
            "category": category,
            "symbol": symbol.upper(),
            "period": period,
            "limit": limit
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Requesting long-short ratio for {symbol} ({category}) - attempt {attempt + 1}")

                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(self.BASE_URL, params=params, headers=self.headers)
                    response.raise_for_status()

                    data = response.json()

                    if data.get("retCode") == 0:
                        self.logger.info(f"Success! Retrieved {len(data['result']['list'])} data points")
                        return data
                    else:
                        self.logger.error(f"API Error: {data.get('retMsg', 'Unknown error')}")
                        return data

            except httpx.RequestError as e:
                self.logger.error(f"Network Error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return {"error": str(e)}
            except Exception as e:
                self.logger.error(f"Unexpected Error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                else:
                    return {"error": str(e)}

    def get_historical_long_short_ratio(self,
                                      symbol: str,
                                      category: str = "linear",
                                      period: str = "1d",
                                      days_back: int = 30) -> List[Dict]:
        """
        Get historical long-short ratio data for a specified number of days.

        Args:
            symbol: Trading pair symbol
            category: Contract type
            period: Time period
            days_back: Number of days to go back from current time

        Returns:
            List of all long-short ratio data points
        """

        end_time = int(time.time() * 1000)  # Current time in ms
        start_time = end_time - (days_back * 24 * 60 * 60 * 1000)  # days_back ago

        all_data = []
        current_start = start_time

        while current_start < end_time:
            # Calculate chunk end time (max 500 data points per request)
            chunk_end = min(current_start + (10 * 24 * 60 * 60 * 1000), end_time)  # 10 days max

            result = self.get_long_short_ratio(
                symbol=symbol,
                category=category,
                period=period,
                limit=500,
                start_time=current_start,
                end_time=chunk_end
            )

            if result.get("retCode") == 0 and result.get("result", {}).get("list"):
                all_data.extend(result["result"]["list"])
                self.logger.info(f"Retrieved chunk: {len(result['result']['list'])} data points")
            else:
                self.logger.warning(f"Failed to retrieve data for chunk starting {current_start}")
                break

            # Move to next chunk
            current_start = chunk_end + 1

            # Rate limiting
            time.sleep(1)

        self.logger.info(f"Total historical data points retrieved: {len(all_data)}")
        return all_data

    def download_and_save(self,
                         symbol: str,
                         category: str = "linear",
                         period: str = "1d",
                         days_back: int = 30,
                         output_file: Optional[str] = None,
                         output_dir: str = "./long_short_ratio_data") -> str:
        """
        Download long-short ratio data and save to JSON file.

        Args:
            symbol: Trading pair symbol
            category: Contract type
            period: Time period
            days_back: Number of days to download
            output_file: Custom filename (optional)
            output_dir: Output directory

        Returns:
            Path to saved file
        """

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{symbol}_{category}_{period}_{days_back}d_longshortratio_{timestamp}.json"

        file_path = Path(output_dir) / output_file

        # Download data
        self.logger.info(f"Downloading {days_back} days of long-short ratio data for {symbol}")
        data = self.get_historical_long_short_ratio(
            symbol=symbol,
            category=category,
            period=period,
            days_back=days_back
        )

        if not data:
            self.logger.error("No data retrieved. File not saved.")
            return None

        # Calculate basic statistics
        buy_ratios = [float(item['buyRatio']) for item in data if 'buyRatio' in item]
        sell_ratios = [float(item['sellRatio']) for item in data if 'sellRatio' in item]

        stats = {}
        if buy_ratios:
            stats = {
                "avg_buy_ratio": sum(buy_ratios) / len(buy_ratios),
                "max_buy_ratio": max(buy_ratios),
                "min_buy_ratio": min(buy_ratios),
                "avg_sell_ratio": sum(sell_ratios) / len(sell_ratios),
                "max_sell_ratio": max(sell_ratios),
                "min_sell_ratio": min(sell_ratios)
            }

        # Prepare data for saving
        save_data = {
            "metadata": {
                "symbol": symbol,
                "category": category,
                "period": period,
                "days_back": days_back,
                "total_data_points": len(data),
                "download_timestamp": datetime.now().isoformat(),
                "earliest_data": datetime.fromtimestamp(int(data[-1]["timestamp"])/1000).isoformat() if data else None,
                "latest_data": datetime.fromtimestamp(int(data[0]["timestamp"])/1000).isoformat() if data else None,
                "statistics": stats
            },
            "data": data
        }

        # Save to file
        try:
            with open(file_path, 'w') as f:
                json.dump(save_data, f, indent=2)

            self.logger.info(f"Data saved successfully to: {file_path}")
            self.logger.info(f"Total data points: {len(data)}")
            if stats:
                self.logger.info(f"Average buy ratio: {stats['avg_buy_ratio']:.3f}")
                self.logger.info(f"Average sell ratio: {stats['avg_sell_ratio']:.3f}")

            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error saving file: {e}")
            return None

    def get_supported_symbols(self, category: str = "linear") -> List[str]:
        """
        Get a list of commonly supported symbols for long-short ratio.

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
                     period: str = "1d",
                     days_back: int = 30,
                     output_dir: str = "./long_short_ratio_bulk") -> Dict[str, str]:
        """
        Download long-short ratio data for multiple symbols.

        Args:
            symbols: List of trading pair symbols
            category: Contract type
            period: Time period
            days_back: Number of days to download
            output_dir: Output directory

        Returns:
            Dictionary mapping symbol to saved file path
        """

        results = {}
        total_symbols = len(symbols)

        self.logger.info(f"Starting bulk download for {total_symbols} symbols")

        for i, symbol in enumerate(symbols, 1):
            self.logger.info(f"Processing {symbol} ({i}/{total_symbols})")

            file_path = self.download_and_save(
                symbol=symbol,
                category=category,
                period=period,
                days_back=days_back,
                output_dir=output_dir
            )

            results[symbol] = file_path

            # Rate limiting between symbols
            if i < total_symbols:
                time.sleep(2)

        self.logger.info(f"Bulk download completed. {len(results)} files saved.")
        return results

    def _validate_symbol(self, symbol: str) -> None:
        """Validate symbol parameter."""
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Symbol must be a non-empty string")

        symbol = symbol.strip().upper()
        if not symbol.replace('/', '').replace('-', '').isalnum():
            raise ValueError(f"Invalid symbol format: {symbol}")

    def _validate_category(self, category: str) -> None:
        """Validate category parameter."""
        if category not in ['linear', 'inverse']:
            raise ValueError("category must be 'linear' or 'inverse'")