# GitHub 项目页文案（About / Topics）

维护仓库「About」与 Topics 时复制下列文案。写法参考 OpenClaw（一句价值主张 + 场景）与 Hermes Agent（自我改进叙事 + 可运行性），并贴合 Bagel 产品：本地优先、多渠道情报、一张 Web、飞书触达。

## About · Description（≤ 350 字符，建议英文）

**推荐（EN，首屏检索友好）：**

```text
Self-hosted AI intel hub: collect news · GitHub · papers · models · media into one DB, review in a Web UI, digest to Feishu. SQLite by default. MIT.
```

**备选（中英混合，面向国内读者）：**

```text
Bagel（贝果）· 一人可跑的 AI 情报中枢：多源采集 · Web 审阅 · 周月汇总 · 飞书触达 · 3D 知识图谱。默认 SQLite，MIT。
```

字符数请在 GitHub 编辑框内确认（About 会截断过长描述）。

## Homepage

可选：

- 文档站或落地页（若有）
- 暂无则留空，或填 README 锚点：`https://github.com/MrLiu007/bagel#bagel--贝果`

## Topics（建议勾选）

```text
ai
intel
rss
fastapi
python
self-hosted
knowledge-graph
feishu
sqlite
llm
opensource
mit-license
```

按需增减：`arxiv` `github-api` `rsshub` `obsidian` `taxonomy`。

## Social preview

仓库 Settings → Social preview：上传一张 **暗色 GBrain 倒锥图** 或登录后新闻列表截图（1280×640 左右），比纯文字 README 更易被 Star / 分享。

## README 首屏原则（与本仓库对齐）

| 原则 | OpenClaw / Hermes 做法 | Bagel 落地 |
|------|------------------------|------------|
| 一句说清 | “Your own personal AI assistant…” | 顶部 EN + ZH tagline |
| 30 秒上手 | install / onboard | `uv sync` → `bagel doctor` → `bagel dev` |
| 卖点先于功能表 | Key features 卡片 | 「你得到什么」6 条，详表进 `docs/capabilities.md` |
| 截图克制 | 少量高信号图 | README 精选 6 张，其余见 `static/` |
| 边界清晰 | What it is / is not | 「不是什么」短列表 |
| 文档入口 | Start here | Docs 索引表 |

更新 About 后，若描述与 README 首段不一致，以本文件 EN 推荐句为准同步 README 顶部引用块。
