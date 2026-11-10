"""Offline scheduler entrypoints: UTC day, drift gate and pinned container argv."""
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from scripts import cold_deploy as deploy


CONFIG = dict(image="ghcr.io/gptcompany/bybit-downloader@sha256:" + "a" * 64,
              image_source_sha="b" * 40, user="sam", uid=1000, gid=1000,
              cold_root="/data/cold/12TB/bybit_data_downloader/data")


@pytest.fixture
def docker_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, "load_release", lambda release: CONFIG)
    monkeypatch.setattr(deploy, "drift", lambda release, units: dict(outcome="success", mismatches=[]))
    def run(command, **kwargs):
        assert command[0] == "/usr/bin/docker"
        assert not kwargs.get("shell", False)
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(deploy.subprocess, "run", run)
    return calls


def test_daily_entrypoint_uses_yesterday_utc(docker_calls, monkeypatch, capsys):
    class Clock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 11, 10, 0, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(deploy, "datetime", Clock)
    assert deploy.main(["run", "/release"]) == 0
    command = docker_calls[0]
    assert command[command.index("--start-date") + 1] == "2026-11-09"
    assert command[command.index("--end-date") + 1] == "2026-11-09"
    assert CONFIG["image"] in command and "--pull=never" in command
    assert json.loads(capsys.readouterr().out)["outcome"] == "success"


def test_backfill_forwards_explicit_selection_and_dry_run(docker_calls, capsys):
    assert deploy.main(["backfill", "/release", "--start-date", "2026-06-29", "--end-date", "2026-11-09",
                        "--symbols", "BTCUSDT,ETHUSDT", "--types", "trade,orderbook",
                        "--intervals", "1m,5m,15m", "--dry-run"]) == 0
    command = docker_calls[0]
    for flag, value in [("--start-date", "2026-06-29"), ("--end-date", "2026-11-09"),
                        ("--symbols", "BTCUSDT,ETHUSDT"), ("--types", "trade,orderbook"),
                        ("--intervals", "1m,5m,15m")]:
        assert command[command.index(flag) + 1] == value
    assert "--dry-run" in command
    assert "--entrypoint" in command and "bash" not in command


def test_drift_blocks_container(docker_calls, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "drift", lambda release, units: dict(outcome="failure", mismatches=["bybit-cold.timer"]))
    assert deploy.main(["run", "/release"]) == 1
    assert docker_calls == []
    result = json.loads(capsys.readouterr().out)
    assert result["finding"] == "F-649" and result["phase"] == "preflight"
    assert result["downloaded"] == result["skipped"] == result["records"] == 0


def test_container_failure_is_not_success(docker_calls, monkeypatch, capsys):
    monkeypatch.setattr(deploy.subprocess, "run", lambda command: SimpleNamespace(returncode=1))
    assert deploy.main(["run", "/release"]) == 1
    assert json.loads(capsys.readouterr().out)["outcome"] == "failure"


@pytest.mark.parametrize("arguments", [[], ["--start-date", "2026-11-09", "--end-date", "2026-06-29"]])
def test_missing_or_reversed_range_never_launches(docker_calls, arguments, capsys):
    assert deploy.main(["backfill", "/release", *arguments]) == 1
    assert docker_calls == []
