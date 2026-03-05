#!/bin/bash
# Bybit Unified CLI - Quick Start Examples
# Execute these commands to test the CLI downloader

echo "🚀 Bybit Unified CLI - Quick Start Examples"
echo "============================================="

# Show directory structure first
echo ""
echo "📁 1. Show directory structure:"
echo "python bybit_unified_cli.py --show-structure"
python bybit_unified_cli.py --show-structure

echo ""
echo "Press Enter to continue with funding rate download..."
read

# Quick funding rate test (7 days)
echo ""
echo "💰 2. Download BTCUSDT funding rates (7 days):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types funding --days-back 7"
python bybit_unified_cli.py --symbols BTCUSDT --data-types funding --days-back 7

echo ""
echo "Press Enter to continue with historical data download..."
read

# Small historical data test
echo ""
echo "📈 3. Download BTCUSDT trade data (contract, 3 days from earliest available):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-03"
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-03

echo ""
echo "Press Enter to continue with historical klines download..."
read

# Kline data test
echo ""
echo "📈 4. Download BTCUSDT klines (1h, 5 days):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types klines --market linear --interval 1h --start-date 2024-01-01 --end-date 2024-01-05"
python bybit_unified_cli.py --symbols BTCUSDT --data-types klines --market linear --interval 1h --start-date 2024-01-01 --end-date 2024-01-05

echo ""
echo "Press Enter to test resume capability..."
read

# Test resume capability (should skip already downloaded files)
echo ""
echo "🔄 4. Test resume capability (should skip existing files):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-03"
python bybit_unified_cli.py --symbols BTCUSDT --data-types trade --market contract --start-date 2020-05-01 --end-date 2020-05-03

echo ""
echo "Press Enter to continue with open interest download..."
read

# Open interest test
echo ""
echo "📊 5. Download BTCUSDT open interest (30 days):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types openinterest --days-back 30"
python bybit_unified_cli.py --symbols BTCUSDT --data-types openinterest --days-back 30

echo ""
echo "Press Enter to continue with mixed download test..."
read

# Mixed download test
echo ""
echo "🎯 6. Download mixed data types (trade + funding + open interest):"
echo "python bybit_unified_cli.py --symbols BTCUSDT --data-types \"trade,funding,openinterest\" --market contract --start-date 2020-05-04 --end-date 2020-05-05 --days-back 7"
python bybit_unified_cli.py --symbols BTCUSDT --data-types "trade,funding,openinterest" --market contract --start-date 2020-05-04 --end-date 2020-05-05 --days-back 7

echo ""
echo "📁 Check downloaded data:"
echo "ls -la data/historical/trade/contract/BTCUSDT/"
ls -la data/historical/trade/contract/BTCUSDT/

echo ""
echo "ls -la data/market_metrics/funding_rates/"
ls -la data/market_metrics/funding_rates/

echo ""
echo "ls -la data/market_metrics/open_interest/"
ls -la data/market_metrics/open_interest/

echo ""
echo "📋 Check latest report:"
LATEST_REPORT=$(ls -t data/reports/ | head -1)
echo "cat data/reports/$LATEST_REPORT"
cat "data/reports/$LATEST_REPORT" | head -20

echo ""
echo "✅ Quick start examples completed!"
echo "🎉 Your Bybit CLI downloader is ready for production use!"

# Summary of what was downloaded
echo ""
echo "📊 SUMMARY OF DOWNLOADED DATA:"
echo "==============================="
echo "Historical Trade Data: $(ls -1 data/historical/trade/contract/BTCUSDT/ 2>/dev/null | wc -l) files"
echo "Funding Rate Files: $(ls -1 data/market_metrics/funding_rates/ 2>/dev/null | wc -l) files"
echo "Open Interest Files: $(ls -1 data/market_metrics/open_interest/ 2>/dev/null | wc -l) files"
echo "Log Files: $(ls -1 data/logs/ 2>/dev/null | wc -l) files"
echo "Report Files: $(ls -1 data/reports/ 2>/dev/null | wc -l) files"

# Show total disk usage
echo ""
echo "💾 DISK USAGE:"
du -sh data/
du -sh data/*/ 2>/dev/null | sort -hr