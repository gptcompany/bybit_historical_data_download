"""
Test input validation behavior for ByBit downloaders
"""
import pytest
from bybit_data_downloader.live.ByBitOpenInterestDownloader import ByBitOpenInterestDownloader


def test_open_interest_validates_symbol():
    """Test that OpenInterest downloader validates symbol parameter"""
    downloader = ByBitOpenInterestDownloader()

    # Should raise ValueError for empty symbol
    with pytest.raises(ValueError, match="Symbol must be a non-empty string"):
        downloader.get_open_interest("", "linear")

    # Should raise ValueError for None symbol
    with pytest.raises(ValueError, match="Symbol must be a non-empty string"):
        downloader.get_open_interest(None, "linear")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])