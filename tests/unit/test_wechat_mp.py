"""Tests for WeChat MP article parse / config nav / tip cleanup helpers."""

from __future__ import annotations

from bagel.domain.enums import ItemType
from bagel.integrations.wechat_mp import (
    WechatMpError,
    _looks_blocked,
    is_wechat_mp_url,
    normalize_mp_url,
    parse_mp_html,
    sanitize_rich_html,
)
from bagel.services.env_config import ENV_CATALOG, CONFIG_FAMILIES, resolve_config_nav


SAMPLE_HTML = """
<html><head>
<meta property="og:title" content="大模型落地实践分享" />
<meta property="og:description" content="本文介绍 RAG 与 Agent 的落地经验。" />
<title>大模型落地实践分享 - 微信公众平台</title>
<script>
var ct = "1710000000";
var nickname = "AI前线";
// Legitimate pages often ship captcha/verify helpers in JS bundles.
window.__verify = function(){};
var captcha = null;
</script>
</head><body>
<strong class="profile_nickname">AI前线</strong>
<div id="js_content">
  <p>正文第一段讲 RAG。</p>
  <p><img data-src="https://mmbiz.qpic.cn/demo.jpg" alt="图1" /></p>
  <p><a href="https://example.com/doc">参考链接</a></p>
  <video data-src="https://example.com/a.mp4" controls></video>
  <audio src="https://example.com/a.mp3" controls></audio>
  <div><p>嵌套段落</p></div>
</div>
<script></script>
</body></html>
"""


def test_is_wechat_mp_url() -> None:
    assert is_wechat_mp_url("https://mp.weixin.qq.com/s/abc")
    assert not is_wechat_mp_url("https://example.com/s/abc")


def test_normalize_mp_url_rejects_other_hosts() -> None:
    try:
        normalize_mp_url("https://www.zhihu.com/p/1")
        assert False, "expected error"
    except WechatMpError as exc:
        assert "mp.weixin.qq.com" in exc.message


def test_parse_mp_html_keeps_rich_media() -> None:
    art = parse_mp_html(SAMPLE_HTML, url="https://mp.weixin.qq.com/s/abc")
    assert art.title == "大模型落地实践分享"
    assert art.account == "AI前线"
    assert art.content_is_html
    assert "<img" in art.content
    assert 'src="https://mmbiz.qpic.cn/demo.jpg"' in art.content
    assert "<video" in art.content
    assert "<audio" in art.content
    assert 'href="https://example.com/doc"' in art.content
    assert "RAG" in art.content
    assert art.published_at is not None


def test_verify_captcha_in_js_not_blocked_when_js_content_present() -> None:
    assert not _looks_blocked(SAMPLE_HTML)


def test_hard_block_without_js_content() -> None:
    html = "<html><body>该内容无法查看</body></html>"
    assert _looks_blocked(html)


def test_sanitize_strips_script() -> None:
    raw = '<p>ok</p><script>alert(1)</script><img src="https://x.com/a.png" onerror="x">'
    out = sanitize_rich_html(raw)
    assert "<script" not in out.lower()
    assert "onerror" not in out.lower()
    assert "<img" in out
    assert "ok" in out


def test_resolve_config_nav_three_pane() -> None:
    groups = [
        {"group": "应用", "fields": [{"key": "APP_PORT"}]},
        {"group": "网络", "fields": [{"key": "HTTP_PROXY"}]},
        {"group": "微信", "fields": [{"key": "ENABLE_WECHAT"}]},
    ]
    nav = resolve_config_nav(groups, family="网络", group="网络")
    assert nav["active_family"] == "网络"
    assert nav["active_group"] == "网络"
    assert nav["active_fields"][0]["key"] == "HTTP_PROXY"
    nav2 = resolve_config_nav(groups, family="AI 与推送")
    assert nav2["active_family"] == "AI 与推送"
    assert "微信" in nav2["subgroups"]


def test_localize_rewrites_img_to_local(monkeypatch, tmp_path) -> None:
    from bagel.integrations import wechat_mp_media as media

    monkeypatch.setattr(media, "media_root", lambda settings=None: tmp_path / "wechat_mp")

    def fake_download(url, *, dest, settings=None, max_bytes=0, timeout=0):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"\xff\xd8\xfffakejpeg")
        return True, "image/jpeg", ""

    monkeypatch.setattr(media, "download_media_file", fake_download)
    html = '<p>x</p><img data-src="https://mmbiz.qpic.cn/a.jpg" alt="a" />'
    out, info = media.localize_article_html(html, item_id="11111111-1111-1111-1111-111111111111")
    assert info["asset_count"] == 1
    assert 'src="/api/wechat/articles/' in out
    assert "mmbiz.qpic.cn" not in out


