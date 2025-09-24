"""
Comprehensive example testing all Bybit market metrics downloader functionality.

This script demonstrates how to download and analyze:
1. Open Interest
2. Long-Short Ratio
3. Implied Volatility
4. Historical Funding Rate

All metrics are tested for historical data availability and saved with comprehensive analysis.
"""

from bybit_data_downloader import (
    ByBitOpenInterestDownloader,
    ByBitLongShortRatioDownloader,
    ByBitImpliedVolatilityDownloader,
    ByBitFundingRateDownloader
)
import json
import time
from datetime import datetime

def test_open_interest():
    """Test Open Interest downloader with historical data analysis."""
    print("\n" + "="*60)
    print("🔥 TESTING OPEN INTEREST")
    print("="*60)

    downloader = ByBitOpenInterestDownloader()

    # Test current data
    print("\n📊 Getting current BTCUSDT open interest...")
    current_oi = downloader.get_open_interest('BTCUSDT', 'linear', '1d', limit=5)

    if current_oi.get("retCode") == 0:
        latest = current_oi["result"]["list"][0]
        timestamp = datetime.fromtimestamp(int(latest["timestamp"])/1000)
        print(f"✅ Latest BTC Open Interest: {latest['openInterest']} BTC")
        print(f"🕐 Timestamp: {timestamp}")

        # Test historical range
        print(f"\n📈 Testing historical data availability...")
        for days in [7, 30, 90, 180]:
            historical_data = downloader.get_historical_open_interest(
                symbol='BTCUSDT',
                category='linear',
                interval_time='1d',
                days_back=days
            )
            print(f"📅 {days:3d} days back: {len(historical_data):3d} data points")
            time.sleep(1)

    return current_oi.get("retCode") == 0

def test_long_short_ratio():
    """Test Long-Short Ratio downloader with sentiment analysis."""
    print("\n" + "="*60)
    print("⚖️  TESTING LONG-SHORT RATIO")
    print("="*60)

    downloader = ByBitLongShortRatioDownloader()

    # Test current data
    print("\n📊 Getting current BTCUSDT long-short ratio...")
    current_ratio = downloader.get_long_short_ratio('BTCUSDT', 'linear', '1d', limit=5)

    if current_ratio.get("retCode") == 0:
        latest = current_ratio["result"]["list"][0]
        timestamp = datetime.fromtimestamp(int(latest["timestamp"])/1000)
        buy_ratio = float(latest["buyRatio"])
        sell_ratio = float(latest["sellRatio"])

        print(f"✅ Buy Ratio (Long): {buy_ratio:.3f} ({buy_ratio*100:.1f}%)")
        print(f"✅ Sell Ratio (Short): {sell_ratio:.3f} ({sell_ratio*100:.1f}%)")
        print(f"🕐 Timestamp: {timestamp}")

        # Sentiment interpretation
        if buy_ratio > 0.6:
            sentiment = "🟢 BULLISH (High Long Positions)"
        elif sell_ratio > 0.6:
            sentiment = "🔴 BEARISH (High Short Positions)"
        else:
            sentiment = "🟡 NEUTRAL (Balanced Positions)"
        print(f"📊 Market Sentiment: {sentiment}")

        # Test historical range
        print(f"\n📈 Testing historical data availability...")
        for days in [7, 30, 90]:
            historical_data = downloader.get_historical_long_short_ratio(
                symbol='BTCUSDT',
                category='linear',
                period='1d',
                days_back=days
            )
            print(f"📅 {days:3d} days back: {len(historical_data):3d} data points")
            time.sleep(1)

    return current_ratio.get("retCode") == 0

def test_implied_volatility():
    """Test Implied Volatility downloader with volatility analysis."""
    print("\n" + "="*60)
    print("📈 TESTING IMPLIED VOLATILITY")
    print("="*60)

    downloader = ByBitImpliedVolatilityDownloader()

    # Test current data for BTC
    print("\n📊 Getting current BTC implied volatility...")
    current_iv = downloader.get_implied_volatility('BTC', 'USD', period=30)

    if current_iv.get("retCode") == 0 and current_iv.get("result"):
        if current_iv["result"]:
            latest = current_iv["result"][0]
            timestamp = datetime.fromtimestamp(int(latest["time"])/1000)
            volatility = float(latest["value"])

            print(f"✅ BTC 30-day IV: {volatility:.4f} ({volatility*100:.2f}%)")
            print(f"🕐 Timestamp: {timestamp}")

            # Volatility interpretation
            if volatility > 1.0:
                vol_level = "🔴 EXTREMELY HIGH (>100%)"
            elif volatility > 0.5:
                vol_level = "🟠 HIGH (50-100%)"
            elif volatility > 0.3:
                vol_level = "🟡 MODERATE (30-50%)"
            else:
                vol_level = "🟢 LOW (<30%)"
            print(f"📊 Volatility Level: {vol_level}")
        else:
            print("⚠️ No current IV data available")

        # Test different periods
        print(f"\n📈 Testing different periods...")
        for period in [7, 14, 30]:
            period_iv = downloader.get_implied_volatility('BTC', 'USD', period=period)
            if period_iv.get("retCode") == 0 and period_iv.get("result"):
                data_points = len(period_iv["result"])
                print(f"📅 {period:2d}-day period: {data_points:3d} data points")
            time.sleep(1)

    return current_iv.get("retCode") == 0

