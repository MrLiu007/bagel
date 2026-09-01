"""Auth gate behaviour — login redirect vs CDP probe 404."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.settings import get_settings
from bagel.web.auth_gate import is_probe_path, wants_html


def test_probe_paths_detected() -> None:
    assert is_probe_path("/json/version")
    assert is_probe_path("/json/list")
    assert is_probe_path("/favicon.ico")
    assert is_probe_path("/.well-known/appspecific/com.chrome.devtools.json")
    assert not is_probe_path("/")
    assert not is_probe_path("/news")
    assert not is_probe_path("/login")


def test_cdp_probe_returns_404_not_login_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/json/version", follow_redirects=False)
        assert resp.status_code == 404
        assert "/login" not in (resp.headers.get("location") or "")
    finally:
        get_settings.cache_clear()


def test_home_redirects_to_login_when_auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/login")
        assert "next=/" in resp.headers["location"] or "next=%2F" in resp.headers["location"]
    finally:
        get_settings.cache_clear()


def test_login_page_preserves_next(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/login?next=/news")
        assert resp.status_code == 200
        assert 'name="next"' in resp.text
        assert 'value="/news"' in resp.text
    finally:
        get_settings.cache_clear()


def test_wants_html_for_browser_navigation() -> None:
    from starlette.requests import Request

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [
            (b"accept", b"text/html,application/xhtml+xml"),
            (b"sec-fetch-mode", b"navigate"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
    }
    assert wants_html(Request(scope)) is True
