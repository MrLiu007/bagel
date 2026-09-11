"""Unit tests for openspeech / Volcengine ASR client (mocked HTTP)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bagel.integrations import volc_asr
from bagel.settings import Settings


@pytest.fixture()
def audio_file(tmp_path: Path) -> Path:
    p = tmp_path / "clip.mp3"
    p.write_bytes(b"ID3" + b"\x00" * 200)
    return p


@pytest.fixture()
def volc_settings() -> Settings:
    return Settings(
        volc_asr_api_key="test-key",
        volc_asr_mode="async",
        volc_asr_poll_interval_sec=0.01,
        volc_asr_poll_timeout_sec=2.0,
        volc_asr_http_timeout_sec=5.0,
        volc_asr_max_retries=2,
        av_asr_language="zh",
    )


def test_volc_asr_configured_new_and_old() -> None:
    assert volc_asr.volc_asr_configured(Settings(volc_asr_api_key="k")) is True
    assert (
        volc_asr.volc_asr_configured(
            Settings(volc_asr_app_id="a", volc_asr_access_key="t")
        )
        is True
    )
    assert volc_asr.volc_asr_configured(Settings()) is False
    assert volc_asr.volc_asr_configured(Settings(volc_asr_app_id="only")) is False


def test_auth_headers_prefer_appkey() -> None:
    s = Settings(
        volc_asr_api_key="new-key",
        volc_asr_app_id="app1",
        volc_asr_access_key="tok1",
    )
    h = volc_asr._auth_headers(s, "rid", resource_id="volc.seedasr.auc", with_sequence=True)
    assert h["X-Api-App-Key"] == "app1"
    assert h["X-Api-Access-Key"] == "tok1"
    assert "X-Api-Key" not in h
    assert h["X-Api-Sequence"] == "-1"
    assert h["X-Api-Request-Id"] == "rid"


def test_auth_headers_apikey_only() -> None:
    s = Settings(volc_asr_api_key="only-key")
    h = volc_asr._auth_headers(s, "rid", resource_id="volc.seedasr.auc")
    assert h["X-Api-Key"] == "only-key"
    assert "X-Api-App-Key" not in h


def test_extract_text_dict_and_utterances() -> None:
    assert "你好" in volc_asr._extract_text({"result": {"text": "你好世界"}})
    body = {
        "result": {
            "text": "",
            "utterances": [{"text": "第一句"}, {"text": "第二句"}],
        }
    }
    text = volc_asr._extract_text(body)
    assert "第一句" in text and "第二句" in text


def test_language_code_mapping() -> None:
    assert volc_asr._language_code("zh") == "zh-CN"
    assert volc_asr._language_code("en") == "en-US"
    assert volc_asr._language_code("ja-JP") == "ja-JP"


def test_async_submit_and_poll_success(audio_file: Path, volc_settings: Settings, monkeypatch) -> None:
    calls = {"n": 0}
    seen_headers: list[dict] = []

    def fake_post(url, headers=None, json=None, **kwargs):  # noqa: A002
        calls["n"] += 1
        seen_headers.append(dict(headers or {}))
        if "submit" in url:
            return httpx.Response(
                200,
                headers={
                    "X-Api-Status-Code": "20000000",
                    "X-Api-Message": "OK",
                    "X-Tt-Logid": "log-submit",
                },
                json={},
            )
        if calls["n"] == 2:
            return httpx.Response(
                200,
                headers={"X-Api-Status-Code": "20000001", "X-Api-Message": "processing"},
                json={},
            )
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000", "X-Api-Message": "OK", "X-Tt-Logid": "log-q"},
            json={"result": {"text": "我们来说一下这一周的AI大事件"}},
        )

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):  # noqa: A002
            return fake_post(url, headers=headers, json=json)

    monkeypatch.setattr(volc_asr.httpx, "Client", FakeClient)

    result = volc_asr.transcribe_volcengine(audio_file, settings=volc_settings)
    assert result["status"] == "done"
    assert "AI大事件" in result["text"]
    assert result["reason"] == "asr_volc_async"
    assert seen_headers[0].get("X-Api-Key") == "test-key"


def test_endpoints_are_openspeech() -> None:
    assert "openspeech.bytedance.com" in volc_asr.SUBMIT_URL
    assert "openspeech.bytedance.com" in volc_asr.QUERY_URL
    assert "openspeech.bytedance.com" in volc_asr.FLASH_URL
    assert volc_asr.SUBMIT_URL.endswith("/api/v3/auc/bigmodel/submit")
    assert volc_asr.FLASH_URL.endswith("/api/v3/auc/bigmodel/recognize/flash")


def test_flash_then_fallback_async(audio_file: Path, monkeypatch) -> None:
    settings = Settings(
        volc_asr_api_key="k",
        volc_asr_mode="auto",
        volc_asr_flash_max_mb=10,
        volc_asr_poll_interval_sec=0.01,
        volc_asr_poll_timeout_sec=2.0,
        volc_asr_max_retries=1,
    )
    seen: list[str] = []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):  # noqa: A002
            seen.append(url)
            if "flash" in url:
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "45000001", "X-Api-Message": "bad"},
                    json={},
                )
            if "submit" in url:
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "20000000", "X-Api-Message": "OK"},
                    json={},
                )
            return httpx.Response(
                200,
                headers={"X-Api-Status-Code": "20000000"},
                json={"result": {"text": "异步成功文稿"}},
            )

    monkeypatch.setattr(volc_asr.httpx, "Client", FakeClient)
    result = volc_asr.transcribe_volcengine(audio_file, settings=settings)
    assert result["status"] == "done"
    assert result["text"] == "异步成功文稿"
    assert any("flash" in u for u in seen)
    assert any("submit" in u for u in seen)


def test_async_uses_appkey_headers(audio_file: Path, monkeypatch) -> None:
    settings = Settings(
        volc_asr_app_id="987654",
        volc_asr_access_key="access-token-xyz",
        volc_asr_mode="async",
        volc_asr_poll_interval_sec=0.01,
        volc_asr_poll_timeout_sec=2.0,
        volc_asr_max_retries=1,
    )
    captured: dict = {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):  # noqa: A002
            if "submit" in url:
                captured["headers"] = dict(headers or {})
                captured["body"] = json
                return httpx.Response(
                    200,
                    headers={"X-Api-Status-Code": "20000000", "X-Tt-Logid": "L1"},
                    json={},
                )
            return httpx.Response(
                200,
                headers={"X-Api-Status-Code": "20000000"},
                json={"result": {"text": "appkey识别成功"}},
            )

    monkeypatch.setattr(volc_asr.httpx, "Client", FakeClient)
    result = volc_asr.transcribe_volcengine(audio_file, settings=settings)
    assert result["status"] == "done"
    assert captured["headers"]["X-Api-App-Key"] == "987654"
    assert captured["headers"]["X-Api-Access-Key"] == "access-token-xyz"
    assert "X-Api-Key" not in captured["headers"]
    assert captured["body"]["user"]["uid"] == "987654"
    assert "data" in captured["body"]["audio"]


def test_missing_creds(audio_file: Path) -> None:
    result = volc_asr.transcribe_volcengine(audio_file, settings=Settings())
    assert result["status"] == "failed"
    assert result["reason"] == "no_volc_creds"


def test_auto_cascade_prefers_volc(monkeypatch, tmp_path: Path) -> None:
    from bagel.integrations import av_transcript

    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x" * 100)
    settings = Settings(
        av_asr_enabled=True,
        av_asr_backend="auto",
        volc_asr_api_key="k",
        data_dir=str(tmp_path / "data"),
    )

    monkeypatch.setattr(
        "bagel.integrations.volc_asr.transcribe_volcengine",
        lambda *a, **k: {"status": "done", "text": "火山文稿内容足够长", "reason": "asr_volc_async"},
    )
    monkeypatch.setattr(
        "bagel.integrations.av_transcript._transcribe_openai",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("openai should not run")),
    )

    media = tmp_path / "v.mp4"
    media.write_bytes(b"fake")
    monkeypatch.setattr(
        "bagel.integrations.av_transcript.extract_audio_track",
        lambda *a, **k: {"status": "done", "audio_path": str(audio)},
    )

    result = av_transcript.transcribe_local_media(
        media, work_dir=tmp_path / "work", settings=settings
    )
    assert result["status"] == "done"
    assert result["backend"] == "volcengine"
    assert "火山文稿" in result["text"]
