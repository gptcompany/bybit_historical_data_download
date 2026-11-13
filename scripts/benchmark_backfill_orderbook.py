"""CI-only same-input comparison of orderbook validation against the deployed release (no network)."""
import cProfile
import io
import json
import pstats
import tempfile
import time
import zipfile
from pathlib import Path

from bybit_data_downloader import backfill_execute
from scripts.benchmark_backfill_ids import load_baseline

BASELINE = "7c6cda8273b6688a31d4872a0a8d3f584fd7f08f"
FIXTURE = Path(__file__).parents[1] / "tests/fixtures/btc-ob200-2026-06-29.jsonl"
# Issue #30 measure: 2026-06-29 BTCUSDT ob200 is 1.44 GB decompressed. Rows follow the
# declared ob200 push cadence of 100 ms, which the fixture's consecutive deltas also show.
DAY_BYTES, PUSH_MS = 1_440_000_000, 100
ROWS = 14_400  # 1/60 of a day, ten rows per UTC minute.
REQUIRED_SPEEDUP = 4  # Acceptance: at most 1/4 of the baseline time on one core.


def lines():
    first = json.loads(FIXTURE.read_text().splitlines()[0])
    pair = first["data"]["b"][0]
    empty = dict(first, data=dict(first["data"], b=[], a=[]))
    pair_bytes = len(json.dumps(pair, separators=(",", ":"))) + 1
    row_bytes = DAY_BYTES / (backfill_execute.DAY / PUSH_MS)
    levels = round((row_bytes - len(json.dumps(empty, separators=(",", ":")))) / pair_bytes / 2)
    start, _ = backfill_execute.bounds(dict(day="2026-06-29"))
    for index in range(ROWS):
        data = dict(first["data"], b=[pair] * levels, a=[pair] * levels, u=index, seq=index)
        row = dict(first, type="delta" if index else "snapshot", ts=start + index * 6000, data=data)
        yield json.dumps(row, separators=(",", ":")) + "\n"


def main():
    baseline = load_baseline(BASELINE)
    job = dict(day="2026-06-29", symbol="BTCUSDT", type="orderbook", source="archive")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "2026-06-29_BTCUSDT_ob200.data.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            with archive.open("2026-06-29_BTCUSDT_ob200.data", "w") as stream:
                stream.writelines(line.encode() for line in lines())
            data_bytes = archive.getinfo("2026-06-29_BTCUSDT_ob200.data").file_size
        results = dict(rows=ROWS, data_bytes=data_bytes, baseline_sha=BASELINE)
        counts = {}
        for name, module in (("before", baseline), ("after", backfill_execute)):
            began = time.perf_counter()
            counts[name] = module.scan(path, job)
            results[name + "_seconds"] = round(time.perf_counter() - began, 3)
            print(json.dumps(results), flush=True)
        assert counts["before"] == counts["after"] == (ROWS, 0), counts
        results["speedup"] = round(results["before_seconds"] / results["after_seconds"], 3)
        print(json.dumps(results), flush=True)
        for name, module in (("before", baseline), ("after", backfill_execute)):
            profile = cProfile.Profile()
            profile.runcall(module.scan, path, job)
            report = io.StringIO()
            pstats.Stats(profile, stream=report).sort_stats("tottime").print_stats(8)
            print(f"profile {name}:\n{report.getvalue()}", flush=True)
        assert results["speedup"] >= REQUIRED_SPEEDUP, results


if __name__ == "__main__":
    main()
