"""Download WeChat MP article media to local disk and rewrite HTML src.

Browser hotlinking to mmbiz.qpic.cn / video CDNs fails without WeChat Referer;
serving local copies (or a same-origin proxy) fixes list/detail display.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from uuid import UUID

from bagel.integrations.http import build_http_client
from bagel.settings import NetworkMode, Settings, get_settings

_SRC_RE = re.compile(
    r"""(?P<prefix>\b(?:src|data-src|poster)\s*=\s*["'])(?P<url>[^"']+)(?P<suffix>["'])""",
    re.I,
)
_WECHAT_MEDIA_HOSTS = (
    "mmbiz.qpic.cn",
    "mmbiz.qlogo.cn",
    "mmsns.qpic.cn",
    "szmmsns.qpic.cn",
    "wxsnsdy.wxs.qq.com",
    "findermp.video.qq.com",
    "mpvideo.qpic.cn",
    "v.qq.com",
    "video.qq.com",
    "wx.qlogo.cn",
)
_DOWNLOAD_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 MicroMessenger/7.0.20"
    ),
    "Referer": "https://mp.weixin.qq.com/",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
_EXT_BY_CT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "application/octet-stream": "",
}
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_AV_BYTES = 80 * 1024 * 1024


def media_root(settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return Path(s.data_dir) / "wechat_mp"


def item_media_dir(item_id: UUID | str, settings: Settings | None = None) -> Path:
    return media_root(settings) / str(item_id)


def _is_downloadable_url(url: str) -> bool:
    low = (url or "").strip().lower()
    if not low or low.startswith(("data:", "javascript:", "blob:", "#")):
        return False
    if low.startswith("//"):
        return True
    if not low.startswith(("http://", "https://")):
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    if not host:
        return False
    # Prefer WeChat / Tencent CDNs; also allow generic https media linked in articles
    if any(host == h or host.endswith("." + h) for h in _WECHAT_MEDIA_HOSTS):
        return True
    path = urlparse(url).path.lower()
    return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".m4a"))


def _normalize_url(url: str, *, page_url: str) -> str:
    text = (url or "").strip()
    if text.startswith("//"):
        text = "https:" + text
    if text.startswith("/"):
        text = urljoin(page_url or "https://mp.weixin.qq.com/", text)
    return text


def _guess_ext(url: str, content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _EXT_BY_CT and _EXT_BY_CT[ct]:
        return _EXT_BY_CT[ct]
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp4", ".mp3", ".m4a", ".webm"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if ct.startswith("image/"):
        return ".jpg"
    if ct.startswith("video/"):
        return ".mp4"
    if ct.startswith("audio/"):
        return ".mp3"
    return ".bin"


def _kind_for_ext(ext: str) -> str:
    e = ext.lower()
    if e in {".mp4", ".webm"}:
        return "video"
    if e in {".mp3", ".m4a", ".wav"}:
        return "audio"
    if e in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return "image"
    return "file"


def download_media_file(
    url: str,
    *,
    dest: Path,
    settings: Settings | None = None,
    max_bytes: int = _MAX_AV_BYTES,
    timeout: float = 60.0,
) -> tuple[bool, str, str]:
    """Download one media URL. Returns (ok, content_type, error)."""
    s = settings or get_settings()
    force_proxy: bool | None
    if s.network_mode == NetworkMode.PROXY:
        force_proxy = True
    elif s.network_mode == NetworkMode.DIRECT:
        force_proxy = False
    else:
        force_proxy = None
    try:
        with build_http_client(
            s, timeout=timeout, force_proxy=force_proxy, headers=_DOWNLOAD_HEADERS
        ) as client:
            with client.stream("GET", url) as resp:
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                cl = resp.headers.get("content-length")
                if cl and cl.isdigit() and int(cl) > max_bytes:
                    return False, ct, f"文件过大 ({cl} bytes)"
                dest.parent.mkdir(parents=True, exist_ok=True)
                size = 0
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(64 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            fh.close()
                            dest.unlink(missing_ok=True)
                            return False, ct, "文件过大"
                        fh.write(chunk)
                return True, ct, ""
    except Exception as exc:  # noqa: BLE001
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False, "", str(exc)[:180]


def localize_article_html(
    html: str,
    *,
    item_id: UUID | str,
    page_url: str = "https://mp.weixin.qq.com/",
    settings: Settings | None = None,
    max_assets: int = 40,
) -> tuple[str, dict[str, Any]]:
    """Rewrite remote media URLs to local API paths; download files under data/wechat_mp."""
    s = settings or get_settings()
    out_dir = item_media_dir(item_id, s)
    assets: list[dict[str, Any]] = []
    url_map: dict[str, str] = {}
    skipped: list[str] = []

    matches = list(_SRC_RE.finditer(html or ""))
    for m in matches:
        if len(url_map) >= max_assets:
            break
        raw = m.group("url")
        abs_url = _normalize_url(raw, page_url=page_url)
        if abs_url in url_map:
            continue
        # Already rewritten to local API — skip re-download
        if raw.startswith("/api/wechat/") or "/api/wechat/articles/" in abs_url:
            continue
        if not _is_downloadable_url(abs_url):
            continue
        digest = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:16]
        # temp name until we know content-type
        tmp = out_dir / f"{digest}.part"
        is_image_hint = any(
            x in abs_url.lower() for x in (".jpg", ".jpeg", ".png", ".gif", ".webp", "qpic.cn")
        )
        max_bytes = _MAX_IMAGE_BYTES if is_image_hint else _MAX_AV_BYTES
        timeout = 45.0 if is_image_hint else 120.0
        ok, ct, err = download_media_file(
            abs_url, dest=tmp, settings=s, max_bytes=max_bytes, timeout=timeout
        )
        if not ok:
            skipped.append(f"{abs_url[:80]}… ({err})" if len(abs_url) > 80 else f"{abs_url} ({err})")
            continue
        ext = _guess_ext(abs_url, ct)
        final = out_dir / f"{digest}{ext}"
        if final.exists():
            final.unlink()
        tmp.rename(final)
        local_url = f"/api/wechat/articles/{item_id}/media/{final.name}"
        url_map[abs_url] = local_url
        # also map original relative / protocol-relative forms
        url_map[raw] = local_url
        if raw.startswith("//"):
            url_map["https:" + raw] = local_url
            url_map["http:" + raw] = local_url
        assets.append(
            {
                "source": abs_url,
                "file": final.name,
                "kind": _kind_for_ext(ext),
                "bytes": final.stat().st_size if final.is_file() else 0,
            }
        )

    def _repl(m: re.Match[str]) -> str:
        raw = m.group("url")
        abs_url = _normalize_url(raw, page_url=page_url)
        local = url_map.get(raw) or url_map.get(abs_url)
        if not local:
            return m.group(0)
        # Always emit src= for browsers (data-src alone won't display)
        attr = m.group("prefix")
        if "data-src" in attr.lower():
            return f'src="{local}"'
        return f"{m.group('prefix')}{local}{m.group('suffix')}"

    rewritten = _SRC_RE.sub(_repl, html or "")
    # Ensure img that only had data-src rewritten still work; also drop empty src leftovers
    return rewritten, {
        "localized": True,
        "asset_count": len(assets),
        "assets": assets,
        "skipped": skipped[:12],
    }
