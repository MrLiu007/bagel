"""Sanity checks for ECS Nginx prefix snippet."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCATION = ROOT / "deploy" / "nginx" / "bagel-location.conf"


def test_bagel_location_conf_exists_and_sets_prefix() -> None:
    text = LOCATION.read_text(encoding="utf-8")
    assert "location /bagel/" in text
    assert "proxy_pass http://127.0.0.1:6280/" in text
    assert "X-Forwarded-Prefix /bagel" in text
    assert "X-Script-Name /bagel" in text


def test_compose_uses_bagel_names_and_loopback_bind() -> None:
    text = (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert "name: bagel" in text
    assert "container_name: bagel-app" in text
    assert "container_name: bagel-postgres" in text
    assert "${BAGEL_BIND:-127.0.0.1}:${BAGEL_HOST_PORT:-6280}:8000" in text
    # Must not publish public 80/443 from this stack
    assert "80:80" not in text
    assert "443:443" not in text
