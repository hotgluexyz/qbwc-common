"""Pytest configuration for qbwc-common unit tests."""

import pytest


@pytest.fixture(autouse=True)
def no_poll_sleep(monkeypatch):
    """Poll loop uses time.sleep(1) between queued/in_progress polls."""
    monkeypatch.setattr("qbwc_common.client.time.sleep", lambda _: None)
