# 部署指南

本项目是一个单容器的 Flask Web 应用，无数据库、无后台任务，部署很简单。下面给出 3 条常用路径，按你的场景挑一条即可。

> **先申请 USDA API Key**（必做）：<https://fdc.nal.usda.gov/api-key-signup>
> 邮箱提交后立刻拿到，免费、额度 1000 次/小时。不配的话线上很快就会被 429 限流。

---

## 方案 A：Docker 部署到任意 Linux 服务器（推荐）

适用：阿里云 / 腾讯云 / AWS EC2 / DigitalOcean 等任意 VPS。一次构建、随处运行。

### 1. 本地构建并测试

```bash
docker build -t foodquery:latest .
docker run --rm -p 8000:8000 -e USDA_API_KEY=你的KEY foodquery:latest
# 访问 http://localhost:8000
```

### 2. 部署到服务器

**A. 用 docker compose（推荐）**：把代码传到服务器后

```bash
export USDA_API_KEY=你的KEY
docker compose up -d --build
docker compose logs -f
```

**B. 推镜像到 registry 再拉取**（适合多机 / CI）：

```bash
docker build -t ghcr.io/你/foodquery:v1 .
docker push ghcr.io/你/foodquery:v1

# 服务器上
docker run -d --name foodquery --restart=unless-stopped \
  -p 8000:8000 \
  -e USDA_API_KEY=你的KEY \
  -v foodquery_cache:/app/.cache \
  ghcr.io/你/foodquery:v1
```

### 3. 绑定域名（用 Cloudflare）

