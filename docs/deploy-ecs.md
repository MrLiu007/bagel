# ECS 多容器共存部署（`/bagel` 前缀）

同机已有其它 Compose / Nginx 站点时，Bagel **不占用公网 80/443**，也不用通用容器名 `postgres` / `app`。

## 冲突规避

| 项 | 默认策略 |
| --- | --- |
| Compose 项目名 | `bagel`（`compose.yml` 顶部 `name:`） |
| 容器名 | `bagel-app` / `bagel-postgres` / `bagel-rsshub` / `bagel-freshrss` |
| 数据卷 | `bagel_postgres_data` / `bagel_freshrss_data` |
| 公网端口 | **不绑定** 80/443 |
| 应用入口 | 仅本机 `127.0.0.1:6280` → 由宿主机 Nginx 反代 |
| Postgres / RSSHub | 仅 Docker 内网，不映射宿主机端口 |

Bagel 是 **FastAPI + Jinja 单体**（无独立前端容器）。Nginx 的 `/bagel/` 同时覆盖页面与 JSON API。

## 访问方式

部署并配置 Nginx 后：

- 前端 / 业务页：`https://你的域名/bagel/`
- 健康检查：`https://你的域名/bagel/health`
- 本地直连（不经 Nginx，需改绑定）：`http://127.0.0.1:6280/`

应用已支持 `X-Forwarded-Prefix: /bagel`（或 `X-Script-Name`），链接与登录跳转会自动带前缀。

## 部署步骤

```bash
cp .env.example .env   # 至少改 SESSION_SECRET
# 可选：BAGEL_HOST_PORT=6280  BAGEL_BIND=127.0.0.1（compose 默认已是）

./docker-up.sh up -d --build
# 或：docker compose up -d --build
```

在**已有**域名的 Nginx `server { ... }` 中加入：

```nginx
include /path/to/bagel/deploy/nginx/bagel-location.conf;
```

或复制 [`deploy/nginx/bagel-location.conf`](../deploy/nginx/bagel-location.conf) 内容后：

```bash
nginx -t && systemctl reload nginx
```

完整独立站点示例见 `deploy/nginx/http.conf` / `https.conf`（仅当该域名尚无站点时使用，避免再抢 443）。

## 端口变量

| 变量 | 默认 | 含义 |
| --- | --- | --- |
| `BAGEL_BIND` | `127.0.0.1` | 宿主机绑定地址；公网勿用 `0.0.0.0` 除非你清楚风险 |
| `BAGEL_HOST_PORT` | `6280` | 宿主机映射到容器 `8000` 的端口；改了需同步改 Nginx `proxy_pass` |
| `APP_PORT` | `8000` | 仅影响本机 `bagel dev`；**Compose 内应用始终监听 8000** |

本机想直接打开浏览器而不经 Nginx：

```bash
BAGEL_BIND=0.0.0.0 BAGEL_HOST_PORT=8000 docker compose up -d --build
```

## 排障

- `bind: address already in use`：改 `BAGEL_HOST_PORT`，并改 Nginx 里的 `127.0.0.1:端口`
- 页面 CSS / 登录跳转到错误路径：确认 Nginx 设置了 `X-Forwarded-Prefix /bagel` 且 `proxy_pass` 带末尾 `/`
- 与旧卷冲突：旧部署若未设 `name: bagel`，卷名可能不同；需要时 `docker volume ls | grep bagel` 核对
