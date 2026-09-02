# 兴趣过滤与各类型关键词（Filter Tags）

Bagel 按**资源类目**管理关键词，避免全局 INCLUDE 误伤自媒体 / 微信。

## 交互一览

| 类型 | 在哪里配置 | 作用 |
|------|------------|------|
| **兴趣标签 INCLUDE** | 系统设置 → 新闻 / GitHub / 股票 / 论文 / 模型 / **教育** 各数据源页 | 有启用标签时，标题/摘要须命中至少一个才进候选；支持添加、删除、启停 |
| **系统排除词 EXCLUDE** | 系统设置 → **系统排除词** | 命中则拒绝入库；可多选适用类目（新闻、GitHub、股票、论文、模型、教育、自媒体、微信）；支持添加、删除、启停、改类目 |
| **自媒体拉取词** | `.env` / 配置页 `MEDIA_CRAWLER_KEYWORDS`，或自媒体页表单 | 决定去哪些平台搜什么；入库后再套该类目 EXCLUDE |
| **微信拉取词** | `.env` `GEWE_KEYWORDS` | 回调须命中才入库；再套微信类目 EXCLUDE |

## 兴趣标签（INCLUDE）

1. 打开对应数据源页（如 **新闻数据源**）。
2. 在「兴趣标签」中添加 `LLM`、`Agent` 等，可启停或删除。
3. 同一关键词若在多个类目都需要，可在各页分别添加（会合并到同一规则的 `scopes`）。
4. **删光某类目下全部 INCLUDE** = 该类目不过兴趣门禁（仍受排除词约束）。
5. 默认种子仅挂在**新闻**，并已去掉语义重复项（如 `AI Agent`/`Agent`、`大语言模型`/`大模型`、`GPT`/`LLM`）。

自媒体 / 微信**不提供** INCLUDE UI（用各自拉取关键词）。

## 系统排除词（EXCLUDE）

独立页签，默认四词：`培训招生`、`荐股`、`付费课程`、`娱乐八卦`，默认适用全部八类目（含教育）。  
可按词勾选类目并保存；停用后不再参与过滤。

## BOOST

种子 BOOST（如 `GraphRAG`）只加分、不门禁；无单独 UI。

## 关键词自增长（定时）

在 **系统设置 → 定时任务** 勾选「定时扩展兴趣标签 / 系统排除词」后，每日根据：

- 个人空间 / 飞书 **搜索日志**（`intel_search_event`）
- `REJECTED` 条目标题中的敏感片段

自动补充 **兴趣标签 INCLUDE** 与 **系统排除词 EXCLUDE**。详见 [briefs-dashboard.md](./briefs-dashboard.md)。

## 代码入口

- 规则表：`intel_keyword_rule.scopes`（CSV，见迁移 `0004_keyword_scopes`）
- 作用域解析：`bagel.pipeline.keyword_scopes`
- 匹配：`bagel.pipeline.filter.apply_keyword_rules`
- 各 job 按 `KeywordScope` 取规则：`news` / `github` / `stocks` / `papers` / `models` / `media` / `wechat`
