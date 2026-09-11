# 默认音视频数据源

启动时写入并 `repair_av_sources`：只保留下列 **验通源 + 已核对 B 站 UP**。多余源会被清理。

## URL 约定

| 前缀 | 含义 | 示例 |
|------|------|------|
| `av:bilibili:mid:{mid}` | B 站 UP 投稿 | `av:bilibili:mid:1567748478` |
| `av:youtube:channel:{handle}` | YouTube 频道 | 可在设置页手动添加 |
| `av:generic:url:{https://…}` | 任意 yt-dlp 页 / 直链 | 验通样片 |

核对 mid：打开 `https://space.bilibili.com/{mid}`。

## 内置源

### 验通（免浏览器 Cookie，优先用来验证下载链路）

| 名称 | URL | 说明 |
|------|-----|------|
| 验通·直链样片（免 Cookie） | Wikimedia Big Buck Bunny 360p 直链 | 国内一般可直连，先采后下即可 |
| 验通·Internet Archive | `archive.org/details/BigBuckBunny_328` | 海外源；需开启海外采集或代理 |

### B 站学习 UP（需 Edge Cookie，易遇 HTTP 412）

| 名称 | URL |
|------|-----|
| 跟李沐学 AI | `av:bilibili:mid:1567748478` |
| 机器之心官方 | `av:bilibili:mid:73414544` |
| 爱可可-爱生活 | `av:bilibili:mid:23852932` |
| 量子位Daily | `av:bilibili:mid:3546619041548912` |

**快速验证步骤：**

1. 重启服务（seed 会补上验通源）
2. `/av` →「采集元数据」
3. 打开「验通·直链样片」详情 →「下载音视频」
4. 看页面进度条 + 日志区；控制台应有 `[yt-dlp]` 行

YouTube / 校方公开课等请在 **系统设置 → 音视频数据源** 按需手动添加。

完整种子见 `src/bagel/storage/seed.py` → `DEFAULT_AV_SOURCES`。
