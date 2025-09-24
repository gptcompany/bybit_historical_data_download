import logging
import os
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Union
from pathlib import Path
import httpx

class ByBitImpliedVolatilityDownloader:
    """
    A high-performance downloader for Bybit historical volatility data using API v5.

    Supports downloading historical implied volatility data for options trading
    with automatic pagination and data export.
    """

    BASE_URL = "https://api.bybit.com/v5/market/historical-volatility"

    def __init__(self, timeout: int = 30):
        """
        Initialize the Bybit implied volatility downloader.

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
        Bybit Implied Volatility Downloader - Usage Guide
        ================================================

        Parameters:
        -----------
        base_coin: str
            - Base cryptocurrency (e.g., 'BTC', 'ETH')
            - Default: 'BTC'

        quote_coin: str
            - Quote currency (default: 'USD')
            - Usually 'USD' for options

        period: int
            - Volatility calculation period in days
            - Common values: 7, 14, 30, 60, 90
            - Default: 7 (7-day average)

        start_time: int (optional)
            - Start timestamp in milliseconds
            - If not provided, fetches recent data

        end_time: int (optional)
            - End timestamp in milliseconds
            - If not provided, fetches up to current time

        Important Limitations:
        ---------------------
        - Category must be "option"
        - Provides hourly option volatility data
        - Can query up to 2 years of historical data
        - Time range limited to 30 days maximum per request

        Example Usage:
        --------------
        downloader = ByBitImpliedVolatilityDownloader()

        # Get current implied volatility
        current_iv = downloader.get_implied_volatility('BTC', 'USD', period=30)

        # Get historical data (last 30 days)
        historical_iv = downloader.get_historical_implied_volatility(
            base_coin='ETH',
            quote_coin='USD',
            period=7,
            days_back=30
        )

        # Download and save to file
        downloader.download_and_save(
            base_coin='BTC',
            quote_coin='USD',
            period=30,
            days_back=30,
            output_file='btc_iv_30d.json'
        )

        Data Interpretation:
        -------------------
        - value: Implied volatility as decimal (e.g., 0.5 = 50% volatility)
        - time: Timestamp of the volatility calculation
        - period: Period used for calculation (in days)

        Higher IV indicates higher expected price movement
        Lower IV indicates lower expected price movement

        Rate Limiting:
        --------------
        - Automatic rate limiting with 1-second delays
        - Respect Bybit API limits (600 requests/minute)
        """
        print(help_text)

    def get_implied_volatility(self,
                             base_coin: str = "BTC",
                             quote_coin: str = "USD",
                             period: int = 7,
                             start_time: Optional[int] = None,
                             end_time: Optional[int] = None) -> Dict:
        """
        Get implied volatility data from Bybit API v5.

        Args:
            base_coin: Base cryptocurrency (e.g., 'BTC', 'ETH')
            quote_coin: Quote currency (default: 'USD')
            period: Volatility calculation period in days
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds

        Returns:
            Dict containing API response with implied volatility data
        """
        # Validate inputs
        self._validate_base_coin(base_coin)
        self._validate_quote_coin(quote_coin)

        params = {
            "category": "option",
            "baseCoin": base_coin.upper(),
            "quoteCoin": quote_coin.upper(),
            "period": period
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.info(f"Requesting implied volatility for {base_coin}{quote_coin} (period: {period}d) - attempt {attempt + 1}")

                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(self.BASE_URL, params=params, headers=self.headers)
                    response.raise_for_status()

                    data = response.json()

                    if data.get("retCode") == 0:
                        result_list = data.get('result', [])
                        self.logger.info(f"Success! Retrieved {len(result_list)} data points")
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

    def get_historical_implied_volatility(self,
                                        base_coin: str = "BTC",
                                        quote_coin: str = "USD",
                                        period: int = 7,
                                        days_back: int = 30) -> List[Dict]:
        """
        Get historical implied volatility data for a specified number of days.

        Note: Limited to 30-day chunks due to API limitations.

        Args:
            base_coin: Base cryptocurrency
            quote_coin: Quote currency
            period: Volatility calculation period in days
            days_back: Number of days to go back from current time (max 30 per request)

        Returns:
            List of all implied volatility data points
        """

        end_time = int(time.time() * 1000)  # Current time in ms
        start_time = end_time - (min(days_back, 30) * 24 * 60 * 60 * 1000)  # Limited to 30 days

        if days_back > 30:
            self.logger.warning(f"days_back limited to 30 days due to API restrictions. Using 30 instead of {days_back}")

        all_data = []

        result = self.get_implied_volatility(
            base_coin=base_coin,
            quote_coin=quote_coin,
            period=period,
            start_time=start_time,
            end_time=end_time
        )

        if result.get("retCode") == 0 and result.get("result"):
            all_data = result["result"]
            self.logger.info(f"Retrieved historical data: {len(all_data)} data points")
        else:
            self.logger.warning(f"Failed to retrieve historical volatility data")

        self.logger.info(f"Total historical data points retrieved: {len(all_data)}")
        return all_data

    def download_and_save(self,
                         base_coin: str = "BTC",
                         quote_coin: str = "USD",
                         period: int = 7,
                         days_back: int = 30,
                         output_file: Optional[str] = None,
                         output_dir: str = "./implied_volatility_data") -> str:
        """
        Download implied volatility data and save to JSON file.

        Args:
            base_coin: Base cryptocurrency
            quote_coin: Quote currency
            period: Volatility calculation period in days
            days_back: Number of days to download (max 30)
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
            output_file = f"{base_coin}{quote_coin}_{period}d_iv_{days_back}d_{timestamp}.json"

        file_path = Path(output_dir) / output_file

        # Download data
        self.logger.info(f"Downloading {days_back} days of implied volatility data for {base_coin}{quote_coin}")
        data = self.get_historical_implied_volatility(
            base_coin=base_coin,
            quote_coin=quote_coin,
            period=period,
            days_back=days_back
        )

        if not data:
            self.logger.error("No data retrieved. File not saved.")
            return None

        # Calculate basic statistics
        volatilities = [float(item['value']) for item in data if 'value' in item and item['value']]

        stats = {}
        if volatilities:
            stats = {
                "avg_volatility": sum(volatilities) / len(volatilities),
                "max_volatility": max(volatilities),
                "min_volatility": min(volatilities),
                "volatility_range": max(volatilities) - min(volatilities),
                "latest_volatility": volatilities[0] if volatilities else None
            }

        # Prepare data for saving
        save_data = {
            "metadata": {
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "period": period,
                "days_back": min(days_back, 30),
                "total_data_points": len(data),
                "download_timestamp": datetime.now().isoformat(),
                "earliest_data": datetime.fromtimestamp(int(data[-1]["time"])/1000).isoformat() if data else None,
                "latest_data": datetime.fromtimestamp(int(data[0]["time"])/1000).isoformat() if data else None,
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
                self.logger.info(f"Average volatility: {stats['avg_volatility']:.4f} ({stats['avg_volatility']*100:.2f}%)")
                self.logger.info(f"Volatility range: {stats['min_volatility']:.4f} - {stats['max_volatility']:.4f}")

            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error saving file: {e}")
            return None

    def get_supported_assets(self) -> Dict[str, List[str]]:
        """
        Get a list of commonly supported assets for implied volatility.

        Returns:
            Dictionary with base coins and quote coins
        """

        return {
            "base_coins": ["BTC", "ETH", "SOL", "ADA", "DOT", "LINK", "UNI", "AVAX"],
            "quote_coins": ["USD", "USDC"],
            "common_periods": [7, 14, 30, 60, 90]
        }

    def bulk_download(self,
                     base_coins: List[str],
                     quote_coin: str = "USD",
                     period: int = 7,
                     days_back: int = 30,
                     output_dir: str = "./implied_volatility_bulk") -> Dict[str, str]:
        """
        Download implied volatility data for multiple base coins.

        Args:
            base_coins: List of base cryptocurrencies
            quote_coin: Quote currency
            period: Volatility calculation period in days
            days_back: Number of days to download
            output_dir: Output directory

        Returns:
            Dictionary mapping base_coin to saved file path
        """

        results = {}
        total_coins = len(base_coins)

        self.logger.info(f"Starting bulk download for {total_coins} base coins")

        for i, base_coin in enumerate(base_coins, 1):
            self.logger.info(f"Processing {base_coin} ({i}/{total_coins})")

            file_path = self.download_and_save(
                base_coin=base_coin,
                quote_coin=quote_coin,
                period=period,
                days_back=days_back,
                output_dir=output_dir
            )

            results[base_coin] = file_path

            # Rate limiting between symbols
            if i < total_coins:
                time.sleep(2)

        self.logger.info(f"Bulk download completed. {len(results)} files saved.")
        return results

    def _validate_base_coin(self, base_coin: str) -> None:
        """Validate base_coin parameter."""
        if not base_coin or not isinstance(base_coin, str):
            raise ValueError("Base coin must be a non-empty string")

        base_coin = base_coin.strip().upper()
        if not base_coin.isalpha():
            raise ValueError(f"Invalid base coin format: {base_coin}")

    def _validate_quote_coin(self, quote_coin: str) -> None:
        """Validate quote_coin parameter."""
        if not quote_coin or not isinstance(quote_coin, str):
            raise ValueError("Quote coin must be a non-empty string")

        quote_coin = quote_coin.strip().upper()
        if not quote_coin.isalpha():
            raise ValueError(f"Invalid quote coin format: {quote_coin}")