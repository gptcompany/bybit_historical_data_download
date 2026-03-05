"""
Test suite for ByBitUnifiedDownloader class.

This test file demonstrates the expected behavior of the unified downloader
that consolidates all 4 separate downloader classes.
"""

import pytest
from unittest.mock import Mock, patch
from bybit_data_downloader.live.ByBitUnifiedDownloader import ByBitUnifiedDownloader


class TestByBitUnifiedDownloaderInit:
    """Test initialization and configuration."""

    def test_open_interest_initialization(self):
        """Test that open_interest data type can be initialized."""
        downloader = ByBitUnifiedDownloader('open_interest')
        assert downloader.data_type == 'open_interest'

    def test_invalid_data_type_raises_error(self):
        """Test that invalid data type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ByBitUnifiedDownloader('invalid_type')
        assert "Unsupported data_type: invalid_type" in str(exc_info.value)

    def test_all_supported_types_can_be_initialized(self):
        """Test that all supported data types can be initialized."""
        valid_types = ['open_interest', 'long_short_ratio', 'implied_volatility', 'funding_rate']

        for data_type in valid_types:
            downloader = ByBitUnifiedDownloader(data_type)
            assert downloader.data_type == data_type

    def test_endpoint_configuration_exists_for_open_interest(self):
        """Test that endpoint configuration is available for open_interest."""
        downloader = ByBitUnifiedDownloader('open_interest')

        assert hasattr(downloader, 'endpoint_config')
        config = downloader.endpoint_config
        assert config['url'] == "https://api.bybit.com/v5/market/open-interest"
        assert config['time_param'] == "intervalTime"


class TestByBitUnifiedDownloaderGetData:
    """Test the unified get_data method."""

    def test_get_data_method_exists(self):
        """Test that get_data method exists and can be called."""
        downloader = ByBitUnifiedDownloader('open_interest')

        assert hasattr(downloader, 'get_data')
        assert callable(getattr(downloader, 'get_data'))

    @patch('httpx.Client.get')
    def test_get_data_accepts_symbol_parameter(self, mock_get):
        """Test that get_data method accepts symbol parameter."""
        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"retCode": 0, "retMsg": "OK", "result": {"list": []}}
        mock_get.return_value = mock_response

        downloader = ByBitUnifiedDownloader('open_interest')

        # Should be able to call with symbol parameter without errors
        # Provide the required interval_time parameter
        result = downloader.get_data(symbol='BTCUSDT', interval_time='1d')

        # Should return a dictionary (either successful response or error)
        assert isinstance(result, dict)
        assert 'retCode' in result  # Standard Bybit API response structure
        assert mock_get.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])