"""Bind-port diagnostics for `bagel dev`."""

from __future__ import annotations

import pytest

from bagel.cli.ports import (
    can_bind,
    diagnose_bind_failure,
    port_in_excluded_range,
    resolve_bind_port,
)


def test_port_in_excluded_range() -> None:
    ranges = [(7991, 8090), (8648, 8747)]
    assert port_in_excluded_range(8000, ranges) is True
    assert port_in_excluded_range(8765, ranges) is False


def test_resolve_keeps_preferred_when_free(monkeypatch) -> None:
    monkeypatch.setattr("bagel.cli.ports.can_bind", lambda host, port: port == 8000)
    port, warning = resolve_bind_port("127.0.0.1", 8000, auto_port=False)
    assert port == 8000
    assert warning is None


def test_resolve_raises_without_auto_port(monkeypatch) -> None:
    monkeypatch.setattr("bagel.cli.ports.can_bind", lambda host, port: False)
    monkeypatch.setattr("bagel.cli.ports.listener_pids", lambda port: [4242])
    monkeypatch.setattr("bagel.cli.ports.windows_excluded_tcp_ranges", lambda: [])
    with pytest.raises(OSError, match="4242"):
        resolve_bind_port("127.0.0.1", 8000, auto_port=False)


def test_resolve_auto_port_falls_back(monkeypatch) -> None:
    # 8001/8002 sit inside 7991-8090; auto-port must skip them and pick 8888.
    monkeypatch.setattr(
        "bagel.cli.ports.can_bind", lambda host, port: port == 8888
    )
    monkeypatch.setattr("bagel.cli.ports.listener_pids", lambda port: [])
    monkeypatch.setattr(
        "bagel.cli.ports.windows_excluded_tcp_ranges", lambda: [(7991, 8090)]
    )
    port, warning = resolve_bind_port("127.0.0.1", 8000, auto_port=True)
    assert port == 8888
    assert warning and "Auto-switched" in warning


def test_diagnose_mentions_winnat(monkeypatch) -> None:
    monkeypatch.setattr("bagel.cli.ports.listener_pids", lambda port: [])
    monkeypatch.setattr(
        "bagel.cli.ports.windows_excluded_tcp_ranges", lambda: [(7991, 8090)]
    )
    text = diagnose_bind_failure("127.0.0.1", 8000)
    assert "7991-8090" in text
    assert "winnat" in text.lower()


def test_can_bind_ephemeral() -> None:
    assert can_bind("127.0.0.1", 0) is True
