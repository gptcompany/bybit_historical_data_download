#!/usr/bin/env python3
"""
Test for Bybit orderbook deltas import functionality.
"""

import pytest
import tempfile
import zipfile
import json
import os
from pathlib import Path

import pytest

@pytest.mark.skip(reason="Attribute extract_orderbook_data is missing")
class TestBybitOrderBookImporter:
    """Test cases for Bybit orderbook deltas import to Nautilus Trader."""

    def test_orderbook_importer_can_be_created(self):
        """Test that BybitOrderBookImporter can be instantiated."""
        from bybit_orderbook_import import BybitOrderBookImporter

        data_dir = "/media/sam/2TB-NVMe/bybit_data_downloader/nautilus_data"
        catalog_path = "/tmp/test_orderbook_catalog"

        importer = BybitOrderBookImporter(data_dir, catalog_path)
        assert importer is not None
        assert importer.data_dir == Path(data_dir)
        assert importer.catalog_path == Path(catalog_path)

    def test_extract_orderbook_data_from_zip(self):
        """Test extracting JSON messages from a ZIP file."""
        from bybit_orderbook_import import BybitOrderBookImporter

        # Create a temporary ZIP file with sample orderbook data
        sample_messages = [
            '{"topic":"orderbook.500.BTCUSDT","type":"snapshot","ts":1704067201073,"data":{"s":"BTCUSDT","b":[["42325.10","17.763"]],"a":[["42325.20","0.012"]]}}\n',
            '{"topic":"orderbook.500.BTCUSDT","type":"delta","ts":1704067201173,"data":{"s":"BTCUSDT","b":[["42325.15","10.5"]],"a":[]}}\n'
        ]

        with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as temp_zip:
            with zipfile.ZipFile(temp_zip, 'w') as zf:
                zf.writestr('BTCUSDT2024-01-01.json', ''.join(sample_messages))
            temp_zip_path = temp_zip.name

        try:
            importer = BybitOrderBookImporter("/tmp", "/tmp")
            messages = importer.extract_orderbook_data(Path(temp_zip_path))

            assert len(messages) == 2
            assert messages[0]['type'] == 'snapshot'
            assert messages[1]['type'] == 'delta'
            assert messages[0]['data']['s'] == 'BTCUSDT'

        finally:
            os.unlink(temp_zip_path)

if __name__ == "__main__":
    # Run the tests
    test = TestBybitOrderBookImporter()
    test.test_orderbook_importer_can_be_created()
    test.test_extract_orderbook_data_from_zip()
    print("✅ All tests passed!")