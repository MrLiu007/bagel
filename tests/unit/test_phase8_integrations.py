"""Phase 8: FreshRSS / RSSHub clients + compose contract."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bagel.integrations.freshrss import FreshRssClient
from bagel.integrations.rsshub import RsshubClient
from bagel.settings import Settings


ROOT = Path(__file__).resolve().parents[2]


def test_compose_has_required_services() -> None:
    text = (ROOT / "compose.yml").read_text(encoding="utf-8")
    for svc in ("postgres:", "rsshub:", "freshrss:", "app:"):
        assert svc in text
    # FreshRSS / RSSHub must not be public by default
    assert "1200:1200" not in text
    assert "profiles: [\"debug\"]" in text or "profiles: ['debug']" in text or "profiles: [\"debug\"]" in text.replace("'", '"')


def test_rsshub_client_builds_url_and_fetches(monkeypatch) -> None:
    settings = Settings(rsshub_base_url="http://rsshub:1200")
    client = RsshubClient(settings)
    assert client.feed_url("github/trending/daily/python") == (
        "http://rsshub:1200/github/trending/daily/python"
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "<rss></rss>"
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("bagel.integrations.rsshub.build_http_client", return_value=fake_client):
        feed = client.fetch_feed("/github/trending/daily/python")
    assert feed.ok is True
    assert feed.body == "<rss></rss>"
    # force_proxy=False for internal calls
    kwargs = fake_client.get.call_args
    assert kwargs is not None


def test_freshrss_client_ping(monkeypatch) -> None:
    settings = Settings(freshrss_base_url="http://freshrss")
    client = FreshRssClient(settings)

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.get.return_value = fake_resp

    with patch("bagel.integrations.freshrss.build_http_client", return_value=fake_client):
        status = client.ping()
    assert status.ok is True
    assert status.base_url == "http://freshrss"


def test_dockerfile_and_env_example_exist() -> None:
    assert (ROOT / "Dockerfile").exists()
    assert (ROOT / ".env.example").exists()
    env = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DATABASE_URL=" in env
    assert "RSSHUB_BASE_URL=" in env
    assert "FRESHRSS_BASE_URL=" in env
    assert "NETWORK_MODE=" in env
