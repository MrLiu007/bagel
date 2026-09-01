# Git 提交与 MediaCrawler（体积 / VPN）

> Bagel 仓库**不包含** MediaCrawler 源码，以保持工程小、避免 submodule 提交失败。

---

## 1. 图中报错是什么？

若曾执行 `git add .`，且本地存在 `third_party/MediaCrawler/`（自带 `.git`），Git 会把它记成 **submodule gitlink**（mode `160000`）。没有 `.gitmodules` 时提交会失败：

```text
fatal: no submodule mapping found in .gitmodules for path 'third_party/MediaCrawler'
```

当前 `.gitignore` 已包含：

```gitignore
third_party/MediaCrawler/
```

因此：**正确状态 = 本地可有 MediaCrawler，但绝不能进 Bagel 的 git 索引。**

---

## 2. 已经 `git add .` 之后怎么修？

在 **bagel** 仓库根目录执行：

```bash
# 1) 从索引移除（不删本机文件）
git rm -r --cached -f third_party/MediaCrawler

# 2) 确认忽略规则在
git check-ignore -v third_party/MediaCrawler
# 应看到：.gitignore:… third_party/MediaCrawler/

# 3) 顺带清掉不该提交的缓存（若曾被 add）
git rm -r --cached -f data 2>nul
git ls-files | findstr /i "__pycache__ .pyc" 
# 若有输出，逐个：git rm --cached -f <path>

# 4) 重新只加应跟踪的文件
git add .gitignore third_party/README.md third_party/patches/
git add src docs tests migrations static LICENSE README.md pyproject.toml AGENTS.md .env.example

# 5) 确认索引里没有 MediaCrawler
git ls-files third_party
# 只应出现：third_party/README.md 与 third_party/patches/bagel_entry.py

# 6) 再提交
git status
git commit -m "Initial Bagel release without vendoring MediaCrawler"
```

**不要**再执行会重新 add 掉忽略目录的奇怪操作；正常 `git add .` 在 ignore 生效后**不会**再加入 `MediaCrawler/`。

若 `git status` 仍把 `third_party/MediaCrawler` 显示为 submodule / deleted submodule，执行上面的 `git rm --cached -f` 即可。

---

## 3. 启动时会不会下载 MediaCrawler？

**会（默认）。** 当满足：

- `ENABLE_MEDIA_CRAWLER=true`（默认开），且  
- `MEDIA_CRAWLER_AUTO_SETUP=true`（默认开），且  
- `MEDIA_CRAWLER_PATH` 下还没有可用源码（缺少 `main.py`）

则 `bagel dev` / 应用 lifespan **启动时会自动 `git clone --depth 1`** 到本机 `third_party/MediaCrawler/`（gitignore，不进仓库）。

| 行为 | 说明 |
|------|------|
| 仓库体积 | 小：只跟踪 `third_party/patches/bagel_entry.py` + README |
| 本机磁盘 | 首次启动后会多一份 MediaCrawler 克隆 |
| 已存在目录 | **不会**每次启动重复下载，仅补拷贝 `bagel_entry.py` |
| 关闭自动拉取 | `.env`：`MEDIA_CRAWLER_AUTO_SETUP=false`，改为手动 `bagel setup-media` |
| 能抓取？ | 克隆 ≠ 可跑。还需在 MediaCrawler 目录装其 `.venv` / Playwright（见下游文档） |

手动：

```bash
uv run bagel setup-media
```

---

## 4. 下载会不会受海外网络影响？要不要 VPN？

**会。** 默认地址是 GitHub：

`https://github.com/NanmiCoder/MediaCrawler.git`

国内直连常出现超时 / `Failed to connect` / `SSL` 错误。

| 方案 | 做法 |
|------|------|
| VPN / 系统代理 | 开启后，让 **运行 bagel 的同一终端** 能访问 GitHub；必要时设 `HTTPS_PROXY` / `HTTP_PROXY` |
| 镜像 URL | `.env` 设置 `MEDIA_CRAWLER_GIT_URL=<你的镜像 clone 地址>` 后重启或 `bagel setup-media --repo ...` |
| 关闭媒体 | `ENABLE_MEDIA_CRAWLER=false`，启动不再尝试 clone |

失败时日志会带提示（不阻断 Bagel 主站启动）：新闻 / GitHub 等其它功能仍可用。

Playwright 浏览器内核下载同样可能受网络影响，需在 MediaCrawler 自己的环境中处理（可走镜像或代理）。

---

## 5. `bagel dev --reload` 一直 Reloading？

若控制台反复出现：

```text
WatchFiles detected changes in 'third_party\MediaCrawler\bagel_entry.py'. Reloading...
```

原因：启动时安装入口 shim 会写该文件，而热重载监视了整个仓库 → 写文件 → 重启 → 再写 → 循环。站点仍可访问，但日志刷屏。

当前版本已修复：

1. shim **内容未变则不写盘**（不碰 mtime）  
2. `bagel dev` 的 `reload_excludes` 排除 `third_party/MediaCrawler` 与 `data/`

请更新代码后重新执行 `uv run bagel dev --host 127.0.0.1 --port 8000 --reload`。

---

## 6. 相关配置（`.env`）

```env
ENABLE_MEDIA_CRAWLER=true
MEDIA_CRAWLER_PATH=./third_party/MediaCrawler
MEDIA_CRAWLER_AUTO_SETUP=true
# 留空 = 官方 GitHub；网络不稳时填镜像
MEDIA_CRAWLER_GIT_URL=
MEDIA_CRAWLER_GIT_REF=main
```

更多交互说明见 [user-config-media-wechat.md](./user-config-media-wechat.md) 与 [../third_party/README.md](../third_party/README.md)。