见下面的 [**Cloudflare 域名 & HTTPS**](#cloudflare-域名--https) 专门章节。三种搭配任选其一：

- **路径 1：Cloudflare 橙云 + Nginx + Origin Cert**（最常规，适合已经熟悉 Nginx 的场景）
- **路径 2：Cloudflare Tunnel**（最省心，服务器一个端口都不用开）
- **路径 3：Cloudflare CNAME 到 PaaS**（走 Render/Fly.io 时）

---

## 方案 B：PaaS 一键托管（零运维，适合个人项目）

这些平台读取 `Procfile` 或直接识别 Dockerfile，推送代码就自动部署。

### Render（免费档最友好，推荐国际访问）

1. GitHub 推代码
2. 登录 <https://render.com>，`New → Web Service` 连接仓库
3. 设置：
   - **Environment**: `Docker`（会自动识别 `Dockerfile`）
   - **Environment Variables**: `USDA_API_KEY=你的KEY`
4. 点 `Create`，2~3 分钟后会给你一个 `https://foodquery.onrender.com` 域名

### Fly.io（性能更好，全球节点）

```bash
# 1. 安装 flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login

# 2. 项目目录里
fly launch --no-deploy   # 会自动根据 Dockerfile 生成 fly.toml
fly secrets set USDA_API_KEY=你的KEY
fly deploy
```

### Railway

<https://railway.app> → `Deploy from GitHub` → 选仓库 → 设 `USDA_API_KEY` 环境变量 → 完成。

---

## 方案 C：传统 VPS + systemd（不想用 Docker）

适合已经有一台 Ubuntu/Debian 服务器，想直接跑 Python 进程。

```bash
# 1. 安装 Python 3.13 和依赖
sudo apt update
sudo apt install python3.13 python3.13-venv python3-pip nginx

# 2. 把代码放到 /opt/foodquery
sudo mkdir -p /opt/foodquery && sudo chown $USER /opt/foodquery
cd /opt/foodquery
# (rsync / git clone 你的代码)

python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. 验证
USDA_API_KEY=你的KEY gunicorn -c gunicorn.conf.py wsgi:app
# Ctrl+C 退出
```

创建 `/etc/systemd/system/foodquery.service`：

```ini
[Unit]
Description=FoodQuery Flask App
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/foodquery
Environment="PORT=8000"
Environment="USDA_API_KEY=你的KEY"
Environment="WEB_CONCURRENCY=2"
ExecStart=/opt/foodquery/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now foodquery
sudo systemctl status foodquery
```

Nginx 反代配置和方案 A 的第 3 步一致。

---

## Cloudflare 域名 & HTTPS

Cloudflare 同时帮你做了 **DNS、CDN、WAF、免费 SSL**。三种典型搭配：

### 准备工作（三种路径共用）

1. 在 Cloudflare 添加你的域名（Cloudflare → Add a site），把域名 NS 记录改到 Cloudflare 给的两个域名服务器。等 DNS 切换完成（一般 5~30 分钟）。
2. 进入域名管理 → **SSL/TLS** → **Overview**，把模式设为 **Full (strict)**。
   > 不要用 `Flexible`，那会让 Cloudflare 到源站之间走 HTTP，存在中间人风险；也不要用 `Full`（不验证证书）。

### 路径 1：橙云 + Nginx + Origin Cert（最常规）

适合方案 A / C：服务器上有 Nginx，自己控制配置。

#### 1. 申请 Cloudflare Origin Certificate（15 年有效）

Cloudflare 控制台 → **SSL/TLS** → **Origin Server** → **Create Certificate**。
保存生成的 `cert.pem` 和 `key.pem` 到服务器：

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/food.example.com.pem   # 贴 cert
sudo nano /etc/ssl/cloudflare/food.example.com.key   # 贴 key
sudo chmod 600 /etc/ssl/cloudflare/*.key
```

#### 2. 在 Cloudflare DNS 加一条记录

| Type | Name | Content                | Proxy |
|------|------|------------------------|-------|
| A    | food | `<你的服务器公网 IP>` | 🟧 Proxied |

#### 3. 启用项目自带的 Nginx 配置

仓库已经准备好了 [`deploy/nginx.cloudflare.conf`](./deploy/nginx.cloudflare.conf)，里面已经包含：

- 完整的 Cloudflare IP 段 `set_real_ip_from`
- `real_ip_header CF-Connecting-IP`（让 `request.remote_addr` 拿到真正的访客 IP）
- 监听 443，证书指向上一步保存的 Origin Cert
- 80 端口默认 `return 444`，防止源站 IP 被人发现后绕过 CF

```bash
sudo cp deploy/nginx.cloudflare.conf /etc/nginx/sites-available/foodquery
# 把里面的 food.example.com 改成你的域名
sudo nano /etc/nginx/sites-available/foodquery
sudo ln -s /etc/nginx/sites-available/foodquery /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

#### 4. 防火墙：只放行 Cloudflare 的 IP（关键）

如果不限制，攻击者扫到你源站 IP 就能绕过 CF。仓库里有现成脚本：

```bash
sudo bash deploy/ufw.cloudflare.sh
```

它会自动从 `cloudflare.com/ips-v4`、`/ips-v6` 拉最新 IP 段，把 443 端口仅放给 CF，再放 SSH 给你自己。

> Cloudflare IP 段会更新（半年级）。建议加个 cron 每周刷一次：
>
> ```bash
> echo "0 4 * * 0 root bash /opt/foodquery/deploy/ufw.cloudflare.sh >/dev/null 2>&1" | sudo tee /etc/cron.d/cf-ufw-refresh
> ```

#### 5.（强推）开启 Authenticated Origin Pulls

Cloudflare → **SSL/TLS** → **Origin Server** → 启用 **Authenticated Origin Pulls**。然后把 Cloudflare 的根证书装到 Nginx，并解开 `nginx.cloudflare.conf` 里那两行 `ssl_client_certificate` / `ssl_verify_client`。这样即使源站 IP 泄漏，没有 CF 客户端证书的请求会被 Nginx 直接拒绝。

```bash
sudo wget -O /etc/ssl/cloudflare/authenticated_origin_pull_ca.pem \
    https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem
sudo systemctl reload nginx
```

---

### 路径 2：Cloudflare Tunnel（不开任何入站端口，最省心）

适合：源站没固定公网 IP / 在 NAT 后面 / 想彻底关上 443。容器只往外建一条长连接到 Cloudflare 边缘，外网请求经隧道反向送进来。

#### 1. 在 Cloudflare 创建一个 Tunnel

Cloudflare → **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → 选 `Cloudflared` → 起个名字（比如 `foodquery`）→ 复制生成的 **Token**。

#### 2. 加一条 Public Hostname

在该 Tunnel 的 **Public Hostnames** tab 添加：

| 字段 | 值 |
|------|----|
| Subdomain | `food` |
| Domain | `example.com` |
| Service Type | `HTTP` |
| URL | `web:8000` |

> Cloudflare 会自动帮你写 DNS CNAME 记录，并签发证书。

#### 3. 在服务器上启动

仓库提供了 compose 叠加文件：

```bash
export USDA_API_KEY=你的KEY
export CLOUDFLARE_TUNNEL_TOKEN=粘贴你的Token

docker compose -f docker-compose.yml -f docker-compose.cloudflared.yml up -d
docker compose logs -f cloudflared
```

宿主机现在 **没有任何端口对外**。SSH 端口（22）也建议只放白名单 IP。

#### 4. 验证

浏览器打开 `https://food.example.com`，CF 控制台 Tunnel 状态应该是 **HEALTHY**。

> Tunnel 方案可以和 nginx 共存（如果你想自己加 access log / 路由），但对这个简单 Flask 项目通常没必要 —— 直接 cloudflared → web 就够了。

---

### 路径 3：Cloudflare DNS → PaaS（CNAME，对应方案 B）

如果你已经把项目部署到 Render / Fly.io / Railway，要让访客走自己的域名：

1. 在 PaaS 控制台添加自定义域名 `food.example.com`，它会给你一个目标，比如 Render 的 `foodquery.onrender.com`，Fly.io 的 `foodquery.fly.dev`。
2. 在 Cloudflare DNS 加一条 **灰云**（DNS only）的 CNAME：

   | Type | Name | Content                  | Proxy |
   |------|------|--------------------------|-------|
   | CNAME | food | `foodquery.onrender.com` | ⚪ DNS only（先灰云） |

3. 等 PaaS 那边显示证书签发成功（Let's Encrypt，几分钟），把代理切回 🟧 **Proxied**。
4. SSL 模式改成 **Full (strict)**。

> 一开始一定要先**灰云**，否则 PaaS 拿不到 ACME challenge 验证不了证书。验证成功后再开橙云。

---

### Cloudflare 推荐设置

无论走哪条路径，进 Cloudflare 控制台再做这几件事：

- **SSL/TLS → Edge Certificates**：勾上 **Always Use HTTPS**、**Automatic HTTPS Rewrites**、**HSTS** （首次启用先短 max-age 试水）。
- **SSL/TLS → Edge Certificates → Minimum TLS Version**：改成 `TLS 1.2`。
- **Speed → Optimization**：开启 `Brotli`、`Auto Minify` (HTML/CSS/JS)。
- **Caching → Configuration**：浏览器缓存 TTL 设 4 小时。
- **Caching → Cache Rules**：为 `/static/*` 加一条规则 `Edge TTL: 1 month`，CSS/图标这种几乎不变的东西就让 CF 边缘扛了。
- **Rules → Page Rules**（也可以用 Cache Rules）：
  - `food.example.com/healthz*` → Cache Level: Bypass（健康检查不要被 CF 缓存）。

### Cloudflare 在中国大陆的现实

Cloudflare 默认 **不接入中国大陆 POP**，大陆访客实际是走香港/日本/美西节点回源，延迟 100~300ms 起步。如果你的目标用户在国内：

- **付费 China Network**：需要 Enterprise 计划，门槛高
- **更现实的做法**：CF 走海外用户；国内访客通过另一条线路（比如 阿里云 CDN + ICP 备案域名 / 七牛 / 又拍）。本项目可以在 Nginx 层做 GeoIP 分流，或干脆国内国外两个子域名各自走自己的 CDN。
- **小流量 demo**：直接全走 Cloudflare 也能用，只是慢一点；对一个查询页面体感可以接受。

---

## 国内部署注意事项（重要）

本项目依赖两个**境外 API**：

- `api.nal.usda.gov`（USDA）
- `search.openfoodfacts.org` / `world.openfoodfacts.org`

如果你部署到**中国大陆服务器**，会遇到：

- USDA 延迟较高（300~800ms），偶发丢包
- Open Food Facts 在大陆访问不稳定

解决办法（按优先级）：

1. **部署到香港 / 新加坡节点**（阿里云国际版、腾讯云轻量境外、DigitalOcean 新加坡、Vultr 东京都可）。最省事。
2. **上游加代理**：在容器入口设置 `HTTPS_PROXY`，走你可控的海外代理。
3. **极致方案**：把常用查询结果预热到 `.cache`，配合 CDN（比如 Cloudflare）缓存整页。
4. **长期方案**：改成本地中国食物成分表（约 1500 条核心食物的 JSON 文件），让绝大多数中文查询完全离线，USDA 仅作补充 —— 这也解决了营养口径更贴近国人饮食的问题。

---

## 部署后检查清单

- [ ] `curl https://你的域名/healthz` 返回 `{"status":"ok"}`
- [ ] `curl 'https://你的域名/?q=banana'` 返回带 USDA 徽章的结果
- [ ] 浏览器里搜"香蕉"，首条为 `Bananas, raw`
- [ ] 配置了 HTTPS（Let's Encrypt / PaaS 默认）
- [ ] 设置了真实 `USDA_API_KEY`，没有使用 `DEMO_KEY`
- [ ] 日志可查（`docker logs foodquery` / `journalctl -u foodquery`）
- [ ] 缓存卷 `.cache` 挂载正确，重启后不丢
