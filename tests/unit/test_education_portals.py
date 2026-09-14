"""Portal scrape + watch subscription tests."""

from __future__ import annotations

from unittest.mock import patch

from bagel.collectors.education import EducationRecord
from bagel.collectors.education_html_list import scrape_list_page
from bagel.collectors.education_portals import resolve_portal
from bagel.collectors.education_watch import build_watch_url, fetch_watch, parse_watch_ref


SCU_HTML = """
<html><body>
<a href="/zsxx/Details/1b2831ad-f372-4084-8462-3b739189cf94" class="data-one">
四川大学2027年硕士研究生招生简章
</a>
2026/9/10
<a href="/zsxx/Details/722a4f5b-416f-42b6-b095-8f8638452014" class="data-one">
四川大学2026年国优计划专项硕士研究生招生简章
</a>
2026/9/4
<a href="/home">首页</a>
</body></html>
"""

SJTU_HTML = """
<html><body>
<a href="/post/3529" class="item">
  <div class="month">2026.09</div>
  <div class="title">上海交通大学2026年硕士研究生招生章程</div>
</a>
<a href="/post/3694" class="item">
  <div class="month">2026.07</div>
  <div class="title">上海交通大学2026年拟录取全日制硕士研究生调档通知</div>
</a>
</body></html>
"""

SCEDU_HTML = """
<html><body>
<a href="/scedu/c100495/2026/9/2/85ebd964d59c407081c311c82.shtml" title="2026年四川省特级教师名单公示">
2026年四川省特级教师名单公示
</a>
<a href="/scedu/c100495/2026/9/10/a03246a95fbd49d1b0354592.shtml">
关于四川省2026年中小学教师书法大赛的通知
</a>
</body></html>
"""


def test_resolve_portals() -> None:
    assert resolve_portal("四川大学", kind="kaoyan").key == "scu"
    assert resolve_portal("上交", kind="kaoyan").key == "sjtu"
    assert resolve_portal("成都", kind="k12").key == "sichuan"
    assert resolve_portal("火星大学", kind="kaoyan") is None


def test_scrape_scu_list(monkeypatch) -> None:
    monkeypatch.setattr(
        "bagel.collectors.education_html_list.fetch_html",
        lambda *_a, **_k: SCU_HTML,
    )
    rows = scrape_list_page("川大", "https://yz.scu.edu.cn/zsxx/newslist/ss/gg")
    assert len(rows) >= 2
    assert all("Details" in r.url for r in rows)
    assert "招生" in rows[0].title


def test_scrape_sjtu_cards(monkeypatch) -> None:
    monkeypatch.setattr(
        "bagel.collectors.education_html_list.fetch_html",
        lambda *_a, **_k: SJTU_HTML,
    )
    rows = scrape_list_page("上交", "https://yzb.sjtu.edu.cn/zkxx/sszs")
    assert len(rows) == 2
    assert rows[0].url.endswith("/post/3529") or rows[1].url.endswith("/post/3529")


def test_fetch_watch_uses_portal(monkeypatch) -> None:
    monkeypatch.setattr(
        "bagel.collectors.education_html_list.fetch_html",
        lambda url, **_k: SCU_HTML if "scu.edu.cn" in url else SCEDU_HTML,
    )
    with patch("bagel.collectors.education_watch.fetch_chsi_watch", return_value=[]):
        rows = fetch_watch("四川大学 · 考研关注", "watch:kaoyan:四川大学", max_results=5)
    assert len(rows) >= 2
    assert any("yz.scu.edu.cn" in r.url for r in rows)

    with patch("bagel.collectors.education_watch.fetch_k12_keyword", return_value=[]):
        city = fetch_watch("成都 · K12 关注", "watch:k12:成都", max_results=5)
    assert len(city) >= 1
    assert any("edu.sc.gov.cn" in r.url for r in city)


def test_fetch_watch_empty_not_raise(monkeypatch) -> None:
    monkeypatch.setattr(
        "bagel.collectors.education_watch.resolve_portal",
        lambda *_a, **_k: None,
    )
    with (
        patch("bagel.collectors.education_watch.fetch_chsi_watch", return_value=[]),
        patch("bagel.collectors.education_watch._soft_national", return_value=[]),
    ):
        rows = fetch_watch("未知校", "watch:kaoyan:未知校")
    assert rows == []


def test_watch_parse() -> None:
    assert parse_watch_ref("watch:k12:成都") == ("k12", "成都")
    assert build_watch_url(kind="kaoyan", query="川大") == "watch:kaoyan:川大"
