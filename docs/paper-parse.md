# 论文 PDF 下载与文档识别

采集论文默认仍只拉 **元数据 + 摘要**。列表上：

1. 若本地已能确定 OA PDF（采集写入的 `pdf_url` / arXiv 等）→ 显示 **「下载PDF并识别」**
2. 否则先显示 **「探测开放 PDF」**（Zenodo API / 页面 `citation_pdf_url` / Unpaywall 等）；探测成功写入 `pdf_url` 后刷新，才出现下载按钮

这样避免点了下载却弹出「已识别 DOI 但无 PDF」的挫败感。

下载后流程不变：本地下载 → MinerU / Kimi 负载解析 → 写入 `content`。

## 配置（`.env`）

```env
ENABLE_PAPER_PARSE=true
PAPER_PARSE_PROVIDERS=mineru,kimi
PAPER_PARSE_STRATEGY=round_robin   # 或 failover
PAPER_PARSE_TIMEOUT_SEC=300

ENABLE_MINERU=true
MINERU_API_TOKEN=                  # https://mineru.net/apiManage/docs
MINERU_MODEL_VERSION=vlm

ENABLE_KIMI_FILES=true
KIMI_API_KEY=                      # 空则复用 moonshot 的 LLM_API_KEY
KIMI_FILES_BASE_URL=               # 默认 https://api.moonshot.cn/v1
```

也可在 **系统设置 → 配置** 的「论文」分组修改。

## 负载策略

| 策略 | 行为 |
|------|------|
| `round_robin` | 每次轮换首选后端，失败则 failover 到下一个 |
| `failover` | 始终按 `PAPER_PARSE_PROVIDERS` 顺序尝试 |

状态：`GET /api/papers/parse-status`  
触发：`POST /api/papers/parse/{item_id}`（任务 kind=`parse_paper`）

## 注意

- 国外 PDF URL 直传 MinerU 可能超时，本实现改为 **先本地下载再上传**
- 解析正文是 **原始证据**；LLM 摘要写在 `llm_*` 字段，不要互相覆盖
- 未配置任一后端 Token 时，按钮会启动任务但失败并提示配置
- PDF 地址：本地已知才显示「下载PDF并识别」；否则先「探测开放 PDF」（arXiv / HF / Zenodo / 页面 meta / Unpaywall）

## 相关

- 能力表：[capabilities.md](./capabilities.md)
- 代码：`services/paper_parse.py`、`integrations/mineru.py`、`integrations/kimi_files.py`、`web/routes/papers_api.py`
