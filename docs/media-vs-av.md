# 自媒体 vs 音视频：职责分离与富媒体链路

Bagel 列表页可以只靠元数据/摘要；**汇总（周/月报）需要可阅读正文**。视频类用 MediaCrawler 发现 + yt-dlp 提文稿。

## 对照表

| | **自媒体 `/media`** | **音视频 `/av`** |
|---|---|---|
| 底层 | MediaCrawler | yt-dlp（元数据 / 下载 / 字幕） |
| 输入 | 关键词 × 平台矩阵（含抖音） | UP/频道/播放列表 URL |
| 默认采集 | 标题 / 正文摘要 / 链接 | 元数据（标题、时长、封面、链接） |
| 可选富输出 | 评论 / 子评论 / MC 本地下载媒体（`.env`，**默认关**） | 用户按需下载 + 提取字幕 / 「下载并解析文稿」 |
| 汇总用文稿 | 「提取文稿」→ yt-dlp 字幕写入 `content` | 详情页字幕或汇总前自动充实 |

## 配置（系统设置 → 配置，或 `.env`）

| 键 | 默认 | 含义 |
|----|------|------|
| `MEDIA_CRAWLER_GET_COMMENTS` | `false` | MediaCrawler 拉评论 |
| `MEDIA_CRAWLER_GET_SUB_COMMENTS` | `false` | 子评论（需开评论） |
| `MEDIA_CRAWLER_GET_MEDIAS` | `false` | MediaCrawler 本地下载图/视频（重、易风控；学习场景优先 yt-dlp） |
| `BRIEF_AUTO_ENRICH_MEDIA` | `true` | 生成自媒体/音视频汇总前，自动对缺正文的视频条目提字幕 |
| `BRIEF_ENRICH_MAX_ITEMS` | `8` | 单次汇总自动提文稿上限 |

## 抖音推荐路径（只走自媒体）

```
/media 勾选「抖音」+ 关键词
        │  MediaCrawler 搜索（综合排序）
        ▼
   MEDIA_POST（标题 / 简介 / 链接）
        │
        ├─ 「提取文稿」──► yt-dlp 字幕 → content（常缺字幕）
        ├─ 「加入音视频学习」──► /av 详情可下载 / 再提字幕
        └─ 自媒体周/月报 ──► 优先 content；无文稿则用简介；可自动 enrich
```

**抖音下载 / 解析文稿 Cookie（必做）**

yt-dlp 对抖音会报 `Fresh cookies (not necessarily logged in) are needed`，需要浏览器里有**最近访问过** douyin.com 的 Cookie：

1. 用 **Edge** 打开 https://www.douyin.com ，随便刷几条（可不登录账号）
2. `.env`：`AV_COOKIES_FROM_BROWSER=edge`（或 `chrome`）
3. **关闭**该浏览器后再点「下载」/「下载并解析文稿」（否则 Cookie 库常被锁）
4. 或用浏览器扩展导出 `cookies.txt`，设置 `AV_COOKIES_FILE=相对或绝对路径`

说明：自媒体扫码登录的是 MediaCrawler 自己的浏览器配置，**不会自动**给 yt-dlp 用；两边 Cookie 要分开准备。

**抖音「有字」但提不出文稿？**

实测该链路：

1. `yt-dlp --list-subs` → `has no subtitles`（平台无 soft CC）
2. 本地下载的 mp4：`ffprobe` 只有 **video + audio**，无 subtitle stream
3. 画面底部白字是**烧录字幕（hardsub）**——像素画在画面上，不是可开关字幕轨

因此：

| 方式 | 能否得到图中字幕 |
|------|------------------|
| yt-dlp `--write-subs` | 否 |
| 从本地 mp4 demux 字幕轨 | 否（文件里没有） |
| 作者简介 / description | 不是画面字幕，只是文案 |
| **本地音轨 ASR** | 是（口播≈烧录字） |
| 画面 OCR | 理论上可以，尚未接入 |

