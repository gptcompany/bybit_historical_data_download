"""CI-only same-input comparison against the deployed ID validator (no network)."""
import gzip
import json
import random
import subprocess
import tempfile
import time
import types
from pathlib import Path

from bybit_data_downloader import backfill_execute

BASELINE = "b1327edbcbc4da0ad49c527001d8141e0799c1d5"
ROWS = 4_320_000


def load_baseline(sha):
    source = subprocess.check_output([
        "git", "--no-replace-objects", "show",
        f"{sha}:src/bybit_data_downloader/backfill_execute.py",
    ], text=True)
    baseline = types.ModuleType("bybit_data_downloader._baseline")
    exec(compile(source, "baseline_backfill_execute.py", "exec"), baseline.__dict__)
    return baseline


def main():
    baseline = load_baseline(BASELINE)
    job = dict(day="2026-08-23", symbol="ETHUSDT", type="trade", source="archive")
    start, _ = backfill_execute.bounds(job)
    rng = random.Random(649)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ETHUSDT2026-08-23.csv.gz"
        with gzip.open(path, "wt", compresslevel=1) as stream:
            stream.write(",".join(backfill_execute.TRADE_V1_FIELDS) + "\n")
            for index in range(ROWS):
                timestamp = start + index * 20
                identity = f"{rng.getrandbits(128):032x}"
                stream.write(f"{timestamp // 1000}.{timestamp % 1000:03d},ETHUSDT,Buy,1,2,PlusTick,{identity},2,1,2\n")
        results = dict(rows=ROWS, gzip_bytes=path.stat().st_size, baseline_sha=BASELINE)
        temporary_directory = tempfile.TemporaryDirectory
        class MeasuredDirectory(temporary_directory):
            def __exit__(self, *args):
                results[name + "_scratch_bytes"] = sum(
                    item.stat().st_size for item in Path(self.name).iterdir() if item.is_file())
                return super().__exit__(*args)
        for name, module in (("before", baseline), ("after", backfill_execute)):
            began = time.perf_counter()
            tempfile.TemporaryDirectory = MeasuredDirectory
            try:
                assert module.validate(path, job) == ROWS
            finally:
                tempfile.TemporaryDirectory = temporary_directory
            results[name + "_seconds"] = round(time.perf_counter() - began, 3)
            print(json.dumps(results), flush=True)
        results["speedup"] = round(results["before_seconds"] / results["after_seconds"], 3)
        print(json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
