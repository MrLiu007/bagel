"""MOE direct fallback when RSSHub /gov/moe/* returns 502."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from bagel.collectors.education import fetch_from_source
from bagel.collectors.education_moe import fetch_moe_list, moe_type_from_path


SAMPLE_MOE_HTML = """
<html><body><ul>
<li><a href="./202609/t20260904_1449019.html">测试公告标题甲</a><span>2026-09-04</span></li>
<li><a href="./202608/t20260824_1447643.html">测试公告标题乙</a><span>2026-08-24</span></li>
<li><a href="/jyb_sy/sy_wb/201301/t20130129_147290.html">微博教育</a></li>
</ul></body></html>
"""


def test_moe_type_from_path() -> None:
    assert moe_type_from_path("/gov/moe/notice") == "notice"
    assert moe_type_from_path("/gov/moe/newest_file") == "newest_file"
    assert moe_type_from_path("http://rsshub:1200/gov/moe/policy_anal") == "policy_anal"
    assert moe_type_from_path("/chsi/kyzx/zcdh") is None


def test_fetch_moe_list_parses_items() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_MOE_HTML.encode("utf-8")
    mock_resp.raise_for_status = MagicMock()

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = mock_resp

    with patch("bagel.collectors.education_moe.build_http_client", return_value=mock_client):
        rows = fetch_moe_list("教育部 · 公告公示", "notice")
    assert len(rows) == 2
    assert rows[0].title.startswith("测试公告")
    assert "t20260904" in rows[0].url
    assert rows[0].authors == "教育部"


def test_fetch_moe_list_drops_chrome_footer() -> None:
    html = """
    <html><body><ul>
    <li><a href="./202609/t20260904_1449019.html">测试公告标题甲</a><span>2026-09-04</span></li>
    <li><a href="/jyb_sy/s3634/201005/t20100504_87292.html">网站声明</a></li>
    <li><a href="/jyb_sy/s3636/202404/t20240411_1125026.html">网站地图</a></li>
    <li><a href="/jyb_sy/s3635/201611/t20161129_290403.html">联系我们</a></li>
    </ul></body></html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = html.encode("utf-8")
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = mock_resp

    with patch("bagel.collectors.education_moe.build_http_client", return_value=mock_client):
        rows = fetch_moe_list("教育部 · 公告公示", "notice")
    assert len(rows) == 1
    assert rows[0].title.startswith("测试公告")


def test_fetch_from_source_moe_fallback_on_rsshub_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSSHUB_BASE_URL", "http://rsshub:1200")
    from bagel.collectors.education import EducationRecord
    from bagel.settings import get_settings

    get_settings.cache_clear()

    def boom(*_a, **_k):
        raise httpx.HTTPStatusError(
            "502 Bad Gateway",
            request=httpx.Request("GET", "http://rsshub:1200/gov/moe/notice"),
            response=httpx.Response(502),
        )

    with (
        patch("bagel.collectors.education.fetch_rss", side_effect=boom),
        patch(
            "bagel.collectors.education_moe.fetch_moe_list",
            return_value=[
                EducationRecord(
                    title="直连条目",
                    url="https://www.moe.gov.cn/x.html",
                    summary="",
                    authors="教育部",
                    published_at=None,
                    source_name="教育部 · 公告公示",
                    external_id="moe:notice:x",
                    institution="教育部",
                )
            ],
        ) as moe,
    ):
        rows = fetch_from_source("教育部 · 公告公示", "edu:k12:national:/gov/moe/notice")
    assert len(rows) == 1
    assert rows[0].title == "直连条目"
    moe.assert_called_once()
    get_settings.cache_clear()
