import pytest

INVOCATION_ID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def systemd_invocation(monkeypatch):
    """Runners execute only inside a systemd unit, which names their container."""
    monkeypatch.setenv("INVOCATION_ID", INVOCATION_ID)
