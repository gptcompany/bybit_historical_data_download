"""Offline transport regressions for planning and atomic cold downloads."""
import json
from datetime import date

import httpx
import pytest

from bybit_data_downloader import backfill
from bybit_data_downloader.backfill_execute import execute
from test_backfill_execute import archive


@pytest.mark.parametrize("phase", ["planning", "execution"])
def test_404_is_immediate(phase, tmp_path, capsys):
    job, _ = archive(tmp_path)
    calls = []
    def respond(request):
        calls.append(request.method)
        return httpx.Response(404)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            if phase == "planning":
                backfill.plan(date(2026, 11, 9), date(2026, 11, 9), ["BTCUSDT"], ["trade"], ["1m"], client)
            else:
                execute([job], tmp_path, client)
    assert calls == (["HEAD"] if phase == "planning" else ["GET"])
    assert not (tmp_path / job["path"]).exists()
    assert not list(tmp_path.rglob("*.part"))
