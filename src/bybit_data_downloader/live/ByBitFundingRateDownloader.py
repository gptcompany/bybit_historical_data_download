import logging
import os
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union
from pathlib import Path
import httpx

class ByBitFundingRateDownloader:
    """
    A high-performance downloader for Bybit historical funding rate data using API v5.

    Supports downloading historical funding rate data for linear and inverse
    perpetual contracts with automatic pagination and data export.
    """

    BASE_URL = "https://api.bybit.com/v5/market/funding/history"

    def __init__(self, timeout: int = 30):
        """
        Initialize the Bybit funding rate downloader.

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
        Bybit Historical Funding Rate Downloader - Usage Guide
        ======================================================

        Parameters:
        -----------
        symbol: str
            - Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT', 'BTCUSD')
            - Must be uppercase format

        category: str
            - Contract type: 'linear' or 'inverse'
            - linear: USDT/USDC perpetual contracts
            - inverse: Coin-margined perpetual contracts

        start_time: int (optional)
            - Start timestamp in milliseconds
            - If not provided, fetches recent data

        end_time: int (optional)
            - End timestamp in milliseconds
            - If not provided, fetches up to current time

        limit: int
            - Data points per request (1-200, default: 200)
            - For pagination with large date ranges

        API Behavior Notes:
        ------------------
        - Passing only startTime returns an error
        - Passing only endTime returns 200 records up to that time
        - Passing no time parameters returns 200 recent records
        - Covers USDT and USDC perpetual / Inverse perpetual

        Example Usage:
        --------------
        downloader = ByBitFundingRateDownloader()

        # Get current funding rates
        current_rates = downloader.get_funding_rate('BTCUSDT', 'linear')

        # Get historical data (last 30 days)
        historical_rates = downloader.get_historical_funding_rate(
            symbol='BTCUSDT',
            category='linear',
            days_back=30
        )

        # Download and save to file
        downloader.download_and_save(
            symbol='ETHUSDT',
            category='linear',
            days_back=90,
            output_file='eth_funding_rates.json'
        )

        Data Interpretation:
        -------------------
        - fundingRate: The funding rate value (decimal)
        - fundingRateTimestamp: Timestamp when rate was applied
        - Positive rate: Longs pay shorts
        - Negative rate: Shorts pay longs
        - Typically updated every 8 hours

        Common Values:
        - Normal markets: -0.01% to +0.01%
        - High volatility: -0.375% to +0.375% (extreme)
        - Very high rates indicate strong directional bias

        Rate Limiting:
        --------------
        - Automatic rate limiting with 1-second delays
        - Respect Bybit API limits (600 requests/minute)
        """
        print(help_text)

    def get_funding_rate(self,
                        symbol: str,
                        category: str = "linear",
                        limit: int = 200,
                        start_time: Optional[int] = None,
                        end_time: Optional[int] = None) -> Dict:
        """
        Get funding rate data from Bybit API v5.

        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            category: Contract type ('linear' or 'inverse')
            limit: Number of data points (1-200)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Dict containing API response with funding rate data
        """
        # Validate inputs
        self._validate_symbol(symbol)
        self._validate_category(category)

        params = {
            "category": category,
            "symbol": symbol.upper(),
            "limit": limit
        }

        # Note: API behavior - passing only startTime returns error
        if start_time and end_time:
            params["startTime"] = start_time
            params["endTime"] = end_time
        elif end_time:
            params["endTime"] = end_time
        # If neither provided, gets recent records

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Requesting funding rate for {symbol} ({category}) - attempt {attempt + 1}")

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

    def get_historical_funding_rate(self,
                                   symbol: str,
                                   category: str = "linear",
                                   days_back: int = 30) -> List[Dict]:
        """
        Get historical funding rate data for a specified number of days.

        Args:
            symbol: Trading pair symbol
            category: Contract type
            days_back: Number of days to go back from current time

        Returns:
            List of all funding rate data points
        """

        end_time = int(time.time() * 1000)  # Current time in ms
        start_time = end_time - (days_back * 24 * 60 * 60 * 1000)  # days_back ago

        all_data = []
        current_end = end_time

        # Work backwards in chunks to respect API behavior
        while len(all_data) < (days_back * 3) and current_end > start_time:  # ~3 funding rates per day
            # Calculate chunk start time (get ~7 days worth per request)
            chunk_start = max(current_end - (7 * 24 * 60 * 60 * 1000), start_time)

            result = self.get_funding_rate(
                symbol=symbol,
                category=category,
                limit=200,
                start_time=chunk_start,
                end_time=current_end
            )

            if result.get("retCode") == 0 and result.get("result", {}).get("list"):
                chunk_data = result["result"]["list"]
                all_data.extend(chunk_data)
                self.logger.info(f"Retrieved chunk: {len(chunk_data)} data points")

                # Update current_end to the oldest timestamp we got
                if chunk_data:
                    oldest_timestamp = min(int(item["fundingRateTimestamp"]) for item in chunk_data)
                    current_end = oldest_timestamp - 1
                else:
                    break
            else:
                self.logger.warning(f"Failed to retrieve data for chunk ending {current_end}")
                break

            # Rate limiting
            time.sleep(1)

        # Sort by timestamp (newest first) and remove duplicates
        seen_timestamps = set()
        unique_data = []

        for item in sorted(all_data, key=lambda x: int(x["fundingRateTimestamp"]), reverse=True):
            timestamp = item["fundingRateTimestamp"]
            if timestamp not in seen_timestamps:
                seen_timestamps.add(timestamp)
                unique_data.append(item)

        # Filter to requested time range
        filtered_data = [
            item for item in unique_data
            if start_time <= int(item["fundingRateTimestamp"]) <= end_time
        ]

        self.logger.info(f"Total historical funding rate data points retrieved: {len(filtered_data)}")
        return filtered_data

    def download_and_save(self,
                         symbol: str,
                         category: str = "linear",
                         days_back: int = 30,
                         output_file: Optional[str] = None,
                         output_dir: str = "./funding_rate_data") -> str:
        """
        Download funding rate data and save to JSON file.

        Args:
            symbol: Trading pair symbol
            category: Contract type
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
            output_file = f"{symbol}_{category}_fundingrate_{days_back}d_{timestamp}.json"

        file_path = Path(output_dir) / output_file

        # Download data
        self.logger.info(f"Downloading {days_back} days of funding rate data for {symbol}")
        data = self.get_historical_funding_rate(
            symbol=symbol,
            category=category,
            days_back=days_back
        )

        if not data:
            self.logger.error("No data retrieved. File not saved.")
            return None

        # Calculate basic statistics
        funding_rates = [float(item['fundingRate']) for item in data if 'fundingRate' in item]

        stats = {}
        if funding_rates:
            positive_rates = [r for r in funding_rates if r > 0]
            negative_rates = [r for r in funding_rates if r < 0]

            stats = {
                "avg_funding_rate": sum(funding_rates) / len(funding_rates),
                "max_funding_rate": max(funding_rates),
                "min_funding_rate": min(funding_rates),
                "funding_rate_range": max(funding_rates) - min(funding_rates),
                "positive_rates_count": len(positive_rates),
                "negative_rates_count": len(negative_rates),
                "neutral_rates_count": len([r for r in funding_rates if r == 0]),
                "avg_positive_rate": sum(positive_rates) / len(positive_rates) if positive_rates else 0,
                "avg_negative_rate": sum(negative_rates) / len(negative_rates) if negative_rates else 0,
                "latest_funding_rate": funding_rates[0] if funding_rates else None
            }

        # Prepare data for saving
        save_data = {
            "metadata": {
                "symbol": symbol,
                "category": category,
                "days_back": days_back,
                "total_data_points": len(data),
                "download_timestamp": datetime.now().isoformat(),
                "earliest_data": datetime.fromtimestamp(int(data[-1]["fundingRateTimestamp"])/1000).isoformat() if data else None,
                "latest_data": datetime.fromtimestamp(int(data[0]["fundingRateTimestamp"])/1000).isoformat() if data else None,
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
                self.logger.info(f"Average funding rate: {stats['avg_funding_rate']:.6f} ({stats['avg_funding_rate']*100:.4f}%)")
                self.logger.info(f"Rate range: {stats['min_funding_rate']:.6f} to {stats['max_funding_rate']:.6f}")
                self.logger.info(f"Positive rates: {stats['positive_rates_count']}, Negative: {stats['negative_rates_count']}")

            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error saving file: {e}")
            return None

    def get_supported_symbols(self, category: str = "linear") -> List[str]:
        """
        Get a list of commonly supported symbols for funding rates.

        Args:
            category: Contract type ('linear' or 'inverse')

        Returns:
            List of supported symbol strings
        """

        if category == "linear":
            return [
                "BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT", "DOTUSDT",
                "LINKUSDT", "LTCUSDT", "BCHUSDT", "XRPUSDT", "EOSUSDT",
                "ETCUSDT", "TRXUSDT", "QTUMUSDT", "XLMUSDT", "ATOMUSDT",
                "AVAXUSDT", "UNIUSDT", "FILUSDT", "MATICUSDT", "AAVEUSDT"
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
                     days_back: int = 30,
                     output_dir: str = "./funding_rate_bulk") -> Dict[str, str]:
        """
        Download funding rate data for multiple symbols.

        Args:
            symbols: List of trading pair symbols
            category: Contract type
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
                days_back=days_back,
                output_dir=output_dir
            )

            results[symbol] = file_path

            # Rate limiting between symbols
            if i < total_symbols:
                time.sleep(2)

        self.logger.info(f"Bulk download completed. {len(results)} files saved.")
        return results

    def analyze_funding_trends(self, data: List[Dict]) -> Dict[str, Union[float, int, str]]:
        """
        Analyze funding rate trends from historical data.

        Args:
            data: List of funding rate data points

        Returns:
            Dictionary with trend analysis
        """

        if not data:
            return {}

        funding_rates = [float(item['fundingRate']) for item in data if 'fundingRate' in item]

        if len(funding_rates) < 2:
            return {}

        # Calculate trends
        recent_half = funding_rates[:len(funding_rates)//2]
        older_half = funding_rates[len(funding_rates)//2:]

        recent_avg = sum(recent_half) / len(recent_half)
        older_avg = sum(older_half) / len(older_half)

        trend_direction = "increasing" if recent_avg > older_avg else "decreasing"
        trend_magnitude = abs(recent_avg - older_avg)

        # Count consecutive positive/negative periods
        consecutive_positive = 0
        consecutive_negative = 0
        current_streak_positive = 0
        current_streak_negative = 0

        for rate in funding_rates:
            if rate > 0:
                current_streak_positive += 1
                consecutive_positive = max(consecutive_positive, current_streak_positive)
                current_streak_negative = 0
            elif rate < 0:
                current_streak_negative += 1
                consecutive_negative = max(consecutive_negative, current_streak_negative)
                current_streak_positive = 0
            else:
                current_streak_positive = 0
                current_streak_negative = 0

        return {
            "trend_direction": trend_direction,
            "trend_magnitude": trend_magnitude,
            "recent_average": recent_avg,
            "older_average": older_avg,
            "max_consecutive_positive": consecutive_positive,
            "max_consecutive_negative": consecutive_negative,
            "current_positive_streak": current_streak_positive,
            "current_negative_streak": current_streak_negative,
            "volatility": max(funding_rates) - min(funding_rates),
            "extreme_positive_count": len([r for r in funding_rates if r > 0.001]),  # >0.1%
            "extreme_negative_count": len([r for r in funding_rates if r < -0.001])  # <-0.1%
        }

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