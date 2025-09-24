"""
Example usage of the ByBitOpenInterestDownloader.

This script demonstrates how to download and analyze open interest data
from Bybit using the new open interest functionality.
"""

from bybit_data_downloader import ByBitOpenInterestDownloader
import json
from datetime import datetime

def main():
    """Example usage of the ByBitOpenInterestDownloader."""

    print("🚀 ByBit Open Interest Downloader - Example Usage")
    print("=" * 55)

    # Initialize downloader
    downloader = ByBitOpenInterestDownloader(timeout=30)

    # Show help information
    print("\n📖 Help Information:")
    print("-" * 25)
    downloader.help()

    # Test 1: Get current open interest
    print("\n📊 Test 1: Current Open Interest")
    print("-" * 35)

    current_oi = downloader.get_open_interest(
        symbol='BTCUSDT',
        category='linear',
        interval_time='1d',
        limit=5
    )

    if current_oi.get("retCode") == 0:
        latest = current_oi["result"]["list"][0]
        timestamp = datetime.fromtimestamp(int(latest["timestamp"])/1000)
        print(f"✅ Latest BTC Open Interest: {latest['openInterest']} BTC")
        print(f"🕐 Timestamp: {timestamp}")
    else:
        print(f"❌ Error: {current_oi.get('retMsg', 'Unknown error')}")

    # Test 2: Get historical data (last 7 days)
    print("\n📈 Test 2: Historical Data (7 days)")
    print("-" * 38)

    historical_data = downloader.get_historical_open_interest(
        symbol='ETHUSDT',
        category='linear',
        interval_time='4h',
        days_back=7
    )

    print(f"📊 Retrieved {len(historical_data)} data points for ETH")
    if historical_data:
        print(f"📅 Date range: {datetime.fromtimestamp(int(historical_data[-1]['timestamp'])/1000).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(int(historical_data[0]['timestamp'])/1000).strftime('%Y-%m-%d')}")

    # Test 3: Download and save to file
    print("\n💾 Test 3: Download and Save")
    print("-" * 30)

    saved_file = downloader.download_and_save(
        symbol='BTCUSDT',
        category='linear',
        interval_time='1d',
        days_back=30,
        output_dir='./open_interest_data'
    )

    if saved_file:
        print(f"✅ Data saved to: {saved_file}")

        # Load and display summary
        with open(saved_file, 'r') as f:
            saved_data = json.load(f)

        metadata = saved_data['metadata']
        print(f"📊 Summary:")
        print(f"   Symbol: {metadata['symbol']}")
        print(f"   Data points: {metadata['total_data_points']}")
        print(f"   Date range: {metadata['earliest_data'][:10]} to {metadata['latest_data'][:10]}")

    # Test 4: Get supported symbols
    print("\n🎯 Test 4: Supported Symbols")
    print("-" * 32)

    linear_symbols = downloader.get_supported_symbols('linear')
    inverse_symbols = downloader.get_supported_symbols('inverse')

    print(f"📈 Linear contracts: {len(linear_symbols)} symbols")
    print(f"   Examples: {', '.join(linear_symbols[:5])}")
    print(f"🔄 Inverse contracts: {len(inverse_symbols)} symbols")
    print(f"   Examples: {', '.join(inverse_symbols[:3])}")

    # Test 5: Bulk download (small sample)
    print("\n📦 Test 5: Bulk Download (Sample)")
    print("-" * 37)

    sample_symbols = ['BTCUSDT', 'ETHUSDT']
    bulk_results = downloader.bulk_download(
        symbols=sample_symbols,
        category='linear',
        interval_time='1d',
        days_back=3,  # Small sample for testing
        output_dir='./open_interest_bulk'
    )

    print(f"✅ Bulk download completed:")
    for symbol, file_path in bulk_results.items():
        if file_path:
            print(f"   {symbol}: {file_path}")
        else:
            print(f"   {symbol}: ❌ Failed")

    print("\n" + "=" * 55)
    print("🎉 Example completed successfully!")
    print("📂 Check the 'open_interest_data' and 'open_interest_bulk' directories for saved files.")

if __name__ == "__main__":
    main()