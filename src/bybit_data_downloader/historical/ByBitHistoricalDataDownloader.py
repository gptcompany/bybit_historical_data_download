import logging
import os
import time
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import httpx
import json

class ByBitHistoricalDataDownloader:
    """
    A high-performance synchronous downloader for Bybit historical data.
    
    Supports downloading trade and orderbook data for spot and contract markets
    with automatic date range splitting and parallel downloads using threading.
    """
    
    BASE_URL = "https://www.bybit.com/x-api/quote/public/support/download"
    
    def __init__(self, parallel_downloads: int = 5, timeout: int = 30):
        """
        Initialize the Bybit data downloader.
        
        Args:
            parallel_downloads: Maximum number of concurrent downloads (default: 5)
            timeout: Request timeout in seconds (default: 30)
        """
        self.parallel_downloads = parallel_downloads
        self.timeout = timeout
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        # Default headers based on the curl commands
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
        Bybit Data Downloader - Usage Guide
        ==================================
        
        Parameters:
        -----------
        symbol: str
            - Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')
            - Use fetch_symbols() to get available symbols
        
        start_date: str
            - Start date in 'YYYY-MM-DD' format
            - Example: '2025-01-01'
        
        end_date: str
            - End date in 'YYYY-MM-DD' format
            - Example: '2025-01-07'
        
        biz_type: str
            - Market type: 'spot' or 'contract'
        
        product_id: str
            - Data type: 'trade' or 'orderbook'
        
        parallel_downloads: int
            - Number of concurrent downloads (1-20 recommended)
            - Default: 5
        
        Example Usage:
        --------------
        downloader = ByBitHistoricalDataDownloader(parallel_downloads=10)
        
        # Fetch available symbols
        symbols = downloader.fetch_symbols('spot', 'trade')
        
        # Download trade data
        downloader.download_data(
            symbol='BTCUSDT',
            start_date='2025-01-01',
            end_date='2025-01-31',
            biz_type='spot',
            product_id='trade',
            output_dir='./data'
        )
        
        Supported Markets:
        ------------------
        - biz_type: 'spot', 'contract'
        - product_id: 'trade', 'orderbook'
        
        Note: API supports maximum 7-day ranges. Larger ranges are automatically split.
        """
        print(help_text)
    
    def fetch_symbols(self, biz_type: str, product_id: str) -> List[str]:
        """
        Fetch available symbols for the specified market and product type.
        
        Args:
            biz_type: Market type ('spot' or 'contract')
            product_id: Data type ('trade' or 'orderbook')
            
        Returns:
            List of available symbols
            
        Raises:
            ValueError: If invalid parameters provided
            httpx.RequestError: If API request fails
        """
        self._validate_biz_type(biz_type)
        self._validate_product_id(product_id)
        
        url = f"{self.BASE_URL}/list-options"
        params = {
            'bizType': biz_type,
            'productId': product_id
        }
        
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.get(url, params=params, headers=self.headers)
                response.raise_for_status()
                
                data = response.json()
                if data.get('ret_code') != 0:
                    raise Exception(f"API Error: {data.get('ret_msg', 'Unknown error')}")
                
                symbols = data.get('result', {}).get('symbols', [])
                self.logger.info(f"Fetched {len(symbols)} symbols for {biz_type}/{product_id}")
                return symbols
                
            except httpx.RequestError as e:
                self.logger.error(f"Failed to fetch symbols: {e}")
                raise
    
    def _split_date_range(self, start_date: str, end_date: str) -> List[Tuple[str, str]]:
        """
        Split date range into 7-day chunks as required by the API.
        
        Args:
            start_date: Start date in 'YYYY-MM-DD' format
            end_date: End date in 'YYYY-MM-DD' format
            
        Returns:
            List of (start_date, end_date) tuples, each spanning max 7 days
        """
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        
        chunks = []
        current_start = start
        
        while current_start <= end:
            current_end = min(current_start + timedelta(days=6), end)
            chunks.append((
                current_start.strftime('%Y-%m-%d'),
                current_end.strftime('%Y-%m-%d')
            ))
            current_start = current_end + timedelta(days=1)
        
        return chunks
    
    def _get_download_files(self, symbol: str, start_date: str, end_date: str,
                           biz_type: str, product_id: str) -> List[Dict]:
        """
        Get download file information for a specific date range.
        
        Args:
            symbol: Trading pair symbol
            start_date: Start date in 'YYYY-MM-DD' format
            end_date: End date in 'YYYY-MM-DD' format
            biz_type: Market type ('spot' or 'contract')
            product_id: Data type ('trade' or 'orderbook')
            
        Returns:
            List of file information dictionaries
        """
        url = f"{self.BASE_URL}/list-files"
        params = {
            'bizType': biz_type,
            'productId': product_id,
            'symbols': symbol,
            'interval': 'daily',
            'periods': '',
            'startDay': start_date,
            'endDay': end_date
        }
        
        with httpx.Client(timeout=self.timeout) as client:
            try:
                response = client.get(url, params=params, headers=self.headers)
                response.raise_for_status()
                
                data = response.json()
                if data.get('ret_code') != 0:
                    raise Exception(f"API Error: {data.get('ret_msg', 'Unknown error')}")
                
                return data.get('result', {}).get('list', [])
                
            except httpx.RequestError as e:
                self.logger.error(f"Failed to get file list: {e}")
                raise
    
    def _download_file(self, file_info: Dict, output_dir: str) -> bool:
        """
        Download a single file with retry logic.
        
        Args:
            file_info: File information dictionary from API
            output_dir: Output directory path
            
        Returns:
            True if download successful, False otherwise
        """
        url = file_info['url']
        filename = file_info['filename']
        file_path = Path(output_dir) / filename
        
        # Skip if file already exists and has correct size
        if file_path.exists():
            expected_size = int(file_info.get('size', 0))
            if expected_size > 0 and file_path.stat().st_size == expected_size:
                self.logger.info(f"File already exists: {filename}")
                return True
        
        # Create output directory if it doesn't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with httpx.Client(timeout=60) as client:
                    with client.stream('GET', url) as response:
                        response.raise_for_status()
                        
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_bytes(chunk_size=8192):
                                f.write(chunk)
                
                # Verify file size
                expected_size = int(file_info.get('size', 0))
                actual_size = file_path.stat().st_size
                
                if expected_size > 0 and actual_size != expected_size:
                    self.logger.warning(f"Size mismatch for {filename}: expected {expected_size}, got {actual_size}")
                    file_path.unlink()  # Delete incomplete file
                    continue
                
                self.logger.info(f"Downloaded: {filename} ({actual_size:,} bytes)")
                return True
                
            except Exception as e:
                self.logger.error(f"Download attempt {attempt + 1} failed for {filename}: {e}")
                if file_path.exists():
                    file_path.unlink()  # Clean up partial download
                
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
        
        self.logger.error(f"Failed to download {filename} after {max_retries} attempts")
        return False
    
    def download_data(self, symbol: str, start_date: str, end_date: str,
                     biz_type: str, product_id: str, output_dir: str = "./data") -> Dict[str, int]:
        """
        Download historical data for the specified parameters.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
            start_date: Start date in 'YYYY-MM-DD' format
            end_date: End date in 'YYYY-MM-DD' format
            biz_type: Market type ('spot' or 'contract')
            product_id: Data type ('trade' or 'orderbook')
            output_dir: Output directory path (default: './data')
            
        Returns:
            Dictionary with download statistics
            
        Raises:
            ValueError: If invalid parameters provided
        """
        # Validate inputs
        self._validate_biz_type(biz_type)
        self._validate_product_id(product_id)
        self._validate_date_format(start_date)
        self._validate_date_format(end_date)
        
        if datetime.strptime(start_date, '%Y-%m-%d') > datetime.strptime(end_date, '%Y-%m-%d'):
            raise ValueError("start_date must be before or equal to end_date")
        
        self.logger.info(f"Starting download: {symbol} {biz_type}/{product_id} from {start_date} to {end_date}")
        
        # Split date range into 7-day chunks
        date_chunks = self._split_date_range(start_date, end_date)
        self.logger.info(f"Split into {len(date_chunks)} date chunks")
        
        # Collect all files to download
        all_files = []
        for chunk_start, chunk_end in date_chunks:
            try:
                files = self._get_download_files(symbol, chunk_start, chunk_end, biz_type, product_id)
                all_files.extend(files)
                self.logger.info(f"Found {len(files)} files for {chunk_start} to {chunk_end}")
            except Exception as e:
                self.logger.error(f"Failed to get files for {chunk_start} to {chunk_end}: {e}")
        
        if not all_files:
            self.logger.warning("No files found for the specified parameters")
            return {'total_files': 0, 'downloaded': 0, 'failed': 0}
        
        # Create output directory structure
        output_path = Path(output_dir) / biz_type / product_id / symbol
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Download files in parallel using ThreadPoolExecutor
        self.logger.info(f"Starting parallel download of {len(all_files)} files...")
        successful = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=self.parallel_downloads) as executor:
            # Submit all download tasks
            future_to_file = {
                executor.submit(self._download_file, file_info, str(output_path)): file_info
                for file_info in all_files
            }
            
            # Process completed downloads
            for future in as_completed(future_to_file):
                file_info = future_to_file[future]
                try:
                    result = future.result()
                    if result:
                        successful += 1
                    else:
                        failed += 1
                except Exception as e:
                    self.logger.error(f"Download task failed for {file_info['filename']}: {e}")
                    failed += 1
        
        stats = {
            'total_files': len(all_files),
            'downloaded': successful,
            'failed': failed
        }
        
        self.logger.info(f"Download completed: {successful}/{len(all_files)} files successful")
        return stats
    
    def _validate_biz_type(self, biz_type: str) -> None:
        """Validate biz_type parameter."""
        if biz_type not in ['spot', 'contract']:
            raise ValueError("biz_type must be 'spot' or 'contract'")
    
    def _validate_product_id(self, product_id: str) -> None:
        """Validate product_id parameter."""
        if product_id not in ['trade', 'orderbook']:
            raise ValueError("product_id must be 'trade' or 'orderbook'")
    
    def _validate_date_format(self, date_str: str) -> None:
        """Validate date string format."""
        try:
            datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            raise ValueError(f"Invalid date format: {date_str}. Use 'YYYY-MM-DD'")