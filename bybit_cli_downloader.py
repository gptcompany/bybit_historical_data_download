#!/usr/bin/env python3
"""
Bybit CLI Downloader - Script simile al binance-history-data-downloader
Usage: python bybit_cli_downloader.py --symbol BTCUSDT --start-date 2020-05-01 --end-date 2020-05-10 --data-type trade --market contract
"""

import argparse
import sys
import os
from datetime import datetime

# Aggiungi la directory src al path
sys.path.append('/media/sam/1TB1/bybit_data_downloader/src')

from bybit_data_downloader import ByBitHistoricalDataDownloader
from bybit_data_downloader import ByBitFundingRateDownloader
from bybit_data_downloader import ByBitOpenInterestDownloader
from bybit_data_downloader import ByBitLongShortRatioDownloader

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Bybit Historical Data Downloader CLI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Download trade data
  python bybit_cli_downloader.py --symbol BTCUSDT --start-date 2020-05-01 --end-date 2020-05-10 --data-type trade --market contract

  # Download orderbook data
  python bybit_cli_downloader.py --symbol BTCUSDT --start-date 2024-01-01 --end-date 2024-01-03 --data-type orderbook --market contract

  # Download funding rates
  python bybit_cli_downloader.py --symbol BTCUSDT --data-type funding --days-back 365

  # Download open interest
  python bybit_cli_downloader.py --symbol BTCUSDT --data-type openinterest --days-back 30

