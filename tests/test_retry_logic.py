"""
Test retry logic behavior for ByBit downloaders
"""
import pytest
import time
from unittest.mock import Mock, patch
import httpx
from bybit_data_downloader.live.ByBitOpenInterestDownloader import ByBitOpenInterestDownloader


def test_open_interest_retry_on_network_failure():
    """Test that OpenInterest downloader retries on network failures with exponential backoff"""
    downloader = ByBitOpenInterestDownloader()

    # Mock httpx.Client to simulate network failures
    with patch('httpx.Client') as mock_client:
        mock_context = Mock()
        mock_client.return_value.__enter__.return_value = mock_context

        # Simulate 2 failures then success
        mock_context.get.side_effect = [
            httpx.RequestError("Network timeout"),
            httpx.RequestError("Connection refused"),
            Mock(status_code=200, json=lambda: {"retCode": 0, "result": {"list": []}})
        ]

        start_time = time.time()
        result = downloader.get_open_interest("BTCUSDT", "linear")
        end_time = time.time()

        # Should have made 3 calls (2 failures + 1 success)
        assert mock_context.get.call_count == 3

        # Should have succeeded after retries
        assert result["retCode"] == 0

        # Should have taken at least 3 seconds due to exponential backoff (1s + 2s)
        assert (end_time - start_time) >= 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])