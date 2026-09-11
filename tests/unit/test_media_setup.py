"""MediaCrawler is external — only Bagel shim / setup helpers are tested."""

from __future__ import annotations

from pathlib import Path

from bagel.services import media_setup


def test_install_entry_shim_idempotent(tmp_path: Path):
    target = tmp_path / "MediaCrawler"
    target.mkdir()
    dest = media_setup.install_entry_shim(target)
    mtime1 = dest.stat().st_mtime_ns
    dest2 = media_setup.install_entry_shim(target)
    assert dest2 == dest
    assert dest.stat().st_mtime_ns == mtime1


def test_sanitize_mediacrawler_utf8_bom(tmp_path: Path):
    root = tmp_path / "MediaCrawler"
    cv2 = root / ".venv" / "Lib" / "site-packages" / "cv2"
    cv2.mkdir(parents=True)
    bom_file = cv2 / "config.py"
    bom_file.write_bytes(b"\xef\xbb\xbfimport os\nBINARIES_PATHS = []\n")
    execjs = root / ".venv" / "Lib" / "site-packages" / "execjs"
    execjs.mkdir(parents=True)
    ex = execjs / "__init__.py"
    ex.write_bytes(b"\xef\xbb\xbf# -*- coding: ascii -*-\nx=1\n")
    proj = root / "main.py"
    proj.write_bytes(b"\xef\xbb\xbfprint(1)\n")
    clean = cv2 / "ok.py"
    clean.write_bytes(b"x = 1\n")
    n = media_setup.sanitize_mediacrawler_utf8_bom(root)
    assert n >= 3
    assert not bom_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not ex.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not proj.read_bytes().startswith(b"\xef\xbb\xbf")
    assert clean.read_bytes() == b"x = 1\n"


def test_install_entry_shim_strips_bom_from_source(tmp_path: Path, monkeypatch):
    """Even if the patch file has a BOM, the installed shim must not."""
    patch = tmp_path / "bagel_entry.py"
    patch.write_bytes(b"\xef\xbb\xbf# shim\nprint(1)\n")
    monkeypatch.setattr(media_setup, "patch_entry_src", lambda: patch)
    target = tmp_path / "MediaCrawler"
    target.mkdir()
    dest = media_setup.install_entry_shim(target)
    assert not dest.read_bytes().startswith(b"\xef\xbb\xbf")
    assert dest.read_text(encoding="utf-8").startswith("# shim")


def test_mediacrawler_dir_is_gitignored():
    root = media_setup.project_root()
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    assert "third_party/MediaCrawler/" in gi


def test_ensure_skips_when_ready(tmp_path, monkeypatch):
    target = tmp_path / "MediaCrawler"
    target.mkdir()
    (target / "main.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("MEDIA_CRAWLER_PATH", str(target))
    monkeypatch.setenv("ENABLE_MEDIA_CRAWLER", "true")
    monkeypatch.setenv("MEDIA_CRAWLER_AUTO_SETUP", "true")
    from bagel.settings import get_settings

    get_settings.cache_clear()
    info = media_setup.ensure_mediacrawler_on_startup(settings=get_settings())
    assert info is not None
    assert info["action"] == "exists"
    get_settings.cache_clear()


def test_vpn_hint_constant():
    assert "VPN" in media_setup.VPN_HINT or "vpn" in media_setup.VPN_HINT.lower()
    assert "GitHub" in media_setup.VPN_HINT or "github" in media_setup.VPN_HINT.lower()
