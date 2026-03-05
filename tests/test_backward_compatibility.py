"""
Test backward compatibility after refactoring to unified downloader.

This test ensures that existing classes still work as expected after
being converted to thin wrappers around the unified downloader.
"""

import pytest
from unittest.mock import Mock, patch
from bybit_data_downloader.live.ByBitOpenInterestDownloader import ByBitOpenInterestDownloader


class TestBackwardCompatibilityOpenInterest:
    """Test backward compatibility for ByBitOpenInterestDownloader."""

    def test_can_initialize_original_class(self):
        """Test that the original class can still be initialized."""
        downloader = ByBitOpenInterestDownloader()
        assert downloader is not None

    def test_has_get_open_interest_method(self):
        """Test that the original get_open_interest method still exists."""
        downloader = ByBitOpenInterestDownloader()
        assert hasattr(downloader, 'get_open_interest')
        assert callable(getattr(downloader, 'get_open_interest'))

    @patch('httpx.Client.get')
    def test_can_call_get_open_interest_with_real_api(self, mock_get):
        """Test that get_open_interest method works with mocked API call."""
        # Mock API response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"retCode": 0, "retMsg": "OK", "result": {"list": []}}
        mock_get.return_value = mock_response

        downloader = ByBitOpenInterestDownloader()

        # Make a call with proper parameters
        result = downloader.get_open_interest(
            symbol='BTCUSDT',
            category='linear',
            interval_time='1d',
            limit=5
        )

        # Should return a dictionary with Bybit API response structure
        assert isinstance(result, dict)
        assert 'retCode' in result
        assert mock_get.called


if __name__ == "__main__":
    pytest.main([__file__, "-v"])