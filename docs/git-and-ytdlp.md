# Git 提交与 yt-dlp（体积 / VPN）

> Bagel 仓库**不包含** yt-dlp 源码，以保持工程小、避免 submodule 提交失败。

---

## 1. 正确状态

`.gitignore` 已包含：

```gitignore
third_party/yt-dlp/
```

**正确状态 = 本地可有 yt-dlp，但绝不能进 Bagel 的 git 索引。**

若误 `git add` 带 `.git` 的目录，会出现与 MediaCrawler 相同的 submodule 报错。修复：

```bash
git rm -r --cached -f third_party/yt-dlp
git check-ignore -v third_party/yt-dlp
git ls-files third_party
# 只应出现 README.md 与 patches/（若有）
```

详见 [git-and-mediacrawler.md](./git-and-mediacrawler.md)。

---

## 2. 安装

```bash
uv run bagel setup-ytdlp
```

默认 clone `https://github.com/yt-dlp/yt-dlp.git`，pin tag `2026.08.19`（可在 `.env` 改 `YTDLP_GIT_REF`）。

启动时若 `ENABLE_YTDLP=true` 且 `YTDLP_AUTO_SETUP=true`，缺失时会自动 clone + 建 venv。

升级已有 checkout：

```bash
uv run bagel setup-ytdlp --ref 2026.08.19
```

B 站单视频下载若报 **HTTP 412**：先在 Edge 打开 bilibili.com，设置 `AV_COOKIES_FROM_BROWSER=edge`，再重试「下载音视频」。

---

## 3. 配置（`.env`）

```env
ENABLE_YTDLP=true
YTDLP_PATH=./third_party/yt-dlp
YTDLP_AUTO_SETUP=true
YTDLP_GIT_URL=
YTDLP_GIT_REF=2026.08.19
AV_MAX_ITEMS_PER_SOURCE=30
AV_DEFAULT_AUDIO_ONLY=true
FFMPEG_PATH=
```

可选：系统安装 **ffmpeg** 用于合并分片 / 转码。

B 站下载需浏览器 Cookie（防 412）：`AV_COOKIES_FROM_BROWSER=edge`，并在该浏览器先打开 bilibili.com。

下载/采集时控制台会打出 `bagel.ytdlp` 日志；详情页轮询任务 API 会显示进度百分比与最近日志行。

快速验证（免 Cookie）：内置「验通·直链样片」源，见 [default-av-sources.md](./default-av-sources.md)。

无 soft CC 时的文稿 / ASR（openspeech）：见 [media-vs-av.md](./media-vs-av.md)。

---

## 4. 与 MediaCrawler 对比

| | MediaCrawler | yt-dlp |
|---|-------------|--------|
| 路径 | `third_party/MediaCrawler` | `third_party/yt-dlp` |
| 命令 | `bagel setup-media` | `bagel setup-ytdlp` |
| 额外依赖 | Playwright Chromium | ffmpeg（可选）；ASR 另配 openspeech |
| 产品 Tab | `/media` 自媒体 | `/av` 音视频 |
| 汇总角色 | 发现帖子元数据 | 下载 + 字幕/ASR 写 `content` |
