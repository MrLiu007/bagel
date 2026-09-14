"""CHSI direct scrape + watch subscriptions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from bagel.collectors.education import EducationRecord, fetch_from_source
from bagel.collectors.education_chsi import chsi_key_from_path, fetch_chsi_list
from bagel.collectors.education_watch import build_watch_url, parse_watch_ref


SAMPLE_CHSI_HTML = """
<html><body>
<a href="/kyzx/zcdh/202609/20260912.html">关于印发《2026年全国硕士研究生招生工作管理规定》的通知</a>
<span>2026-09-12</span>
<a href="/kyzx/zcdh/202608/20260801.html">四川大学2026年硕士研究生招生简章</a>2026-08-01
</body></html>
"""


def test_chsi_key_from_path() -> None:
    assert chsi_key_from_path("/chsi/kyzx/zcdh") == "zcdh"
    assert chsi_key_from_path("https://yz.chsi.com.cn/kyzx/kydt/") == "kydt"
    assert chsi_key_from_path("/chsi/hotnews") == "kydt"
    assert chsi_key_from_path("/gov/moe/notice") is None


def test_fetch_chsi_list_parses() -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_CHSI_HTML.encode("utf-8")
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = mock_resp

    with patch("bagel.collectors.education_chsi.build_http_client", return_value=mock_client):
        rows = fetch_chsi_list("研招网", "zcdh")
    assert len(rows) >= 1
    assert "研究生" in rows[0].title or "四川大学" in rows[0].title


def test_fetch_from_source_chsi_https() -> None:
    with patch(
        "bagel.collectors.education_chsi.fetch_chsi_list",
        return_value=[
            EducationRecord(
                title="研招网政策导航测试条目",
                url="https://yz.chsi.com.cn/x.html",
                summary="",
                authors="研招网",
                published_at=None,
                source_name="研招网",
                external_id="chsi:zcdh:x",
                institution="研招网",
            )
        ],
    ) as chsi:
        rows = fetch_from_source(
            "研招网 · 政策导航",
            "edu:kaoyan:national:https://yz.chsi.com.cn/kyzx/zcdh/",
        )
    assert len(rows) == 1
    chsi.assert_called_once()


def test_watch_parse_and_build() -> None:
    assert parse_watch_ref("watch:k12:成都") == ("k12", "成都")
    assert parse_watch_ref("watch:kaoyan:四川大学") == ("kaoyan", "四川大学")
    assert build_watch_url(kind="k12", query="杭州") == "watch:k12:杭州"


def test_fetch_from_source_watch_dispatches() -> None:
    with patch(
        "bagel.collectors.education_watch.fetch_watch",
        return_value=[
            EducationRecord(
                title="成都教育改革",
                url="https://edu.sc.gov.cn/x.html",
                summary="",
                authors="四川省教育厅",
                published_at=None,
                source_name="成都 · K12 关注",
                external_id="portal:x",
                institution="四川省教育厅",
            )
        ],
    ) as watch:
        rows = fetch_from_source("成都 · K12 关注", "edu:k12:city:watch:k12:成都")
    assert len(rows) == 1
    watch.assert_called_once()
