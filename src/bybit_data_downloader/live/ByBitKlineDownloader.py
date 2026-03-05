import logging
import os
import time
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any
from pathlib import Path
import httpx

class ByBitKlineDownloader:
    """
    A high-performance downloader for Bybit historical kline data using API v5.
    
    Supports downloading kline data for spot, linear, and inverse markets
    with automatic pagination and daily JSON export for idempotency.
    """
    
    BASE_URL = "https://api.bybit.com/v5/market/kline"
    
    INTERVAL_MAPPING = {
        '1m': '1',
        '3m': '3',
        '5m': '5',
        '15m': '15',
        '30m': '30',
        '1h': '60',
        '2h': '120',
        '4h': '240',
        '6h': '360',
        '12h': '720',
        '1d': 'D',
        '1w': 'W',
        '1mo': 'M'
    }
    
    def __init__(self, timeout: int = 30):
        """
        Initialize the Bybit kline downloader.
        
        Args:
            timeout: Request timeout in seconds (default: 30)
        """
        self.timeout = timeout
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Browser-like headers
        self.headers = {
            'accept': '*/*',
            'accept-language': 'en-US,en;q=0.9',
            'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }

    def get_klines(self, 
                   symbol: str, 
                   interval: str, 
                   category: str = "linear", 
                   start_time: Optional[int] = None, 
                   end_time: Optional[int] = None,
                   limit: int = 1000) -> Dict[str, Any]:
        """
        Fetch kline data from Bybit API v5.
        """
        bybit_interval = self.INTERVAL_MAPPING.get(interval, interval)
        
        params = {
            "category": category,
            "symbol": symbol.upper(),
            "interval": bybit_interval,
            "limit": limit
        }
        
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
            
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.get(self.BASE_URL, params=params, headers=self.headers)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data.get("retCode") == 0:
                        return data
                    else:
                        self.logger.error(f"Bybit API Error: {data.get('retMsg')} (code: {data.get('retCode')})")
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                        else:
                            return data
            except Exception as e:
                self.logger.error(f"Network error on attempt {attempt+1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return {"retCode": -1, "retMsg": str(e)}
        return {"retCode": -1, "retMsg": "Max retries exceeded"}

    def download_range(self,
                       symbol: str,
                       start_date: str,
                       end_date: str,
                       interval: str = "1m",
                       category: str = "linear",
                       output_dir: str = "data/historical/klines") -> Dict[str, int]:
        """
        Download kline data for a specific date range, saving as daily files.
        """
        self.logger.info(f"🚀 Starting kline download for {symbol} ({category}) from {start_date} to {end_date} (interval: {interval})")
        
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        # Adjust market name for directory structure if needed
        market = category
        if market == 'linear' and category == 'linear': # Already linear
            pass
            
        base_path = Path(output_dir) / market / symbol / interval
        base_path.mkdir(parents=True, exist_ok=True)
        
        stats = {"total_days": 0, "successful_days": 0, "failed_days": 0, "total_records": 0}
        
        current_dt = start_dt
        while current_dt <= end_dt:
            stats["total_days"] += 1
            date_str = current_dt.strftime('%Y-%m-%d')
            filename = f"{symbol}_{interval}_{date_str}.json"
            file_path = base_path / filename
            
            # Daily time range in ms
            day_start_ms = int(current_dt.timestamp() * 1000)
            day_end_ms = int((current_dt + timedelta(days=1)).timestamp() * 1000) - 1
            
            # Check if file exists
            if file_path.exists():
                self.logger.info(f"✅ Skipping {date_str}, already exists.")
                stats["successful_days"] += 1
                current_dt += timedelta(days=1)
                continue
            
            # Fetch data for the day
            day_data = []
            current_fetch_end = day_end_ms
            
            while current_fetch_end > day_start_ms:
                # Bybit returns newest first. We fetch from current_fetch_end backwards.
                result = self.get_klines(symbol, interval, category, end_time=current_fetch_end, limit=1000)
                
                if result.get("retCode") == 0:
                    batch = result.get("result", {}).get("list", [])
                    if not batch:
                        break
                        
                    # Filter data to stay within current day
                    valid_batch = []
                    for item in batch:
                        try:
                            ts = int(float(item[0]))
                        except (ValueError, TypeError):
                            continue
                            
                        if ts < day_start_ms:
                            continue
                        if ts <= current_fetch_end:
                            valid_batch.append(item)
                    
                    if not valid_batch:
                        break
                        
                    day_data.extend(valid_batch)
                    
                    # Find oldest timestamp in this batch
                    oldest_ts = min(int(float(item[0])) for item in valid_batch)
                    
                    if oldest_ts <= day_start_ms:
                        break
                        
                    # Move end time backward
                    current_fetch_end = oldest_ts - 1
                    
                    # Rate limit
                    time.sleep(0.1)
                else:
                    self.logger.error(f"❌ Failed to fetch klines for {date_str} at {current_fetch_end}")
                    break
            
            if day_data:
                # Sort day_data by timestamp (oldest first) before saving
                day_data.sort(key=lambda x: int(float(x[0])))
                try:
                    with open(file_path, 'w') as f:
                        json.dump({
                            "metadata": {
                                "symbol": symbol,
                                "interval": interval,
                                "category": category,
                                "date": date_str,
                                "count": len(day_data)
                            },
                            "data": day_data
                        }, f, indent=2)
                    self.logger.info(f"💾 Saved {len(day_data)} klines for {date_str}")
                    stats["successful_days"] += 1
                    stats["total_records"] += len(day_data)
                except Exception as e:
                    self.logger.error(f"❌ Error saving {file_path}: {e}")
                    stats["failed_days"] += 1
            else:
                self.logger.warning(f"⚠️ No data found for {date_str}")
                stats["failed_days"] += 1
                
            current_dt += timedelta(days=1)
            # Sleep between days
            time.sleep(0.2)
            
        return stats

    def _get_interval_ms(self, interval: str) -> int:
        """Convert interval string to milliseconds."""
        if not interval or len(interval) < 2:
            return 60 * 1000 # default 1m
            
        unit = interval[-1]
        if interval == '1mo': # Special case for 1 month
            return 30 * 24 * 60 * 60 * 1000
            
        try:
            value = int(interval[:-1])
        except ValueError:
            return 60 * 1000 # default 1m
            
        if unit == 'm':
            return value * 60 * 1000
        elif unit == 'h':
            return value * 60 * 60 * 1000
        elif unit == 'd':
            return value * 24 * 60 * 60 * 1000
        elif unit == 'w':
            return value * 7 * 24 * 60 * 60 * 1000
        else:
            return 60 * 1000 # default 1m
