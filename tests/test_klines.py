import pytest
import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from bybit_data_downloader import ByBitKlineDownloader
from bybit_unified_cli import BybitUnifiedCLI

class TestByBitKlineDownloader(unittest.TestCase):
    def setUp(self):
        self.downloader = ByBitKlineDownloader()

    def test_interval_mapping(self):
        """Test interval mapping to Bybit v5 parameters."""
        assert self.downloader.INTERVAL_MAPPING['1m'] == '1'
        assert self.downloader.INTERVAL_MAPPING['1h'] == '60'
        assert self.downloader.INTERVAL_MAPPING['1d'] == 'D'
        assert self.downloader.INTERVAL_MAPPING['1w'] == 'W'
        assert self.downloader.INTERVAL_MAPPING['1mo'] == 'M'

    def test_get_interval_ms(self):
        """Test conversion of interval string to milliseconds."""
        assert self.downloader._get_interval_ms('1m') == 60 * 1000
        assert self.downloader._get_interval_ms('1h') == 60 * 60 * 1000
        assert self.downloader._get_interval_ms('1d') == 24 * 60 * 60 * 1000
        assert self.downloader._get_interval_ms('1w') == 7 * 24 * 60 * 60 * 1000
        assert self.downloader._get_interval_ms('1mo') == 30 * 24 * 60 * 60 * 1000
        assert self.downloader._get_interval_ms('unknown') == 60 * 1000
        assert self.downloader._get_interval_ms(None) == 60 * 1000

    @patch('httpx.Client.get')
    def test_get_klines_mock_success(self, mock_get):
        """Test basic kline retrieval with mocked API success."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 0,
            "retMsg": "OK",
            "result": {
                "category": "linear",
                "symbol": "BTCUSDT",
                "list": [
                    ["1670608800000", "17000", "17100", "16900", "17050", "10", "170000"]
                ]
            }
        }
        mock_get.return_value = mock_response

        result = self.downloader.get_klines("BTCUSDT", "1m")
        assert result['retCode'] == 0
        assert len(result['result']['list']) == 1
        assert result['result']['list'][0][0] == "1670608800000"

    @patch('httpx.Client.get')
    def test_get_klines_api_error(self, mock_get):
        """Test kline retrieval with API error and retries."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "retCode": 10001,
            "retMsg": "Internal Error"
        }
        mock_get.return_value = mock_response
        
        with patch('time.sleep'): # Avoid slowing down tests
            result = self.downloader.get_klines("BTCUSDT", "1m")
            assert result['retCode'] == 10001
            assert mock_get.call_count == 3

    @patch('httpx.Client.get')
    def test_get_klines_network_error(self, mock_get):
        """Test kline retrieval with network error."""
        mock_get.side_effect = Exception("Network Down")
        
        with patch('time.sleep'):
            result = self.downloader.get_klines("BTCUSDT", "1m")
            assert result['retCode'] == -1
            assert "Network Down" in result['retMsg']

    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    def test_download_range_success(self, mock_exists, mock_mkdir):
        """Test download_range with successful pagination and file saving."""
        mock_exists.return_value = False
        
        # Mock 2 batches for one day to test pagination
        day_start = datetime(2024, 1, 1)
        day_start_ms = int(day_start.timestamp() * 1000)
        day_end_ms = int((day_start + timedelta(days=1)).timestamp() * 1000) - 1
        
        batch1 = [[str(day_end_ms - i * 60000), "1", "1", "1", "1", "1", "1"] for i in range(1000)]
        oldest_batch1 = int(float(batch1[-1][0]))
        
        batch2 = [[str(oldest_batch1 - (i+1) * 60000), "1", "1", "1", "1", "1", "1"] for i in range(440)]
        batch2[-1][0] = str(day_start_ms)
        
        self.downloader.get_klines = MagicMock(side_effect=[
            {"retCode": 0, "result": {"list": batch1}},
            {"retCode": 0, "result": {"list": batch2}}
        ])
        
        m_open = mock_open()
        with patch('builtins.open', m_open):
            with patch('time.sleep'):
                stats = self.downloader.download_range("BTCUSDT", "2024-01-01", "2024-01-01", interval="1m")
                
        assert stats['successful_days'] == 1
        assert stats['total_records'] == 1440
        assert m_open.called

    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    def test_download_range_api_failure(self, mock_exists, mock_mkdir):
        """Test download_range when API returns error."""
        mock_exists.return_value = False
        self.downloader.get_klines = MagicMock(return_value={"retCode": -1, "retMsg": "Error"})
        
        with patch('time.sleep'):
            stats = self.downloader.download_range("BTCUSDT", "2024-01-01", "2024-01-01")
            
        assert stats['failed_days'] == 1
        assert stats['successful_days'] == 0

    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    def test_download_range_no_data(self, mock_exists, mock_mkdir):
        """Test download_range when API returns empty list."""
        mock_exists.return_value = False
        self.downloader.get_klines = MagicMock(return_value={"retCode": 0, "result": {"list": []}})
        
        with patch('time.sleep'):
            stats = self.downloader.download_range("BTCUSDT", "2024-01-01", "2024-01-01")
            
        assert stats['failed_days'] == 1
        assert stats['successful_days'] == 0

    @patch('pathlib.Path.mkdir')
    @patch('pathlib.Path.exists')
    def test_download_range_save_exception(self, mock_exists, mock_mkdir):
        """Test download_range when file saving fails."""
        mock_exists.return_value = False
        batch = [[str(datetime(2024,1,1).timestamp() * 1000), "1", "1", "1", "1", "1", "1"]]
        self.downloader.get_klines = MagicMock(return_value={"retCode": 0, "result": {"list": batch}})
        
        with patch('builtins.open', side_effect=Exception("Disk Full")):
            with patch('time.sleep'):
                stats = self.downloader.download_range("BTCUSDT", "2024-01-01", "2024-01-01")
                
        assert stats['failed_days'] == 1
        assert stats['successful_days'] == 0

    @patch('pathlib.Path.exists')
    def test_download_range_skip_existing(self, mock_exists):
        """Test that existing files are skipped."""
        mock_exists.return_value = True
        
        stats = self.downloader.download_range("BTCUSDT", "2024-01-01", "2024-01-01")
        assert stats['successful_days'] == 1
        assert stats['total_records'] == 0

