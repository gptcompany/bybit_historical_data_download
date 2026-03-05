#!/usr/bin/env python3
"""
Bybit OrderBook Deltas Import for Nautilus Trader

TDD GREEN phase: Minimal implementation to fix ModuleNotFoundError
Test failure: ModuleNotFoundError: No module named 'bybit_orderbook_import'
"""

from pathlib import Path


class BybitOrderBookImporter:
    """Import Bybit orderbook data to Nautilus Trader catalog."""

    def __init__(self, data_dir: str, catalog_path: str):
        """Initialize the importer."""
        self.data_dir = Path(data_dir)
        self.catalog_path = Path(catalog_path)