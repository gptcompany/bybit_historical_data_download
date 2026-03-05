import logging
import time
import json
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path
import httpx

class ByBitUnifiedDownloader:
    SUPPORTED_TYPES = ['open_interest', 'long_short_ratio', 'implied_volatility', 'funding_rate']

    ENDPOINTS = {
        "open_interest": {
            "url": "https://api.bybit.com/v5/market/open-interest",
            "time_param": "intervalTime",
            "max_limit": 200,
            "supports_category": True,
            "supports_symbol": True
        },
        "long_short_ratio": {
            "url": "https://api.bybit.com/v5/market/account-ratio",
            "time_param": "period",
            "max_limit": 500,
            "supports_category": True,
            "supports_symbol": True
        },
        "implied_volatility": {
            "url": "https://api.bybit.com/v5/market/historical-volatility",
            "time_param": "period",
            "max_limit": 200,
            "supports_category": False,
            "supports_symbol": False
        },
        "funding_rate": {
            "url": "https://api.bybit.com/v5/market/funding/history",
            "time_param": None,
            "max_limit": 200,
            "supports_category": True,
            "supports_symbol": True
        }
    }

    def __init__(self, data_type: str, timeout: int = 30):
        if data_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported data_type: {data_type}. "
                           f"Supported types: {self.SUPPORTED_TYPES}")
        self.data_type = data_type
        self.endpoint_config = self.ENDPOINTS[data_type]
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

    def get_data(self, symbol: Optional[str] = None, category: str = "linear",
                 interval_time: Optional[str] = None, limit: int = 50,
                 start_time: Optional[int] = None, end_time: Optional[int] = None,
                 base_coin: Optional[str] = None, quote_coin: Optional[str] = None) -> Dict:
        """Get data from Bybit API for the configured data type."""
        config = self.endpoint_config

        # Build parameters based on endpoint configuration
        params = {"limit": limit}

        # Add symbol/category or base_coin/quote_coin based on endpoint
        if config['supports_symbol']:
            self._validate_symbol(symbol)
            params["symbol"] = symbol.upper()

        if config['supports_category']:
            self._validate_category(category)
            params["category"] = category

        # Special handling for implied volatility
        if self.data_type == 'implied_volatility':
            if base_coin:
                self._validate_base_coin(base_coin)
                params["baseCoin"] = base_coin.upper()
            if quote_coin:
                self._validate_quote_coin(quote_coin)
                params["quoteCoin"] = quote_coin.upper()

        # Add time interval parameter with correct name
        if config['time_param'] and interval_time:
            params[config['time_param']] = interval_time

        # Add time range if provided
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        # Execute request with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                identifier = symbol or f"{base_coin}/{quote_coin}" if base_coin and quote_coin else "data"
                self.logger.info(f"Requesting {self.data_type} for {identifier} ({category}) - attempt {attempt + 1}")

                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(config['url'], params=params, headers=self.headers)
                    response.raise_for_status()

                    data = response.json()

                    if data.get("retCode") == 0:
                        result_list = data.get('result', {}).get('list', [])
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

    def get_historical_data(self, symbol: Optional[str] = None, category: str = "linear",
                           interval_time: str = "1d", days_back: int = 30,
                           base_coin: Optional[str] = None, quote_coin: Optional[str] = None) -> List[Dict]:
        """Get historical data for a specified number of days with automatic pagination."""
        config = self.endpoint_config
        end_time = int(time.time() * 1000)  # Current time in ms
        start_time = end_time - (days_back * 24 * 60 * 60 * 1000)  # days_back ago

        all_data = []
        current_start = start_time

        while current_start < end_time:
            # Calculate chunk end time
            chunk_end = min(current_start + (7 * 24 * 60 * 60 * 1000), end_time)  # 7 days max

            result = self.get_data(
                symbol=symbol,
                category=category,
                interval_time=interval_time,
                limit=config['max_limit'],
                start_time=current_start,
                end_time=chunk_end,
                base_coin=base_coin,
                quote_coin=quote_coin
            )

            if result.get("retCode") == 0 and result.get("result", {}).get('list'):
                chunk_data = result["result"]['list']
                all_data.extend(chunk_data)
                self.logger.info(f"Retrieved chunk: {len(chunk_data)} data points")
            else:
                self.logger.warning(f"Failed to retrieve data for chunk starting {current_start}")
                break

            # Move to next chunk
            current_start = chunk_end + 1

            # Rate limiting
            time.sleep(1)

        self.logger.info(f"Total historical data points retrieved: {len(all_data)}")
        return all_data

    def download_and_save(self, symbol: Optional[str] = None, category: str = "linear",
                         interval_time: str = "1d", days_back: int = 30,
                         output_file: Optional[str] = None, output_dir: str = None,
                         base_coin: Optional[str] = None, quote_coin: Optional[str] = None) -> str:
        """Download data and save to JSON file."""
        # Set default output directory
        if not output_dir:
            output_dir = f"./{self.data_type}_data"

        # Create output directory
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename if not provided
        if not output_file:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            identifier = symbol or f"{base_coin}_{quote_coin}" if base_coin and quote_coin else "data"
            output_file = f"{identifier}_{self.data_type}_{interval_time}_{days_back}d_{timestamp}.json"

        file_path = Path(output_dir) / output_file

        # Download data
        identifier = symbol or f"{base_coin}/{quote_coin}" if base_coin and quote_coin else "data"
        self.logger.info(f"Downloading {days_back} days of {self.data_type} data for {identifier}")

        data = self.get_historical_data(
            symbol=symbol,
            category=category,
            interval_time=interval_time,
            days_back=days_back,
            base_coin=base_coin,
            quote_coin=quote_coin
        )

        if not data:
            self.logger.error("No data retrieved. File not saved.")
            return None

        # Prepare data for saving
        save_data = {
            "metadata": {
                "data_type": self.data_type,
                "symbol": symbol,
                "category": category if self.endpoint_config['supports_category'] else None,
                "base_coin": base_coin,
                "quote_coin": quote_coin,
                "interval_time": interval_time,
                "days_back": days_back,
                "total_data_points": len(data),
                "download_timestamp": datetime.now().isoformat(),
                "earliest_data": datetime.fromtimestamp(int(data[-1]["timestamp"])/1000).isoformat() if data else None,
                "latest_data": datetime.fromtimestamp(int(data[0]["timestamp"])/1000).isoformat() if data else None,
                "endpoint_url": self.endpoint_config['url']
            },
            "data": data
        }

        # Save to file
        try:
            with open(file_path, 'w') as f:
                json.dump(save_data, f, indent=2)

            self.logger.info(f"Data saved successfully to: {file_path}")
            self.logger.info(f"Total data points: {len(data)}")

            return str(file_path)

        except Exception as e:
            self.logger.error(f"Error saving file: {e}")
            return None

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