from bybit_data_downloader import ByBitHistoricalDataDownloader
import asyncio

def main():
    """Example usage of the ByBitHistoricalDataDownloader."""
    downloader = ByBitHistoricalDataDownloader(parallel_downloads=10)
    
    # Show help
    # downloader.help()
    
    # # Fetch available symbols
    # print("\nFetching symbols...")
    # symbols = downloader.fetch_symbols('spot', 'trade')
    # print(f"Available symbols: {symbols[:10]}...")  # Show first 10
    
    # Download sample data
    print("\nDownloading sample data...")
    stats = downloader.download_data(
        symbol='BTCUSDT',
        start_date='2025-07-01',
        end_date='2025-07-07',
        biz_type='spot',
        product_id='trade',
        output_dir='/bybit_data/'
    )
    
    print(f"Download stats: {stats}")

if __name__ == "__main__":
    main()