#!/usr/bin/env python3
"""
Test to verify the fix for open interest bug.

This test expects the download_open_interest method to work correctly
with list data from get_historical_open_interest.
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


class TestOpenInterestFix(unittest.TestCase):
    """Test that open interest downloads work correctly after fix."""

    def setUp(self):
        """Set up test environment."""
        self.test_dir = tempfile.mkdtemp()
        self.cli = BybitUnifiedCLI()
        # Override directories to use test directory
        for key in self.cli.DIRECTORIES:
            self.cli.DIRECTORIES[key] = os.path.join(self.test_dir, key)
            os.makedirs(self.cli.DIRECTORIES[key], exist_ok=True)

    def test_open_interest_download_success(self):
        """
        Test that download_open_interest works correctly when get_historical_open_interest
        returns a list of data points (which is the correct behavior).

        This test should FAIL with current buggy code and PASS after fix.
        """
        # Mock historical data as returned by get_historical_open_interest()
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

            # This should work without errors after the fix
            try:
                result = self.cli.download_open_interest('BTCUSDT', 7, 'test_key')

                # Verify the download was successful
                self.assertIsNotNone(result)
                self.assertEqual(result['status'], 'completed')
                self.assertEqual(result['records'], 3)  # Should count the 3 records in the list

                print(f"✅ Open interest download worked successfully: {result['records']} records")

            except Exception as e:
                self.fail(f"Open interest download should not fail after fix, but got: {e}")


if __name__ == '__main__':
    print("🧪 TESTING OPEN INTEREST FIX")
    print("=" * 50)
    print("This test should FAIL with current buggy code")
    print("and PASS after implementing the fix")
    print("=" * 50)

    # Run the test
    unittest.main(verbosity=2)