Data locations:
  ./downloaded_data/      - Trade/orderbook historical data
  ./funding_rate_data/    - Funding rate data
  ./open_interest_data/   - Open interest data
  ./long_short_ratio_data/- Long-short ratio data
        """
    )

    parser.add_argument('--symbol', required=True, help='Trading symbol (e.g., BTCUSDT)')
    parser.add_argument('--start-date', help='Start date (YYYY-MM-DD) for historical data')
    parser.add_argument('--end-date', help='End date (YYYY-MM-DD) for historical data')
    parser.add_argument('--data-type', required=True,
                        choices=['trade', 'orderbook', 'funding', 'openinterest', 'longshortratio'],
                        help='Type of data to download')
    parser.add_argument('--market', choices=['contract', 'spot'], default='contract',
                        help='Market type (contract/spot) - default: contract')
    parser.add_argument('--days-back', type=int, default=30,
                        help='Days back for funding/openinterest/longshortratio data - default: 30')
    parser.add_argument('--output-dir', default='./downloaded_data',
                        help='Output directory - default: ./downloaded_data')
    parser.add_argument('--parallel', type=int, default=5,
                        help='Number of parallel downloads - default: 5')
    parser.add_argument('--timeout', type=int, default=60,
                        help='Request timeout in seconds - default: 60')

    return parser.parse_args()

def download_historical_data(symbol, start_date, end_date, data_type, market, output_dir, parallel, timeout):
    """Download historical trade/orderbook data."""
    print(f"📈 Downloading {data_type} data for {symbol} ({market})")
    print(f"📅 Period: {start_date} to {end_date}")
    print(f"📁 Output: {output_dir}")

    downloader = ByBitHistoricalDataDownloader(parallel_downloads=parallel, timeout=timeout)

    try:
        stats = downloader.download_data(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            biz_type=market,
            product_id=data_type,
            output_dir=output_dir
        )
        print(f"✅ Download completed: {stats}")
        return True
    except Exception as e:
        print(f"❌ Download failed: {e}")
        return False

def download_funding_rates(symbol, days_back):
    """Download funding rate data."""
    print(f"💰 Downloading funding rates for {symbol}")
    print(f"📅 Days back: {days_back}")

    try:
        downloader = ByBitFundingRateDownloader(timeout=30)

        # Current rate
        current_rate = downloader.get_funding_rate(symbol, 'linear')
        if current_rate.get('result', {}).get('list'):
            rate_value = float(current_rate['result']['list'][0].get('fundingRate', 0))
            print(f"📊 Current funding rate: {rate_value:.8f} ({rate_value*100:.6f}%)")

        # Historical data
        file_path = downloader.download_and_save(
            symbol=symbol,
            category='linear',
            days_back=days_back,
            output_dir='./funding_rate_data'
        )
        print(f"✅ Funding rates saved to: {file_path}")
        return True
    except Exception as e:
        print(f"❌ Funding rates download failed: {e}")
        return False

def download_open_interest(symbol, days_back):
    """Download open interest data."""
    print(f"📊 Downloading open interest for {symbol}")
    print(f"📅 Days back: {days_back}")

    try:
        downloader = ByBitOpenInterestDownloader(timeout=30)

        # Current OI
        current_oi = downloader.get_open_interest(symbol, 'linear')
        if current_oi.get('result', {}).get('list'):
            oi_value = current_oi['result']['list'][0].get('openInterest', 'N/A')
            print(f"📊 Current open interest: {oi_value}")

        # Historical data
        historical_data = downloader.get_historical_open_interest(
            symbol=symbol,
            category='linear',
            interval_time='1d',
            days_back=days_back
        )

        # Save to file
        os.makedirs('./open_interest_data', exist_ok=True)
        filename = f"./open_interest_data/{symbol}_openinterest_{days_back}d_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        import json
        with open(filename, 'w') as f:
            json.dump(historical_data, f, indent=2)

        print(f"✅ Open interest saved to: {filename}")
        print(f"📈 Historical records: {len(historical_data.get('result', {}).get('list', []))}")
        return True
    except Exception as e:
        print(f"❌ Open interest download failed: {e}")
        return False

def download_long_short_ratio(symbol, days_back):
    """Download long-short ratio data."""
    print(f"⚖️  Downloading long-short ratio for {symbol}")
    print(f"📅 Days back: {days_back}")

    try:
        downloader = ByBitLongShortRatioDownloader(timeout=30)

        # Current ratio
        current_ratio = downloader.get_long_short_ratio(symbol, 'linear')
        result_list = current_ratio.get('result', {}).get('list', [])
        if result_list:
            buy_ratio = float(result_list[0].get('buyRatio', 0))
            sell_ratio = float(result_list[0].get('sellRatio', 0))
            print(f"📊 Current sentiment - Long: {buy_ratio:.1%}, Short: {sell_ratio:.1%}")

        # Historical data
        file_path = downloader.download_and_save(
            symbol=symbol,
            category='linear',
            period='1d',
            days_back=days_back,
            output_dir='./long_short_ratio_data'
        )
        print(f"✅ Long-short ratio saved to: {file_path}")
        return True
    except Exception as e:
        print(f"❌ Long-short ratio download failed: {e}")
        return False

def main():
    """Main CLI function."""
    print("🚀 Bybit CLI Data Downloader")
    print("=" * 50)

    args = parse_arguments()

    # Validate arguments
    if args.data_type in ['trade', 'orderbook']:
        if not args.start_date or not args.end_date:
            print("❌ --start-date and --end-date are required for trade/orderbook data")
            sys.exit(1)

    # Create output directories
    if args.data_type in ['trade', 'orderbook']:
        os.makedirs(args.output_dir, exist_ok=True)

    success = False

    # Execute download based on data type
    if args.data_type in ['trade', 'orderbook']:
        success = download_historical_data(
            args.symbol, args.start_date, args.end_date,
            args.data_type, args.market, args.output_dir,
            args.parallel, args.timeout
        )
    elif args.data_type == 'funding':
        success = download_funding_rates(args.symbol, args.days_back)
    elif args.data_type == 'openinterest':
        success = download_open_interest(args.symbol, args.days_back)
    elif args.data_type == 'longshortratio':
        success = download_long_short_ratio(args.symbol, args.days_back)

    if success:
        print(f"\n🎉 Download completed successfully!")
        print(f"📁 Check data in the respective directories")
    else:
        print(f"\n💥 Download failed!")
        sys.exit(1)

if __name__ == "__main__":
    main()