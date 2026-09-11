# GitHub 「学习」页（Qoder Wiki 风格 + Archify）

GitHub 项目列表每条有 **学习** 按钮 → `/github/learn/{id}`。

## 流程（懒加载）

1. **开始分析（bootstrap）**：GitHub API 拉元数据 + 目录树；**源码片段优先走 raw.githubusercontent.com**（不占 REST 额度）→ LLM 规划目录与首页 → Archify 出图  
2. **点击目录项**：若该页 `status=pending`，后台任务 `github_learn_page` 深度撰写一页并写入 `.qoder/repowiki/zh/*.md`；再次打开直接读本地，不重跑  
3. 产物目录：`data/github/learn/{item_id}/`（含 `snippets.json` 供按需页复用）  
4. 阅读页：左侧目录 + Markdown 正文；架构图默认嵌入预览，点 Archify「演示」或「全屏演示」进入浏览器全屏，Esc 退出后恢复嵌入尺寸

**GitHub 限流**：未配置 `GITHUB_TOKEN` 时匿名额度约 60 次/小时，多次「重建目录」易 403。请在 `.env` 设置 `GITHUB_TOKEN=ghp_…` 后重启。额度耗尽且本地已有证据缓存时，会尽量用缓存继续生成。

这样首屏更快，且用户未点开的模块页不消耗 LLM。

## Archify（统一由 `bagel dev` 管理）

| | |
|---|---|
| 源码 | `third_party/archify/` **gitignore** |
| 日常 | `uv run bagel dev …` 自动 ensure（`ARCHIFY_AUTO_SETUP=true`） |
| 可选 | `bagel setup-archify` 仅作失败恢复 |
| 依赖 | 本机 **Node ≥ 18** |

详见 [archify-and-github-briefs.md](./archify-and-github-briefs.md)。

## 相关

- 能力表：[capabilities.md](./capabilities.md)
- 本地产物目录：[storage.md](./storage.md)（`data/github/learn/`）
- 代码：`services/github_learn.py`、`integrations/archify.py`、`web/routes/github_learn.py`