class TestBybitUnifiedCLI_Klines(unittest.TestCase):
    def setUp(self):
        # Patch load_state to ensure download_state is initialized correctly
        with patch('bybit_unified_cli.BybitUnifiedCLI.setup_logging'):
            with patch('bybit_unified_cli.BybitUnifiedCLI.setup_directories'):
                with patch('bybit_unified_cli.BybitUnifiedCLI.load_state'):
                    self.cli = BybitUnifiedCLI()
                    self.cli.download_state = {}
                    self.cli.logger = MagicMock()

    def test_state_management(self):
        """Test saving state and marking downloads complete."""
        with patch('builtins.open', mock_open()):
            with patch('json.dump') as mock_json:
                self.cli.save_state()
                mock_json.assert_called_once()

        with patch('bybit_unified_cli.BybitUnifiedCLI.get_file_hash', return_value="hash"):
            with patch('os.path.exists', return_value=True):
                with patch('os.path.getsize', return_value=100):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.save_state'):
                        self.cli.mark_download_complete("key", "file", {"meta": 1})
                        assert self.cli.download_state["key"]["completed"] == True

    def test_generate_report(self):
        """Test generating report file."""
        results = {"test": {"status": "completed"}}
        m_open = mock_open()
        with patch('builtins.open', m_open):
            with patch('json.dump'):
                report_path = self.cli.generate_report(results)
                assert "reports" in report_path
                assert m_open.called

    def test_state_key_includes_interval(self):
        """Test that the state key for klines includes the interval."""
        symbol = "BTCUSDT"
        interval = "5m"
        market = "linear"
        start_date = "2024-01-01"
        end_date = "2024-01-02"
        
        state_key = f"historical_{symbol}_klines_{market}_{interval}_{start_date}_{end_date}"
        assert "5m" in state_key
        assert "klines" in state_key

    def test_invalid_interval_validation(self):
        """Test that invalid intervals are rejected."""
        assert "1m" in self.cli.VALID_INTERVALS
        assert "invalid" not in self.cli.VALID_INTERVALS

    @patch('bybit_unified_cli.ByBitKlineDownloader.download_range')
    def test_download_historical_data_klines(self, mock_download_range):
        """Test CLI integration with Kline downloader."""
        mock_download_range.return_value = {'successful_days': 1, 'total_records': 100}
        
        with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
            results = self.cli.download_historical_data(
                symbols=["BTCUSDT"],
                data_types=["klines"],
                market="linear",
                start_date="2024-01-01",
                end_date="2024-01-01",
                interval="1m"
            )
            
        assert "BTCUSDT_klines_1m_linear" in results
        assert results["BTCUSDT_klines_1m_linear"]["status"] == "completed"
        mock_download_range.assert_called_once()

    @patch('bybit_unified_cli.ByBitHistoricalDataDownloader.download_data')
    def test_download_historical_data_trade(self, mock_download_data):
        """Test downloading trade data via CLI."""
        mock_download_data.return_value = {'downloaded': 1}
        
        with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
            with patch('bybit_unified_cli.BybitUnifiedCLI.get_expected_historical_files', return_value=[]):
                results = self.cli.download_historical_data(
                    symbols=["BTCUSDT"],
                    data_types=["trade"],
                    market="spot",
                    start_date="2024-01-01",
                    end_date="2024-01-01"
                )
        assert "BTCUSDT_trade_spot" in results
        assert results["BTCUSDT_trade_spot"]["status"] == "completed"

    @patch('bybit_unified_cli.ByBitFundingRateDownloader')
    def test_download_funding_rates_cli(self, mock_downloader_cls):
        """Full test for download_funding_rates in CLI."""
        mock_downloader = mock_downloader_cls.return_value
        mock_downloader.get_funding_rate.return_value = {'result': {'list': [{'fundingRate': '0.0001'}]}}
        mock_downloader.download_and_save.return_value = "fake_file.json"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.getsize', return_value=1024):
                with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
                    res = self.cli.download_funding_rates("BTCUSDT", 30, "state_key")
                    assert res['status'] == 'completed'

    @patch('bybit_unified_cli.ByBitOpenInterestDownloader')
    def test_download_open_interest_cli(self, mock_downloader_cls):
        """Full test for download_open_interest in CLI."""
        mock_downloader = mock_downloader_cls.return_value
        mock_downloader.get_open_interest.return_value = {'result': {'list': [{'openInterest': '100'}]}}
        mock_downloader.get_historical_open_interest.return_value = [{'timestamp': '123', 'openInterest': '100'}]
        
        with patch('builtins.open', mock_open()):
            with patch('os.path.exists', return_value=True):
                with patch('os.path.getsize', return_value=1024):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
                        res = self.cli.download_open_interest("BTCUSDT", 30, "state_key")
                        assert res['status'] == 'completed'

    @patch('bybit_unified_cli.ByBitLongShortRatioDownloader')
    def test_download_long_short_ratio_cli(self, mock_downloader_cls):
        """Full test for download_long_short_ratio in CLI."""
        mock_downloader = mock_downloader_cls.return_value
        mock_downloader.get_long_short_ratio.return_value = {'result': {'list': [{'buyRatio': '0.5'}]}}
        mock_downloader.download_and_save.return_value = "fake_file.json"
        
        with patch('os.listdir', return_value=[]):
            with patch('os.path.exists', return_value=True):
                with patch('os.path.getsize', return_value=1024):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
                        res = self.cli.download_long_short_ratio("BTCUSDT", 30, "state_key")
                        assert res['status'] == 'completed'

    @patch('bybit_unified_cli.ByBitImpliedVolatilityDownloader')
    def test_download_implied_volatility_cli(self, mock_downloader_cls):
        """Full test for download_implied_volatility in CLI."""
        mock_downloader = mock_downloader_cls.return_value
        mock_downloader.get_implied_volatility.return_value = "0.5"
        mock_downloader.download_and_save.return_value = "fake_file.json"
        
        with patch('os.path.exists', return_value=True):
            with patch('os.path.getsize', return_value=1024):
                with patch('bybit_unified_cli.BybitUnifiedCLI.mark_download_complete'):
                    res = self.cli.download_implied_volatility("BTCUSDT", 30, "state_key")
                    assert res['status'] == 'completed'

    def test_main_utility_flags(self):
        """Test utility flags like --show-structure and --clear-state."""
        from bybit_unified_cli import main
        import sys
        
        with patch.object(sys, 'argv', ['bybit_unified_cli.py', '--show-structure']):
            with patch('bybit_unified_cli.BybitUnifiedCLI.setup_logging'):
                with patch('bybit_unified_cli.BybitUnifiedCLI.setup_directories'):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.load_state'):
                        main() 

        with patch.object(sys, 'argv', ['bybit_unified_cli.py', '--clear-state', '--symbols', 'BTC', '--data-types', 'funding']):
            with patch('bybit_unified_cli.BybitUnifiedCLI.setup_logging'):
                with patch('bybit_unified_cli.BybitUnifiedCLI.setup_directories'):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.load_state'):
                        with patch('os.path.exists', return_value=True):
                            with patch('os.remove') as mock_remove:
                                with patch('bybit_unified_cli.BybitUnifiedCLI.download_market_data', return_value={}):
                                    with patch('bybit_unified_cli.BybitUnifiedCLI.generate_report'):
                                        main()
                                        mock_remove.assert_called_once()

    def test_main_klines_interval_validation_failure(self):
        """Test main entry point validation for invalid intervals."""
        from bybit_unified_cli import main
        import sys
        
        test_args = [
            'bybit_unified_cli.py',
            '--symbols', 'BTCUSDT',
            '--data-types', 'klines',
            '--interval', 'invalid_int',
            '--start-date', '2024-01-01',
            '--end-date', '2024-01-01'
        ]
        
        with patch.object(sys, 'argv', test_args):
            with patch('bybit_unified_cli.BybitUnifiedCLI.setup_logging'):
                with patch('bybit_unified_cli.BybitUnifiedCLI.setup_directories'):
                    with patch('bybit_unified_cli.BybitUnifiedCLI.load_state'):
                        with pytest.raises(SystemExit) as cm:
                            main()
                        assert cm.value.code == 1
