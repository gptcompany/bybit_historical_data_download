"""
Test backward compatibility after refactoring to unified downloader.

This test ensures that existing classes still work as expected after
being converted to thin wrappers around the unified downloader.
"""

import pytest
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

    def test_can_call_get_open_interest_with_real_api(self):
        """Test that get_open_interest method works with real API call."""
        downloader = ByBitOpenInterestDownloader()

        # Make a real API call with proper parameters
        result = downloader.get_open_interest(
            symbol='BTCUSDT',
            category='linear',
            interval_time='1d',
            limit=5
        )

        # Should return a dictionary with Bybit API response structure
        assert isinstance(result, dict)
        assert 'retCode' in result
        # Should have either successful data or clear error message
        assert result.get('retCode') is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])