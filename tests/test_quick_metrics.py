"""
Quick test of all Bybit metrics to verify functionality and data availability.
"""

from bybit_data_downloader import (
    ByBitOpenInterestDownloader,
    ByBitLongShortRatioDownloader,
    ByBitImpliedVolatilityDownloader,
    ByBitFundingRateDownloader
)
import time
from datetime import datetime

def quick_test():
    print("🚀 QUICK BYBIT METRICS TEST")
    print("="*50)

    results = {}

    # Test 1: Open Interest
    print("\n📊 Testing Open Interest...")
    try:
        oi_downloader = ByBitOpenInterestDownloader()
        oi_data = oi_downloader.get_open_interest('BTCUSDT', 'linear', '1d', limit=3)
        results['open_interest'] = oi_data.get('retCode') == 0
        if results['open_interest']:
            latest = oi_data['result']['list'][0]
            print(f"✅ BTC OI: {latest['openInterest']}")
    except Exception as e:
        print(f"❌ OI Error: {e}")
        results['open_interest'] = False

    time.sleep(1)

    # Test 2: Long-Short Ratio
    print("\n⚖️ Testing Long-Short Ratio...")
    try:
        lsr_downloader = ByBitLongShortRatioDownloader()
        lsr_data = lsr_downloader.get_long_short_ratio('BTCUSDT', 'linear', '1d', limit=3)
        results['long_short_ratio'] = lsr_data.get('retCode') == 0
        if results['long_short_ratio']:
            latest = lsr_data['result']['list'][0]
            print(f"✅ Buy: {float(latest['buyRatio']):.3f}, Sell: {float(latest['sellRatio']):.3f}")
    except Exception as e:
        print(f"❌ LSR Error: {e}")
        results['long_short_ratio'] = False

    time.sleep(1)

    # Test 3: Implied Volatility
    print("\n📈 Testing Implied Volatility...")
    try:
        iv_downloader = ByBitImpliedVolatilityDownloader()
        iv_data = iv_downloader.get_implied_volatility('BTC', 'USD', period=7)
        results['implied_volatility'] = iv_data.get('retCode') == 0 and iv_data.get('result')
        if results['implied_volatility']:
            if iv_data['result']:
                latest = iv_data['result'][0]
                print(f"✅ BTC 7d IV: {float(latest['value']):.4f}")
            else:
                print("⚠️ No IV data available")
                results['implied_volatility'] = False
    except Exception as e:
        print(f"❌ IV Error: {e}")
        results['implied_volatility'] = False

    time.sleep(1)

    # Test 4: Funding Rate
    print("\n💰 Testing Funding Rate...")
    try:
        fr_downloader = ByBitFundingRateDownloader()
        fr_data = fr_downloader.get_funding_rate('BTCUSDT', 'linear', limit=3)
        results['funding_rate'] = fr_data.get('retCode') == 0
        if results['funding_rate']:
            latest = fr_data['result']['list'][0]
            print(f"✅ Funding Rate: {float(latest['fundingRate']):.6f}")
    except Exception as e:
        print(f"❌ FR Error: {e}")
        results['funding_rate'] = False

    # Summary
    print("\n" + "="*50)
    print("📋 QUICK TEST RESULTS:")
    success_count = sum(results.values())
    for metric, success in results.items():
        status = "✅" if success else "❌"
        print(f"{status} {metric.replace('_', ' ').title()}")

    print(f"\n🎯 Success Rate: {success_count}/4 ({success_count/4*100:.0f}%)")

    if success_count == 4:
        print("🎉 ALL METRICS WORKING!")
    elif success_count >= 3:
        print("✅ Most metrics working!")
    else:
        print("⚠️ Some issues detected")

    return results

if __name__ == "__main__":
    quick_test()