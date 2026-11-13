"""The strict pydantic path must reproduce the jsonschema path's outcome and message."""
import json
import zipfile

import pytest

from bybit_data_downloader import backfill_execute as module

START = 1782691200000  # 2026-06-29T00:00:00Z
JOB = dict(day="2026-06-29", symbol="BTCUSDT", type="orderbook", source="archive")


def rows():
    return [json.dumps(dict(type="snapshot" if minute == 0 else "delta", ts=START + minute * 60000, cts=START,
                            data=dict(s="BTCUSDT", b=[["59556.50", "6.835"]], a=[["59556.60", "0"]], u=minute, seq=minute)))
            for minute in range(1440)]


def replace(index, old, new):
    def mutate(lines):
        assert old in lines[index]
        lines[index] = lines[index].replace(old, new, 1)
    return mutate


CASES = {
    "valid": lambda lines: None,
    "tail-within-limit": lambda lines: lines.append(lines[-1].replace(f'"ts": {START + 1439 * 60000}', f'"ts": {START + 86400000}')
                                                    .replace('"u": 1439', '"u": 1440')),
    "tail-over-limit": lambda lines: lines.append(lines[-1].replace(f'"ts": {START + 1439 * 60000}', f'"ts": {START + 86460001}')
                                                  .replace('"u": 1439', '"u": 1440')),
    "duplicate-id": lambda lines: lines.insert(2, lines[1]),
    "missing-snapshot": replace(0, '"snapshot"', '"delta"'),
    "missing-minute": lambda lines: lines.pop(7),
    "unordered": lambda lines: lines.insert(3, lines.pop(5)),
    "wrong-symbol": replace(4, '"s": "BTCUSDT"', '"s": "ETHUSDT"'),
    "extra-field": replace(4, '"cts"', '"extra": 1, "cts"'),
    "null-cts": replace(4, f'"cts": {START}', '"cts": null'),
    "bool-u": replace(4, '"u": 4', '"u": true'),
    "float-integer-u": replace(4, '"u": 4', '"u": 4.0'),
    "float-ts": replace(4, f'"ts": {START + 4 * 60000}', f'"ts": {START + 4 * 60000}.0'),
    "leading-zero": replace(4, '"u": 4', '"u": 04'),
    "triple-level": replace(4, '["59556.50", "6.835"]', '["59556.50", "6.835", "1"]'),
    "exponent-text": replace(4, '"6.835"', '"6e3"'),
    "newline-text": replace(4, '"6.835"', '"6.835\\n"'),
    "negative-price": replace(4, '"59556.50"', '"-59556.50"'),
    "zero-price": replace(4, '"59556.50"', '"0.00"'),
    "negative-zero-price": replace(4, '"59556.50"', '"-0"'),
    "negative-size": replace(4, '"6.835"', '"-0.010"'),
    "negative-zero-size": replace(4, '"6.835"', '"-0.000"'),
    "duplicate-key-last-valid": replace(4, '"type": "delta"', '"type": "bogus", "type": "delta"'),
    "duplicate-key-last-invalid": replace(4, '"type": "delta"', '"type": "delta", "type": "bogus"'),
    "invalid-json": replace(4, "}}", "}"),
    "blank-line": lambda lines: lines.insert(4, ""),
    "byte-order-mark": lambda lines: lines.__setitem__(0, "﻿" + lines[0]),
}


def outcome(path, monkeypatch, fast):
    with monkeypatch.context() as patch:
        calls = []
        original = module.strict_book_row
        patch.setattr(module, "strict_book_row", lambda line: calls.append(line) or (original(line) if fast else None))
        try:
            result = ("ok", module.scan(path, JOB, allow_orderbook_tail=True))
        except Exception as error:
            result = (type(error).__name__, str(error))
        assert calls
        return result


@pytest.mark.parametrize("case", CASES)
def test_strict_path_matches_schema_path(tmp_path, monkeypatch, case):
    lines = rows()
    CASES[case](lines)
    path = tmp_path / "day.zip"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        stream.writestr("2026-06-29_BTCUSDT_ob200.data", "\n".join(lines) + "\n")
    expected = outcome(path, monkeypatch, fast=False)
    assert outcome(path, monkeypatch, fast=True) == expected
    assert (expected[0] == "ok") == (case in {"valid", "tail-within-limit", "float-integer-u", "float-ts", "newline-text",
                                              "negative-zero-size", "duplicate-key-last-valid"})


def test_valid_rows_skip_the_schema_path(tmp_path, monkeypatch):
    path = tmp_path / "day.zip"
    with zipfile.ZipFile(path, "w") as stream:
        stream.writestr("day.data", "\n".join(rows()) + "\n")
    monkeypatch.setattr(module.json, "loads", lambda line: pytest.fail("schema path used for a valid row"))
    assert module.scan(path, JOB) == (1440, 0)
