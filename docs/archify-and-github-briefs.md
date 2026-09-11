# Archify 与 GitHub「项目总结」

> 结论：**不适合**用 MediaCrawler / yt-dlp 同款方式接入 Archify，来替代或增强 Bagel 的 GitHub 项目文字总结。

## Archify 是什么

[tt-a1i/archify](https://github.com/tt-a1i/archify) 是 **AI Agent Skill + 确定性渲染器**：

1. Agent（Cursor / Claude Code 等）阅读需求或仓库后，写出 **typed JSON IR**
2. Archify CLI（Node）校验 IR，编译为可交互的 **HTML/SVG 架构图**

它解决的是「架构图可视化」，不是「从仓库自动生成可读项目摘要」。

## 为何不能照搬 MediaCrawler / yt-dlp 模式

| | MediaCrawler / yt-dlp | Archify |
|---|---|---|
| 运行时 | Python 爬虫 / 下载器，subprocess 即可产出数据 | Node 渲染器，**正文分析靠外部 LLM Agent** |
| 输入 | 关键词 / URL | 人工或 Agent 写好的 JSON IR |
| 输出 | 帖子 / 视频元数据与文件 | 架构图 HTML |
| 与 Bagel 汇总 | 可直接写入 `IntelItem` | 图 ≠ 周月报需要的文字总结 |

Bagel 的「汇总 · GitHub 项目」需要的是：**问题 / 方案 / 适用场景 / 与 README 互补的结构洞察**。  
Archify 不会自动读完仓库并吐出中文摘要；就算 `third_party/archify` + `.venv`（实际是 Node）克隆成功，没有 Agent 写 IR，subprocess 也几乎无事可做。

## 若仍想用图（已实现路径）

Bagel 已在 **GitHub → 学习** 页集成 Archify（`docs/github-learn.md`）：

1. LLM 根据 README/目录生成 Archify JSON IR（失败则用目录兜底 IR）
2. `third_party/archify`（gitignore）+ 由 **`bagel dev` 启动自动 ensure**（也可手动 `setup-archify` 恢复）
3. 产物 `data/github/learn/{id}/architecture.html`，阅读页 iframe 打开

学习页 Wiki 为 `github-learn-v2`：拉取关键源码片段后分阶段生成「现状能力 / 实现要点 / 扩展」文档，不再只做目录级概述。

## 更合理的 GitHub 总结增强（推荐）

在不引入 Archify 的前提下，优先：

1. **已有**：GitHub Search + Release 采集、README/description 截断摘要
2. **增量**：浅克隆或 GitHub API Tree → 语言占比、顶层目录、关键文件路径列表 → 一并喂给 LLM
3. **可选工具**：`gitingest` / 自研 tree walker（HTTP API，不必 third_party 大仓）

这样输出仍是文字，能直接进周月报，也符合 AGENTS.md「不无微服务 / 不乱加依赖」的约束。
