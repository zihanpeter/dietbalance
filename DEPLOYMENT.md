# 部署指南（systemd + Cloudflare Tunnel）

当前推荐方式：

- `dietbalance` 用 systemd 托管 Gunicorn
- `cloudflared` 用 systemd 托管 Tunnel
- 不使用 Docker、不使用 Nginx

---

## 1) 准备环境

```bash
sudo apt update
sudo apt install -y python3.13 python3.13-venv python3-pip cloudflared
```

```bash
cd /opt/dietbalance
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 2) 配置 USDA Key 文件（.env）

先申请 USDA Key：<https://fdc.nal.usda.gov/api-key-signup>

```bash
cat > .env <<'EOF'
USDA_API_KEY=你的KEY
EOF

```

默认会读取当前目录 `.env` 中的 `USDA_API_KEY`。  
不再支持通过环境变量注入 `USDA_API_KEY`。

---

## 3) 配置并启动 `dietbalance` systemd 服务

创建 `/etc/systemd/system/dietbalance.service`：

```ini
[Unit]
Description=DietBalance Gunicorn
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/dietbalance
Environment=PORT=8000
Environment=WEB_CONCURRENCY=2
ExecStart=/opt/dietbalance/.venv/bin/gunicorn -c gunicorn.conf.py wsgi:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动并设为开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dietbalance
sudo systemctl status dietbalance
curl http://127.0.0.1:8000/healthz
```

---

## 4) 配置并启动 `cloudflared` systemd 服务

在 Cloudflare Zero Trust 创建 Tunnel，拿到 `TUNNEL_TOKEN`，并在 Public Hostname 中配置：

- Service Type: `HTTP`
- URL: `http://localhost:8000`

安装服务并启动：

```bash
sudo cloudflared service install <你的TunnelToken>
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

---

## 5) 日常运维

常用命令：

```bash
sudo systemctl restart dietbalance
sudo systemctl restart cloudflared
journalctl -u dietbalance -f
journalctl -u cloudflared -f
```

---

## 6) 检查清单

- [ ] `curl http://127.0.0.1:8000/healthz` 返回 `{"status":"ok"}`
- [ ] `https://你的域名/healthz` 可访问
- [ ] 页面查询 `香蕉` 返回正常结果
- [ ] `.env` 中已设置真实 `USDA_API_KEY`（非 `DEMO_KEY`）