def test_build_and_parse_wechat_mp_source_url() -> None:
    from bagel.integrations.wechat_mp_discover import build_source_url, parse_source_url

    url = build_source_url(name="机器之心", wxid="almosthuman2014")
    assert url.startswith("wechat:mp:")
    ref = parse_source_url(url)
    assert ref.name == "机器之心"
    assert ref.wxid == "almosthuman2014"
    name_only = parse_source_url(build_source_url(name="量子位"))
    assert name_only.name == "量子位"
    assert name_only.wxid == ""
    with_feed = parse_source_url(
        build_source_url(name="机器之心", feed_url="http://127.0.0.1:4000/feeds/MP_WXS_1.json")
    )
    assert with_feed.feed_url.endswith("MP_WXS_1.json")


def test_parse_feed_articles_json_and_rss() -> None:
    from bagel.integrations.wechat_mp_discover import parse_feed_articles

    body = """
    {
      "title": "机器之心",
      "items": [
        {
          "title": "新文章",
          "url": "https://mp.weixin.qq.com/s/abcdefg",
          "date_published": "2026-09-01T10:00:00Z",
          "authors": [{"name": "机器之心"}]
        },
        {
          "title": "外链",
          "url": "https://example.com/x"
        }
      ]
    }
    """
    arts = parse_feed_articles(body, limit=5)
    assert len(arts) == 1
    assert arts[0].title == "新文章"
    assert "mp.weixin.qq.com" in arts[0].url

    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>量子位</title>
    <item><title>A</title><link>https://mp.weixin.qq.com/s/zzz</link>
    <pubDate>Mon, 01 Sep 2026 10:00:00 GMT</pubDate></item>
    </channel></rss>"""
    arts2 = parse_feed_articles(rss, limit=5)
    assert len(arts2) == 1
    assert arts2[0].url.endswith("/s/zzz")


def test_parse_sogou_relative_links_and_author_filter() -> None:
    from bagel.integrations.wechat_mp_discover import (
        _author_matches,
        _extract_mp_from_bridge_html,
        _parse_sogou_article_items,
        empty_discover_hint,
    )

    html = """
    <ul class="news-list">
      <li id="sogou_vr_11002601_box_0">
        <div class="txt-box">
          <h3><a href="/link?url=abc&amp;token=t1">机器之心 标题<em>x</em></a></h3>
          <span class="all-time-y2">机器之心</span>
        </div>
      </li>
      <li id="sogou_vr_11002601_box_1">
        <div class="txt-box">
          <h3><a href="/link?url=def&amp;token=t2">其他号提及机器之心</a></h3>
          <span class="all-time-y2">算法邦</span>
        </div>
      </li>
    </ul>
    """
    items = _parse_sogou_article_items(html)
    assert len(items) == 2
    assert items[0][0].startswith("/link?url=")
    assert items[0][2] == "机器之心"
    assert _author_matches("机器之心", "机器之心")
    assert not _author_matches("智猩猩AI", "算法邦")

    bridge = """
    <script>
    setTimeout(function () {
        var url = '';
        url += 'https://mp.w';
        url += 'eixin.qq.co';
        url += 'm/s?src=11&signature=ab*cd';
        url.replace("@", "");
        window.location.replace(url)
    },100);
    </script>
    """
    mp = _extract_mp_from_bridge_html(bridge)
    assert mp.startswith("https://mp.weixin.qq.com/s?")
    assert "ab*cd" in mp

    hint = empty_discover_hint("机器之心", {"sogou_enabled": False})
    assert "WeWe-RSS" in hint


def test_discover_prefers_feed_url(monkeypatch) -> None:
    from bagel.integrations import wechat_mp_discover as disc

    def fake_feed(feed_url, *, settings, limit, lookback_days):
        return [
            disc.DiscoveredArticle(
                url="https://mp.weixin.qq.com/s/fromfeed",
                title="from feed",
                author="机器之心",
            )
        ], {"kept": 1}

    monkeypatch.setattr(disc, "_discover_via_feed_url", fake_feed)
    monkeypatch.setattr(
        disc,
        "_discover_via_wewe",
        lambda *a, **k: ([], {"skipped": "not_configured"}),
    )
    arts, meta = disc.discover_articles(
        disc.WechatMpSourceRef(
            name="机器之心",
            feed_url="http://127.0.0.1:4000/feeds/x.json",
        ),
        limit=3,
    )
    assert len(arts) == 1
    assert arts[0].url.endswith("/fromfeed")
    assert "feed" in meta["methods"]


def test_run_collect_wechat_mp_empty_sources() -> None:
    from unittest.mock import MagicMock

    from bagel.jobs.wechat_mp import run_collect_wechat_mp

    session = MagicMock()
    session.scalars.return_value.all.return_value = []
    result = run_collect_wechat_mp(session)
    assert result["status"] == "FAILED"
    assert result["items_created"] == 0
    assert "未订阅" in (result.get("error") or "")


def test_all_env_groups_mapped_no_loss() -> None:
    catalog_groups = {f.group for f in ENV_CATALOG}
    mapped = {g for _, gs in CONFIG_FAMILIES for g in gs}
    assert catalog_groups <= mapped
    assert len(ENV_CATALOG) >= 90


def test_wechat_article_item_type_exists() -> None:
    assert ItemType.WECHAT_ARTICLE == "WECHAT_ARTICLE"
