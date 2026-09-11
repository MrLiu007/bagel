# 新闻默认爬取数据源

种子数据见 `src/bagel/storage/seed.py` 的 `DEFAULT_SOURCES`。首次空库启动会自动写入；之后在 **系统设置 → 新闻数据源** 可增删启停。

定位：**科技 / AI / 大模型 / 机器人** 行业动态（非泛消费数码）。兴趣标签（INCLUDE）在同页配置。详见 [filter-tags.md](./filter-tags.md)。

已有库启动时会通过 `ensure_reddit_sources` / `ensure_x_sources` / `repair_news_sources` / `ensure_default_interest_keywords` 补种与修复。

## 国内（默认启用）

| 名称 | URL |
| --- | --- |
| InfoQ 中国 | https://www.infoq.cn/feed |
| Solidot | https://www.solidot.org/index.rss |
| OSCHINA | https://www.oschina.net/news/rss |
| 爱范儿 | https://www.ifanr.com/feed |

## 国内（默认关闭）

| 名称 | 说明 |
| --- | --- |
| 机器之心 / 量子位 | RSS 不可用或 403 |
| 少数派 / IT之家 / 掘金 / 博客园 | 消费数码或教程噪声，偏离 AI 焦点 |
| 36氪 | 常见空壳 / 非可用条目 |

## 海外（默认启用，建议代理）

| 名称 | URL |
| --- | --- |
| OpenAI Blog | https://openai.com/blog/rss.xml |
| Google AI Blog | https://blog.google/technology/ai/rss/ |
| DeepMind | https://deepmind.google/blog/rss.xml |
| Hugging Face Blog | https://huggingface.co/blog/feed.xml |
| Meta Engineering | https://engineering.fb.com/feed/ |
| NVIDIA Blog | https://blogs.nvidia.com/feed/ |
| Microsoft Research | https://www.microsoft.com/en-us/research/feed/ |
| AWS ML Blog | https://aws.amazon.com/blogs/machine-learning/feed/ |
| TechCrunch AI | https://techcrunch.com/category/artificial-intelligence/feed/ |
| The Verge AI | https://www.theverge.com/rss/ai-artificial-intelligence/index.xml |
| Wired AI | https://www.wired.com/feed/tag/ai/latest/rss |
| IEEE Spectrum AI | https://spectrum.ieee.org/feeds/topic/artificial-intelligence.rss |
| MIT Tech Review | https://www.technologyreview.com/feed/ |
| Ars Technica | https://feeds.arstechnica.com/arstechnica/technology-lab |
| Towards Data Science | https://towardsdatascience.com/feed |
| PyTorch Blog | https://pytorch.org/blog/feed.xml |
| LangChain Blog | https://blog.langchain.dev/rss.xml |
| Reddit r/MachineLearning | 默认启用；其余 Reddit 子版默认关闭（易 429） |

## 海外 / 适配（默认关闭）

| 名称 | 说明 |
| --- | --- |
| Anthropic（假 RSS） | PARSE_ERROR，勿启用 |
| Reddit 其它子版 / RSSHub（微博热搜、GitHub Trending、X） | 需健康 RSSHub；常见 502，设置里按需开启 |

## 采集节流

新闻任务**串行**拉源（无线程池）。环境变量：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `NEWS_SOURCE_SLEEP_SEC` | 1.5 | 普通源之间休眠 |
| `NEWS_REDDIT_SLEEP_SEC` | 8 | Reddit 源前更长休眠 |
| `NEWS_RATE_LIMIT_COOLDOWN_SEC` | 18 | 命中 429 后冷却再下一源 |
| `NEWS_SOURCE_MAX_ATTEMPTS` | 2 | 单源最大尝试（少重试减压力） |

502/网关错误不再重试；跳过该源继续。

## 兴趣标签要点

- **必须保留 `GPT`**：标题「GPT-6」不含 `LLM` / `大模型`，旧种子把 GPT 当成 LLM 重复项删掉会导致漏抓。
- `开源` 改为 **BOOST**（加分），不再做 INCLUDE 门禁。
- 拉丁短词按「词边界」匹配，避免 `ai` 误伤 `said`/`training`；`GPT` 仍可命中 `GPT-6`。

`ENABLE_OVERSEAS_SOURCES=false` 时会跳过全部 `region=GLOBAL` 源（含 Reddit / 海外博客）。抓不到海外 GPT 动态时优先检查此项与代理。
