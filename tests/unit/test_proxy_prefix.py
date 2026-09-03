"""Reverse-proxy path prefix (X-Forwarded-Prefix / X-Script-Name)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bagel.main import create_app
from bagel.settings import get_settings
from bagel.web.proxy_prefix import app_url
from starlette.requests import Request


def _scope(*, root_path: str = "", path: str = "/") -> dict:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 8000),
        "root_path": root_path,
    }


def test_app_url_without_prefix() -> None:
    req = Request(_scope())
    assert app_url(req, "/login") == "/login"
    assert app_url(req, "/static/css/theme.css") == "/static/css/theme.css"


def test_app_url_with_prefix() -> None:
    req = Request(_scope(root_path="/bagel"))
    assert app_url(req, "/login") == "/bagel/login"
    assert app_url(req, "/") == "/bagel/"


def test_login_form_action_with_forwarded_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/login", headers={"X-Forwarded-Prefix": "/bagel"})
        assert resp.status_code == 200
        assert 'action="/bagel/login"' in resp.text
        assert 'href="/bagel/static/css/theme.css"' in resp.text
    finally:
        get_settings.cache_clear()


def test_auth_redirect_location_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "true")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/", headers={"X-Forwarded-Prefix": "/bagel"}, follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/bagel/login")
        assert "next=%2F" in resp.headers["location"] or "next=/" in resp.headers["location"]
    finally:
        get_settings.cache_clear()


def test_login_post_redirect_preserves_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        from bagel.storage.database import init_db

        init_db(seed=True)
        client = TestClient(create_app())
        resp = client.post(
            "/login",
            headers={"X-Forwarded-Prefix": "/bagel"},
            data={"username": "liuzemin", "password": "123456", "next": "/"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/bagel/"
    finally:
        get_settings.cache_clear()


def test_x_script_name_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_REQUIRED", "false")
    get_settings.cache_clear()
    try:
        client = TestClient(create_app())
        resp = client.get("/login", headers={"X-Script-Name": "/bagel"})
        assert resp.status_code == 200
        assert 'action="/bagel/login"' in resp.text
    finally:
        get_settings.cache_clear()
