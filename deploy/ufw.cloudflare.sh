#!/usr/bin/env bash
# 防火墙收紧：只允许 Cloudflare 边缘节点访问 443 端口，其他全部拒绝。
# 搭配 nginx.cloudflare.conf 使用，可避免源站 IP 被人直接扫到后绕过 CF。
#
# 用法：
#   sudo bash ufw.cloudflare.sh
set -euo pipefail

CF_V4_LIST=$(curl -fsSL https://www.cloudflare.com/ips-v4)
CF_V6_LIST=$(curl -fsSL https://www.cloudflare.com/ips-v6)

sudo ufw --force reset
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow OpenSSH

for cidr in $CF_V4_LIST $CF_V6_LIST; do
    sudo ufw allow from "$cidr" to any port 443 proto tcp
done

sudo ufw --force enable
sudo ufw status numbered
