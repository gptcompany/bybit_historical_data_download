#!/usr/bin/env python3
"""
Test script to reproduce the open interest bug.

Bug: 'list' object has no attribute 'get'
Location: bybit_unified_cli.py line 430
Issue: historical_data is a list, not a dict with 'result' and 'list' keys
"""

import sys
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
import json

# Add the src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import the CLI class
from bybit_unified_cli import BybitUnifiedCLI


class TestOpenInterestBugReproduction(unittest.TestCase):
    """Test class to reproduce the open interest bug."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.cli = BybitUnifiedCLI()
        # Override directories to use test directory
        for key in self.cli.DIRECTORIES:
            self.cli.DIRECTORIES[key] = os.path.join(self.test_dir, key)
            os.makedirs(self.cli.DIRECTORIES[key], exist_ok=True)

    def test_open_interest_bug_reproduction(self):
        """
        Test that reproduces the bug: 'list' object has no attribute 'get'

        This test simulates the exact scenario where get_historical_open_interest()
        returns a list (as it should), but the CLI code tries to treat it as a
        dict with 'result' and 'list' keys.
        """
        # Mock historical data as returned by ByBitUnifiedDownloader.get_historical_data()
        # This is a LIST of data points, not a dict with 'result' structure
        mock_historical_data = [
            {'openInterest': '66485.49000000', 'timestamp': '1758758400000'},
            {'openInterest': '67132.06800000', 'timestamp': '1758672000000'},
            {'openInterest': '66382.56400000', 'timestamp': '1758585600000'}
        ]

        # Mock the ByBitOpenInterestDownloader
        with patch('bybit_unified_cli.ByBitOpenInterestDownloader') as mock_downloader_class:
            mock_downloader = Mock()
            mock_downloader_class.return_value = mock_downloader

            # Mock current OI response (API format)
            mock_current_oi = {
                'result': {
                    'list': [{'openInterest': '66485.49000000', 'timestamp': '1758758400000'}]
                }
            }
            mock_downloader.get_open_interest.return_value = mock_current_oi

            # Mock historical data response (LIST format as returned by get_historical_data)
            mock_downloader.get_historical_open_interest.return_value = mock_historical_data

            # This should now SUCCEED after the bug fix
            result = self.cli.download_open_interest('BTCUSDT', 7, 'test_key')

            # Verify the result structure
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['records'], 3)
            print(f"✅ Bug verified as FIXED: Result is {result['status']}")


if __name__ == '__main__':
    print("🧪 REPRODUCING OPEN INTEREST BUG")
    print("=" * 50)
    print("Bug: 'list' object has no attribute 'get'")
    print("Location: bybit_unified_cli.py line 430")
    print("Issue: historical_data is a list, not a dict")
    print("=" * 50)

    # Run the test
    unittest.main(verbosity=2)