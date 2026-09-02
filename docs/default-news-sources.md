# 新闻默认爬取数据源

种子数据见 `src/bagel/storage/seed.py` 的 `DEFAULT_SOURCES`。首次空库启动会自动写入；之后在 **系统设置 → 新闻数据源** 可增删启停。

新闻兴趣标签（INCLUDE）在 **新闻数据源** 页配置；系统排除词在独立页签，可覆盖全部类目。详见 [filter-tags.md](./filter-tags.md)。

已有库启动时会通过 `ensure_reddit_sources` / `ensure_x_sources` / `repair_news_sources` 补种与修复缺失/失效的源。

## 国内（默认启用）

| 名称 | URL | 类型 |
| --- | --- | --- |
| InfoQ 中国 | https://www.infoq.cn/feed | RSS |
| 少数派 | https://sspai.com/feed | RSS |
| Solidot | https://www.solidot.org/index.rss | RSS |
| 36氪 | https://36kr.com/feed | RSS |
| IT之家 | https://www.ithome.com/rss/ | RSS |
| OSCHINA | https://www.oschina.net/news/rss | RSS |
| 掘金后端 | https://juejin.cn/rss | RSS |
| 博客园精华 | https://feed.cnblogs.com/blog/sitehome/rss | RSS |
| 爱范儿 | https://www.ifanr.com/feed | RSS |

## 国内（默认关闭）

| 名称 | URL | 说明 |
| --- | --- | --- |
| 机器之心 | https://www.jiqizhixin.com/rss | 返回 HTML/门禁页，非可用 RSS |
| 量子位 | https://www.qbitai.com/feed | 常见 403 |

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
| The Verge AI | https://www.theverge.com/rss/ai-artificial-intelligence/index.xml |
| MIT Tech Review | https://www.technologyreview.com/feed/ |
| Ars Technica | https://feeds.arstechnica.com/arstechnica/technology-lab |
| Towards Data Science | https://towardsdatascience.com/feed |
| PyTorch Blog | https://pytorch.org/blog/feed.xml |
| LangChain Blog | https://blog.langchain.dev/rss.xml |
| Reddit r/MachineLearning | https://www.reddit.com/r/MachineLearning/new/.rss |
| Reddit r/LocalLLaMA | https://www.reddit.com/r/LocalLLaMA/new/.rss |
| Reddit r/artificial | https://www.reddit.com/r/artificial/new/.rss |
| Reddit r/LanguageTechnology | https://www.reddit.com/r/LanguageTechnology/new/.rss |

> Reddit 官方 `.rss` 需浏览器风格 User-Agent；采集层已对 `reddit.com` 等站点自动切换请求头。连续拉取仍可能偶发 **429**（限流），属上游策略，可稍后重试或临时关闭部分 Reddit 源。

## X（Twitter）via RSSHub（默认关闭）

依赖 `RSSHUB_BASE_URL`（本地或 Compose 中的 RSSHub）。路径使用 RSSHub 的 `/twitter/user/:id` 路由。未配置 Cookie / RSSHub 不健康时常见 **502**，因此默认关闭；在设置中按需启用。

| 名称 | RSSHub 路径 |
| --- | --- |
| X · OpenAI | `/twitter/user/OpenAI` |
| X · Anthropic | `/twitter/user/AnthropicAI` |
| X · Hugging Face | `/twitter/user/HuggingFace` |
| X · Andrej Karpathy | `/twitter/user/karpathy` |
| X · Andrew Ng | `/twitter/user/AndrewYNg` |
| X · DeepLearningAI | `/twitter/user/DeepLearningAI` |

## 默认关闭（可选）

| 名称 | 说明 |
| --- | --- |
| Anthropic | 种子 URL 非稳定 RSS，默认 `enabled=false` |
| 微博热搜 (RSSHub) | 依赖本地/Compose RSSHub |
| GitHub Trending (RSSHub) | 同上 |

`ENABLE_OVERSEAS_SOURCES=false` 时采集会跳过 `region=GLOBAL` 源（含 X / Reddit / 海外博客）。

## 启动时自动修复（`repair_news_sources`）

| 旧 URL | 处理 |
| --- | --- |
| `https://www.cnblogs.com/aggsite/rss` | → `https://feed.cnblogs.com/blog/sitehome/rss` |
| `https://blog.langchain.dev/rss/` | → `https://blog.langchain.dev/rss.xml` |
| `https://ai.meta.com/blog/rss/` | → `https://engineering.fb.com/feed/`（改名 Meta Engineering） |
| 机器之心 / 量子位 旧源 | 关闭（`FEED_UNRELIABLE`） |
