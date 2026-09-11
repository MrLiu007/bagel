"""Unit tests for yt-dlp URL parsing (no subprocess)."""

from __future__ import annotations

import pytest

from bagel.integrations.ytdlp import YtdlpError, parse_av_source_url, _platform_from_url, _row_to_entry


def test_parse_youtube_channel_handle() -> None:
    plat, url = parse_av_source_url("av:youtube:channel:@3blue1brown")
    assert plat == "youtube"
    assert "@3blue1brown" in url


def test_parse_bilibili_mid() -> None:
    plat, url = parse_av_source_url("av:bilibili:mid:1567748478")
    assert plat == "bilibili"
    assert "1567748478" in url


def test_parse_generic_https() -> None:
    plat, url = parse_av_source_url("av:generic:url:https://www.coursera.org/learn/ml")
    assert plat == "coursera"
    assert url.startswith("https://")


def test_platform_from_url_bilibili() -> None:
    assert _platform_from_url("https://www.bilibili.com/video/BV1xx") == "bilibili"


def test_row_to_entry_minimal() -> None:
    ent = _row_to_entry(
        {
            "id": "abc",
            "title": "Hello",
            "webpage_url": "https://youtube.com/watch?v=abc",
            "uploader": "Test",
            "upload_date": "20240102",
            "duration": 120,
        },
        default_platform="youtube",
    )
    assert ent is not None
    assert ent.title == "Hello"
    assert ent.duration_sec == 120
    assert ent.published_at is not None


def test_parse_invalid_prefix_raises() -> None:
    with pytest.raises(YtdlpError):
        parse_av_source_url("not-a-valid-source")


def test_friendly_bilibili_login_error() -> None:
    from bagel.integrations.ytdlp import _friendly_ytdlp_error

    msg = _friendly_ytdlp_error("login to access playlist", platform="bilibili")
    assert "B 站" in msg
    assert "AV_COOKIES" in msg


def test_friendly_bilibili_412_error() -> None:
    from bagel.integrations.ytdlp import _friendly_ytdlp_error

    msg = _friendly_ytdlp_error(
        "ERROR: [BiliBili] 1DT8u6WEQ7: Unable to download webpage: HTTP Error 412: Precondition Failed",
        platform="bilibili",
    )
    assert "412" in msg
    assert "setup-ytdlp" in msg
    assert "AV_COOKIES" in msg


def test_absolute_out_dir_and_list_media(tmp_path, monkeypatch) -> None:
    from pathlib import Path

    from bagel.integrations.ytdlp import _absolute_out_dir, _list_media_files

    monkeypatch.chdir(tmp_path)
    rel = Path("data/av/files/demo")
    abs_dir = _absolute_out_dir(rel)
    assert abs_dir.is_absolute()
    assert abs_dir == (tmp_path / "data/av/files/demo").resolve()

    abs_dir.mkdir(parents=True)
    (abs_dir / "x.mp4").write_bytes(b"video")
    (abs_dir / "x.m4a").write_bytes(b"audio")
    (abs_dir / "note.vtt").write_text("WEBVTT\n", encoding="utf-8")
    videos = _list_media_files(abs_dir, prefer_audio=False)
    assert videos[0].suffix == ".mp4"
    audios = _list_media_files(abs_dir, prefer_audio=True)
    assert audios[0].suffix == ".m4a"


def test_cookie_attempts_bilibili() -> None:
    from bagel.integrations.ytdlp import _cookie_attempts
    from bagel.settings import Settings

    s = Settings(av_cookies_file="", av_cookies_from_browser="", av_bilibili_browser="edge,chrome")
    assert _cookie_attempts(s, "bilibili") == ["edge", "chrome", None]
    assert _cookie_attempts(s, "youtube") == [None]


def test_cookie_attempts_douyin_defaults_to_browsers() -> None:
    from bagel.integrations.ytdlp import _cookie_attempts
    from bagel.settings import Settings

    s = Settings(av_cookies_file="", av_cookies_from_browser="", av_bilibili_browser="edge")
    assert _cookie_attempts(s, "douyin") == ["edge", "chrome"]
    s2 = Settings(av_cookies_file="", av_cookies_from_browser="chrome", av_bilibili_browser="edge")
    assert _cookie_attempts(s2, "douyin") == ["chrome", "edge"]


def test_friendly_douyin_fresh_cookies_error() -> None:
    from bagel.integrations.ytdlp import _friendly_ytdlp_error

    msg = _friendly_ytdlp_error(
        "ERROR: [Douyin] 123: Fresh cookies (not necessarily logged in) are needed",
        platform="douyin",
    )
    assert "抖音" in msg
    assert "AV_COOKIES_FROM_BROWSER" in msg
    assert "douyin.com" in msg


def test_cookie_attempts_explicit_chrome_then_none() -> None:
    from bagel.integrations.ytdlp import _cookie_attempts
    from bagel.settings import Settings

    s = Settings(av_cookies_file="", av_cookies_from_browser="chrome", av_bilibili_browser="edge")
    assert _cookie_attempts(s, "bilibili") == ["chrome", None]


def test_friendly_chrome_cookie_lock_error() -> None:
    from bagel.integrations.ytdlp import _friendly_ytdlp_error

    msg = _friendly_ytdlp_error(
        "ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271",
        platform="bilibili",
    )
    assert "Chrome" in msg
    assert "edge" in msg.lower()


def test_build_base_cmd_none_skips_browser_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    from bagel.integrations.ytdlp import _build_base_cmd
    from bagel.settings import Settings
    from pathlib import Path

    monkeypatch.setattr("bagel.integrations.ytdlp._ytdlp_executable", lambda root: ["yt-dlp"])
    s = Settings(av_cookies_file="", av_cookies_from_browser="chrome")
    cmd = _build_base_cmd(s, Path("."), browser=None)
    joined = " ".join(cmd)
    assert "--cookies-from-browser" not in joined


def test_build_base_cmd_bilibili_adds_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    from bagel.integrations.ytdlp import _build_base_cmd
    from bagel.settings import Settings
    from pathlib import Path

    monkeypatch.setattr("bagel.integrations.ytdlp._ytdlp_executable", lambda root: ["yt-dlp"])
    s = Settings(av_cookies_file="", av_cookies_from_browser="edge")
    cmd = _build_base_cmd(s, Path("."), browser="edge", platform="bilibili")
    joined = " ".join(cmd)
    assert "--cookies-from-browser edge" in joined
    assert "Referer:https://www.bilibili.com/" in joined
    assert "Origin:https://www.bilibili.com" in joined
    assert "--user-agent" in joined


def test_parse_download_percent() -> None:
    from bagel.integrations.ytdlp import parse_download_percent

    assert parse_download_percent("[download]  45.2% of  12.00MiB at  1.20MiB/s ETA 00:04") == 45.2
    assert parse_download_percent("[download] Destination: foo.m4a") is None
    assert parse_download_percent("unrelated") is None


def test_platform_extra_args_youtube_empty() -> None:
    from bagel.integrations.ytdlp import _platform_extra_args

    assert _platform_extra_args("youtube") == []
    assert _platform_extra_args("bilibili")[0] == "--user-agent"