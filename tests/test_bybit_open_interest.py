"""
Test script per richiedere open interest storico da Bybit API v5
Basato sulla documentazione ufficiale: https://bybit-exchange.github.io/docs/v5/market/open-interest
"""

import requests
import json
from datetime import datetime, timedelta
import time

def get_bybit_open_interest(symbol: str = "BTCUSDT",
                           category: str = "linear",
                           interval_time: str = "1d",
                           limit: int = 50,
                           start_time: int = None,
                           end_time: int = None):
    """
    Richiede open interest storico da Bybit API v5

    Args:
        symbol: Symbol name (e.g., "BTCUSDT")
        category: Product type ("linear", "inverse")
        interval_time: Time interval ("5min", "15min", "30min", "1h", "4h", "1d")
        limit: Data size per page (1-200, default 50)
        start_time: Start timestamp in milliseconds
        end_time: End timestamp in milliseconds

    Returns:
        dict: API response
    """

    url = "https://api.bybit.com/v5/market/open-interest"

    params = {
        "category": category,
        "symbol": symbol,
        "intervalTime": interval_time,
        "limit": limit
    }

    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    try:
        print(f"🔄 Requesting open interest data for {symbol}...")
        print(f"📊 Parameters: {params}")

        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if data.get("retCode") == 0:
            print(f"✅ Success! Retrieved {len(data['result']['list'])} data points")
            return data
        else:
            print(f"❌ API Error: {data.get('retMsg', 'Unknown error')}")
            return data

    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}")
        return None

def test_open_interest_scenarios():
    """Test diversi scenari per l'open interest"""

    print("🚀 Testing Bybit Open Interest API v5")
    print("=" * 50)

    # Test 1: Current data (ultimo mese)
    print("\n📈 Test 1: Current Open Interest (last 30 days)")
    end_time = int(time.time() * 1000)  # Now
    start_time = end_time - (30 * 24 * 60 * 60 * 1000)  # 30 days ago

    result1 = get_bybit_open_interest(
        symbol="BTCUSDT",
        category="linear",
        interval_time="1d",
        limit=50,
        start_time=start_time,
        end_time=end_time
    )

    if result1 and result1.get("retCode") == 0:
        oi_data = result1["result"]["list"]
        if oi_data:
            latest = oi_data[0]
            print(f"💰 Latest Open Interest: {latest['openInterest']}")
            print(f"🕐 Timestamp: {datetime.fromtimestamp(int(latest['timestamp'])/1000)}")

    time.sleep(1)  # Rate limiting

    # Test 2: Historical data (6 mesi fa)
    print("\n📊 Test 2: Historical Data (6 months ago)")
    end_time_hist = int(time.time() * 1000) - (6 * 30 * 24 * 60 * 60 * 1000)  # 6 months ago
    start_time_hist = end_time_hist - (7 * 24 * 60 * 60 * 1000)  # 7 days period

    result2 = get_bybit_open_interest(
        symbol="BTCUSDT",
        category="linear",
        interval_time="1h",
        limit=100,
        start_time=start_time_hist,
        end_time=end_time_hist
    )

    if result2 and result2.get("retCode") == 0:
        print(f"📈 Historical data points: {len(result2['result']['list'])}")

    time.sleep(1)

    # Test 3: ETH data
    print("\n🔷 Test 3: ETH Open Interest")
    result3 = get_bybit_open_interest(
        symbol="ETHUSDT",
        category="linear",
        interval_time="4h",
        limit=20
    )

    if result3 and result3.get("retCode") == 0:
        oi_data = result3["result"]["list"]
        if oi_data:
            print(f"💎 ETH Open Interest: {oi_data[0]['openInterest']}")

    time.sleep(1)

    # Test 4: Contract inverso (BTC)
    print("\n⚡ Test 4: Inverse Contract (BTCUSD)")
    result4 = get_bybit_open_interest(
        symbol="BTCUSD",
        category="inverse",
        interval_time="1d",
        limit=10
    )

    if result4 and result4.get("retCode") == 0:
        print(f"🔄 Inverse contract data available: {len(result4['result']['list'])} points")

    # Summary
    print("\n" + "=" * 50)
    print("📋 SUMMARY:")
    print(f"✅ Current data test: {'SUCCESS' if result1 and result1.get('retCode') == 0 else 'FAILED'}")
    print(f"✅ Historical data test: {'SUCCESS' if result2 and result2.get('retCode') == 0 else 'FAILED'}")
    print(f"✅ ETH data test: {'SUCCESS' if result3 and result3.get('retCode') == 0 else 'FAILED'}")
    print(f"✅ Inverse contract test: {'SUCCESS' if result4 and result4.get('retCode') == 0 else 'FAILED'}")

    # Return first successful result for inspection
    return result1 or result2 or result3 or result4

def print_sample_data(data):
    """Print structured sample of the data"""
    if not data or data.get("retCode") != 0:
        print("❌ No valid data to display")
        return

    result = data["result"]
    print(f"\n📊 SAMPLE DATA for {result['symbol']} ({result['category']}):")
    print("-" * 60)

    for i, item in enumerate(result["list"][:5]):  # Show first 5 items
        timestamp = datetime.fromtimestamp(int(item["timestamp"])/1000)
        print(f"{i+1:2d}. {timestamp.strftime('%Y-%m-%d %H:%M')} | OI: {item['openInterest']:>15}")

    if len(result["list"]) > 5:
        print(f"... and {len(result['list']) - 5} more data points")

if __name__ == "__main__":
    result = test_open_interest_scenarios()

    if result:
        print_sample_data(result)

        # Save sample to file
        with open('/media/sam/1TB1/EVO/bybit_open_interest_sample.json', 'w') as f:
            json.dump(result, f, indent=2)
        print(f"\n💾 Sample data saved to: bybit_open_interest_sample.json")