def test_funding_rate():
    """Test Funding Rate downloader with trend analysis."""
    print("\n" + "="*60)
    print("💰 TESTING FUNDING RATE")
    print("="*60)

    downloader = ByBitFundingRateDownloader()

    # Test current data
    print("\n📊 Getting current BTCUSDT funding rate...")
    current_rate = downloader.get_funding_rate('BTCUSDT', 'linear', limit=10)

    if current_rate.get("retCode") == 0:
        latest = current_rate["result"]["list"][0]
        timestamp = datetime.fromtimestamp(int(latest["fundingRateTimestamp"])/1000)
        funding_rate = float(latest["fundingRate"])

        print(f"✅ Latest Funding Rate: {funding_rate:.6f} ({funding_rate*100:.4f}%)")
        print(f"🕐 Timestamp: {timestamp}")

        # Rate interpretation
        if funding_rate > 0.001:  # >0.1%
            rate_level = "🔴 HIGH POSITIVE (Longs pay shorts)"
        elif funding_rate > 0:
            rate_level = "🟡 POSITIVE (Longs pay shorts)"
        elif funding_rate < -0.001:  # <-0.1%
            rate_level = "🔵 HIGH NEGATIVE (Shorts pay longs)"
        elif funding_rate < 0:
            rate_level = "🟡 NEGATIVE (Shorts pay longs)"
        else:
            rate_level = "🟢 NEUTRAL"
        print(f"📊 Rate Level: {rate_level}")

        # Test historical range and analyze trends
        print(f"\n📈 Testing historical data availability...")
        for days in [7, 30, 90, 180]:
            historical_data = downloader.get_historical_funding_rate(
                symbol='BTCUSDT',
                category='linear',
                days_back=days
            )
            print(f"📅 {days:3d} days back: {len(historical_data):3d} data points")

            # Analyze recent data for trends
            if days == 30 and len(historical_data) > 10:
                trend_analysis = downloader.analyze_funding_trends(historical_data)
                if trend_analysis:
                    print(f"📊 30-day trend: {trend_analysis['trend_direction']}")
                    print(f"💹 Recent avg: {trend_analysis['recent_average']:.6f}")
                    print(f"📈 Max positive streak: {trend_analysis['max_consecutive_positive']}")
                    print(f"📉 Max negative streak: {trend_analysis['max_consecutive_negative']}")

            time.sleep(1)

    return current_rate.get("retCode") == 0

def run_comprehensive_test():
    """Run comprehensive test of all metrics and generate summary report."""
    print("🚀 BYBIT COMPREHENSIVE METRICS TEST")
    print("="*80)
    print(f"🕐 Test started at: {datetime.now()}")

    results = {
        "open_interest": False,
        "long_short_ratio": False,
        "implied_volatility": False,
        "funding_rate": False
    }

    # Run all tests
    try:
        results["open_interest"] = test_open_interest()
        time.sleep(2)

        results["long_short_ratio"] = test_long_short_ratio()
        time.sleep(2)

        results["implied_volatility"] = test_implied_volatility()
        time.sleep(2)

        results["funding_rate"] = test_funding_rate()

    except Exception as e:
        print(f"❌ Test error: {e}")

    # Generate summary report
    print("\n" + "="*80)
    print("📋 COMPREHENSIVE TEST SUMMARY")
    print("="*80)

    success_count = sum(results.values())
    total_tests = len(results)

    for metric, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{metric.replace('_', ' ').title():20} : {status}")

    print(f"\n🎯 Overall Success Rate: {success_count}/{total_tests} ({success_count/total_tests*100:.1f}%)")

    if success_count == total_tests:
        print("🎉 ALL METRICS WORKING PERFECTLY!")
        print("📊 Ready for professional trading analysis!")
    elif success_count >= total_tests * 0.75:
        print("✅ Most metrics working - Good for analysis!")
    else:
        print("⚠️ Some metrics need attention")

    print(f"\n🕐 Test completed at: {datetime.now()}")

    # Save results to file
    test_results = {
        "test_timestamp": datetime.now().isoformat(),
        "results": results,
        "success_rate": success_count / total_tests,
        "total_metrics_tested": total_tests,
        "successful_metrics": success_count
    }

    with open('comprehensive_test_results.json', 'w') as f:
        json.dump(test_results, f, indent=2)

    print(f"💾 Test results saved to: comprehensive_test_results.json")

    return results

if __name__ == "__main__":
    run_comprehensive_test()