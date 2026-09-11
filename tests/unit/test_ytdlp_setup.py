"""Unit tests for yt-dlp setup helpers (no network)."""

from __future__ import annotations

from pathlib import Path

from bagel.services import ytdlp_setup


def test_gitignore_covers_ytdlp() -> None:
    gi = (Path(__file__).resolve().parents[2] / ".gitignore").read_text(encoding="utf-8")
    assert "third_party/yt-dlp/" in gi


def test_is_checkout_ready_false_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "yt-dlp"
    target.mkdir()
    assert ytdlp_setup.is_checkout_ready(target) is False


def test_is_checkout_ready_true_with_package(tmp_path: Path) -> None:
    target = tmp_path / "yt-dlp"
    pkg = target / "yt_dlp"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    assert ytdlp_setup.is_checkout_ready(target) is True