Bagel 文稿顺序：**平台 CC → 本地 soft-sub → 本地 ASR**。  
作者简介回退默认关闭（`AV_FALLBACK_AUTHOR_DESC=false`）。

ASR 配置：

```env
AV_ASR_ENABLED=true
AV_ASR_BACKEND=auto          # auto | volcengine | openai | faster_whisper | off
AV_ASR_LANGUAGE=zh
# 火山引擎 openspeech / 豆包语音（系统设置→配置→音视频ASR）
VOLC_ASR_API_KEY=            # 新版控制台 X-Api-Key
# 或旧版：
VOLC_ASR_APP_ID=
VOLC_ASR_ACCESS_KEY=
VOLC_ASR_MODE=auto           # 短音频 flash，长音频 submit/query
VOLC_ASR_POLL_TIMEOUT_SEC=900
```

`auto` 顺序：**openspeech（若已配置）→ OpenAI Whisper → faster-whisper**。  
走官方录音文件识别（[任务提交](https://docs.volcengine.com/docs/6561/1354868) / [查询](https://docs.volcengine.com/docs/6561/2606792)），含重试与超时；失败自动降级。

| 字段 | 含义 |
|------|------|
| `VOLC_ASR_APP_ID` + `VOLC_ASR_ACCESS_KEY` | 豆包语音**旧版**控制台 → `X-Api-App-Key` / `X-Api-Access-Key`（推荐） |
| `VOLC_ASR_API_KEY` | **新版**控制台 → `X-Api-Key`（与上一组二选一） |
| `VOLC_ASR_RESOURCE_ID` | 默认 `volc.seedasr.auc`（录音文件识别 2.0） |
| `VOLC_ASR_MODE` | `auto`（短音频 flash）/ `async` / `flash` |

实现：`integrations/volc_asr.py`（endpoint 均为 `openspeech.bytedance.com`）；编排：`integrations/av_transcript.py`；任务：`jobs/av.py`（`download_av` / `extract_av_subtitles`）。用户在设置页填写的密钥经 `settings_for_user` overlay 注入后台任务。

订阅型长视频（李沐 / 课程 UP）直接在 **音视频数据源** 配置 `av:bilibili:mid:…`。
自定义 `https://` / `av:` 源会被保留，不会被 repair 清掉。

B 站 Cookie/412 不稳时，先用内置 **验通·直链样片（免 Cookie）** 验证下载与进度透出，再配 B 站。见 [default-av-sources.md](./default-av-sources.md)。

## 运维速查

```bash
uv run bagel setup-ytdlp          # 本机克隆 yt-dlp
# 系统设置 → 音视频数据源：增删 UP / 频道
# /av → 采集元数据 → 详情页「下载」/「提取文稿」
```

| 现象 | 处理 |
|------|------|
| 抖音 Fresh cookies | Edge 打开 douyin.com，关浏览器，`AV_COOKIES_FROM_BROWSER=edge` |
| B 站 HTTP 412 | 同上换 bilibili.com；或先用验通样片 |
| `Invalid X-Api-Key` | 用豆包语音 APP ID+Token / 新版 API Key，不要填方舟 LLM `ark-` 密钥 |
| Whisper 远程断开 | 配 openspeech，或本机 `faster-whisper` |
| 进度条不动 | 看任务详情 / 控制台 `bagel.ytdlp`、`bagel.volc_asr` 日志 |

## 其它资源 Tab（新闻 / 论文 / …）

- **列表**：元数据 + 摘要即可，点进原文。
- **汇总**：已有 RSS/摘要/论文 abstract 的继续用之；**只有视频平台**需要 yt-dlp 文稿链路。
- MediaCrawler 的 `GET_MEDIAS` 不是汇总主路径；磁盘占用与风控成本高。

## 相关文档

- [user-config-media-wechat.md](./user-config-media-wechat.md)
- [git-and-ytdlp.md](./git-and-ytdlp.md)
- [default-av-sources.md](./default-av-sources.md)
- [storage.md](./storage.md)（`data/av/` 布局）
- [capabilities.md](./capabilities.md)
