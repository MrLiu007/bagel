# third_party/

Bagel **does not vendor** heavy third-party tools — they are cloned locally at runtime（保持仓库体积小、避免 submodule 事故）。

| Path | In git? | Purpose | Docs |
|------|---------|---------|------|
| `patches/bagel_entry.py` | Yes | MediaCrawler entry shim | — |
| `MediaCrawler/` | **No** | 自媒体爬虫 | [git-and-mediacrawler.md](../docs/git-and-mediacrawler.md) |
| `yt-dlp/` | **No** | 音视频元数据 / 下载 / 字幕 | [git-and-ytdlp.md](../docs/git-and-ytdlp.md) |
| `archify/` | **No** | GitHub 学习架构图（需 Node ≥ 18） | [github-learn.md](../docs/github-learn.md) |
| `wewe-rss/` | **No** | 微信公众号近期文章（WeWe） | [wewe-rss-integration.md](../docs/wewe-rss-integration.md) |

```bash
uv run bagel setup-media
uv run bagel setup-ytdlp
uv run bagel setup-archify   # 失败恢复；日常由 bagel dev 自动 ensure
uv run bagel setup-wewe      # 失败恢复；日常由 bagel dev 自动 clone + 启动
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

## WeWe-RSS

公众号**近期文章**来源。源码不入库；`bagel dev` 会：

1. 缺失时 `git clone` → `third_party/wewe-rss/`
2. **优先 Docker** 启动 `cooderl/wewe-rss-sqlite`（容器名 `bagel-wewe-rss`，端口默认 4000）
3. 无 Docker 时再尝试本地 Node ≥ 20 + pnpm（首次构建较慢）

```env
ENABLE_WEWE_RSS=true
WEWE_RSS_AUTO_SETUP=true
WEWE_RSS_AUTO_START=true
WEWE_RSS_PATH=./third_party/wewe-rss
WEWE_RSS_PORT=4000
WEWE_RSS_BASE_URL=          # 留空 → 自动 http://127.0.0.1:4000
WEWE_RSS_AUTH_CODE=bagel-wewe
WEWE_RSS_RUNTIME=auto       # auto | docker | local | off
```

首次使用：打开 `http://127.0.0.1:4000`，微信读书扫码，用样例文章链接添加公众号；再回 Bagel「微信 → 公众号」订阅采集。
