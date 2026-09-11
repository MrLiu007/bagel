# third_party/

Bagel **does not vendor** heavy third-party tools — they are cloned locally at runtime（保持仓库体积小、避免 submodule 事故）。

| Path | In git? | Purpose | Docs |
|------|---------|---------|------|
| `patches/bagel_entry.py` | Yes | MediaCrawler entry shim | — |
| `MediaCrawler/` | **No** | 自媒体爬虫 | [git-and-mediacrawler.md](../docs/git-and-mediacrawler.md) |
| `yt-dlp/` | **No** | 音视频元数据 / 下载 / 字幕 | [git-and-ytdlp.md](../docs/git-and-ytdlp.md) |
| `archify/` | **No** | GitHub 学习架构图（需 Node ≥ 18） | [github-learn.md](../docs/github-learn.md) |

```bash
uv run bagel setup-media
uv run bagel setup-ytdlp
uv run bagel setup-archify   # 失败恢复；日常由 bagel dev 自动 ensure
```

## MediaCrawler

当 `ENABLE_MEDIA_CRAWLER=true` 且 `MEDIA_CRAWLER_AUTO_SETUP=true` 时，启动会在缺失时 clone 一次。

```env
ENABLE_MEDIA_CRAWLER=true
MEDIA_CRAWLER_AUTO_SETUP=true
MEDIA_CRAWLER_PATH=./third_party/MediaCrawler
MEDIA_CRAWLER_GIT_URL=          # 可选镜像
```

上游多为**非商用学习许可**，再分发时请遵守其条款。大陆网络常需代理或镜像。

## yt-dlp

```env
ENABLE_YTDLP=true
YTDLP_AUTO_SETUP=true
YTDLP_PATH=./third_party/yt-dlp
YTDLP_GIT_REF=2026.08.19
```

可选：系统安装 **ffmpeg**。B 站 / 抖音下载 Cookie 见 [media-vs-av.md](../docs/media-vs-av.md)。

## Archify

```env
ENABLE_ARCHIFY=true
ARCHIFY_AUTO_SETUP=true
ARCHIFY_PATH=./third_party/archify
ARCHIFY_GIT_REF=main
```

`bagel dev` 会 ensure；仅当自动失败时再跑 `setup-archify`。详见 [archify-and-github-briefs.md](../docs/archify-and-github-briefs.md)。
