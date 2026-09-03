# Bagel · 贝果

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.14-blue.svg)](https://www.python.org/)
[![uv](https://img.shields.io/badge/packaging-uv-de5fe9.svg)](https://github.com/astral-sh/uv)
[![FastAPI](https://img.shields.io/badge/Web-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)

> **Self-hosted AI intel hub** — collect news · GitHub · papers · models · media into one DB, review in a Web UI, digest to Feishu. SQLite by default. MIT.
>
> **Bagel（贝果）**：一个人也能跑起来的 AI 情报中枢 —— 采集 · 审阅 · 汇总 · 飞书触达 · 3D 知识图谱。

一个 Python 工程 · 一份 `.env` · 可选 Compose · 一个 Web 入口。  
用户只访问 **http://localhost:8000**，无需理解 FreshRSS / RSSHub / PostgreSQL。

---

## 为什么是 Bagel

情报散落在 RSS、GitHub、arXiv、Hugging Face、自媒体和微信里；人工刷流既慢又漏。  
Bagel 把多源采集归一成同一套 `IntelItem`，用 Web 审阅 + 周月汇总 + 飞书推送闭环；可选编译 Wiki，在个人空间用 **GBrain** 一张 3D 图把「资源 ↔ 主题」串起来。

| 你要的 | Bagel 怎么做 |
|--------|----------------|
| 本地可控 | 默认 SQLite；数据在你机器上 |
| 少组件 | 单进程 FastAPI；FreshRSS/RSSHub 仅作隐藏基建 |
| 国内可用 | 海外源失败不阻断国内采集；代理可选 |
| 触达现场 | 飞书指令查询 + 定时摘要推送 |
| 看得懂关联 | Taxonomy + Wiki + 资源优先的 3D 图谱 |

**不是什么：** 不是托管 SaaS、不是荐股产品、不是向量库/RAG 全家桶（Wiki MD 可给 Obsidian/RAG，**不能替代**事务库）。

---

## 你得到什么

- **多渠道采集** — 新闻 / GitHub / 论文 / 教育 / 模型 / 股票 / 自媒体 / 微信，统一入库与去重  
- **Web 审阅台** — 列表、收藏、兴趣标签、关联侧栏；明暗主题  
- **周月汇总** — 可自定义提示词；可选 LLM 润色  
- **飞书双场景** — 自然语言查库 + 定时推送  
- **个人空间** — 看板统计 + 全幅 **GBrain**（倒锥 3D、SUBJECTS 八频道、摘要+原文知识卡）  
- **Wiki 编译** — Markdown 正文 + DB 索引；taxonomy 结构可扩展  

完整能力表见 **[docs/capabilities.md](./docs/capabilities.md)**。

---

## 最快上手（约 1 分钟）

```bash
git clone https://github.com/MrLiu007/bagel.git
cd bagel
cp .env.example .env
uv sync
uv run bagel doctor
uv run bagel dev --host 127.0.0.1 --port 8000 --reload
```

打开 **http://127.0.0.1:8000**。默认 **SQLite**（`data/bagel.db`），无需 Docker。

| 命令 | 作用 |
|------|------|
| `bagel doctor` | 环境与依赖健康检查 |
| `bagel dev` | 开发启动 Web（可自动拉取 MediaCrawler） |
| `bagel setup-media` | 手动克隆自媒体依赖到 `third_party/`（gitignore） |
| `bagel cli …` | 飞书 send / digest / ask |

生产或无 reload：`uv run bagel dev --host 0.0.0.0 --port 8000 --no-reload`

**自媒体 / MediaCrawler：** 源码不进 git；首次需要时自动 clone（海外网络可能需代理或镜像 URL）。详见 [docs/git-and-mediacrawler.md](./docs/git-and-mediacrawler.md)。

---

## 截图

| 登录 | 新闻 | GitHub |
|:---:|:---:|:---:|
| ![登录](./static/0.登录.png) | ![新闻](./static/1.new.png) | ![GitHub](./static/2.github项目.png) |

| 论文 | 汇总 | 关联 |
|:---:|:---:|:---:|
| ![论文](./static/3.art.png) | ![汇总](./static/7.汇总.png) | ![关联](./static/19.新闻&论文&项目&自媒体等关联依赖信息.png) |

更多界面（股票 / 自媒体 / 微信 / 设置 / 采集等）见仓库 [`static/`](./static/) 目录。

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/capabilities.md](./docs/capabilities.md) | **能力全景归档**、入口速查、验收清单 |
| [docs/github-presence.md](./docs/github-presence.md) | **GitHub About / Topics** 推荐文案 |
| [AGENTS.md](./AGENTS.md) | 开发约束 |
| [docs/architecture.md](./docs/architecture.md) | 架构原则与包结构 |
| [docs/wiki-taxonomy-gbrain.md](./docs/wiki-taxonomy-gbrain.md) | Wiki · Taxonomy · GBrain（含图谱 UX） |
| [docs/briefs-dashboard.md](./docs/briefs-dashboard.md) | 个人空间、关联侧栏、学习 API |
| [docs/storage.md](./docs/storage.md) | SQLite / Postgres / Wiki |
| [docs/data-model.md](./docs/data-model.md) | 数据模型 |
| [docs/network.md](./docs/network.md) | 网络与代理 |
| [docs/filter-tags.md](./docs/filter-tags.md) | 兴趣标签与排除词 |
| [docs/default-news-sources.md](./docs/default-news-sources.md) | 默认新闻源 |
| [docs/git-and-mediacrawler.md](./docs/git-and-mediacrawler.md) | MediaCrawler 与 git |
| [docs/user-config-media-wechat.md](./docs/user-config-media-wechat.md) | 自媒体 + 微信 |

---

## 代理（国内网络）

```env
NETWORK_MODE=AUTO
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
```

海外源 / GitHub 不可达时：国内新闻继续；`bagel doctor` 与设置页显示降级告警。详见 [docs/network.md](./docs/network.md)。

---

## Docker Compose（可选）

适合一次拉起 **Bagel + Postgres + RSSHub + FreshRSS**（后两者默认不对公网暴露）。

```bash
cp .env.example .env   # 至少改 SESSION_SECRET
docker compose up -d --build
```

浏览器打开 **http://localhost:8000**（端口可用 `APP_PORT` 覆盖）。

本地开发仍推荐 `uv run bagel dev` + SQLite。Compose 变量、代理、排障见下方要点：

- Compose 覆盖 `STORAGE_BACKEND=postgres` 与容器内 `DATABASE_URL` / RSSHub / FreshRSS  
- 镜像入口对 Postgres 跑 `alembic upgrade head`；SQLite 由 `init_db` 建表  
- MediaCrawler **不进镜像**；自媒体请在宿主机 `bagel setup-media` 或挂载本机目录  
- 拉取基础镜像超时：配置 Docker Hub 镜像或代理后再试  

---

## 开源与致谢

- **协议**：[MIT](./LICENSE) — 宽松、易二次分发与商用改造  
- **品牌**：英文 **Bagel**，中文 **贝果**；包名 / CLI / 默认库文件均为 `bagel`  
- **免责**：股票相关能力仅供信息整理，**不构成投资建议**  
- 从旧版升级：默认库由 `data/intel.db` 改为 `data/bagel.db`（可改名或在 `.env` 继续指向旧路径）

站在开源肩膀上（许可证归原作者；**不 fork** FreshRSS / RSSHub）：

| 依赖 | 用途 |
|------|------|
| FastAPI · Uvicorn · SQLAlchemy · Alembic · uv | Web / ORM / 包管理 |
| [RSSHub](https://github.com/DIYgod/RSSHub) · [FreshRSS](https://github.com/FreshRSS/FreshRSS) | 隐藏 RSS 基建（Compose 可选） |
| [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | 自媒体（本机克隆，不进 git） |
| 3d-force-graph | 个人空间 GBrain 可视化 |

欢迎 Issue / PR。推广时请同步 GitHub **About** / Topics：见 **[docs/github-presence.md](./docs/github-presence.md)**。
