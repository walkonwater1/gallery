#!/usr/bin/env bash
#
# 水上行走画册 · H618 / Armbian 一键部署脚本
#
# 用法（在 H618 上，从项目目录运行）：
#   sudo bash deploy/install-h618.sh
#
# 脚本会：
#   1. 安装 nginx / rsync
#   2. 把项目同步到 /srv/digital_album
#   3. 安装 Nginx 配置并监听 8080
#   4. 设置只读权限并重启 Nginx
#
# 可重复运行，用于更新网站。

set -euo pipefail

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

[[ ${EUID} -eq 0 ]] || die "请用 sudo 运行：sudo bash deploy/install-h618.sh"

ARCH="$(uname -m)"
log "CPU 架构：$ARCH"
case "$ARCH" in
  aarch64|arm64) ;;
  *) warn "当前不是 ARM64。H618 应显示 aarch64，脚本仍会继续。" ;;
esac

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SITE_SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
SITE_DEST="/srv/digital_album"
NGINX_CONF="$SCRIPT_DIR/nginx-album.conf"

[[ -f "$SITE_SRC/index.html" ]] || die "未找到 index.html：$SITE_SRC"
[[ -f "$NGINX_CONF" ]] || die "未找到 Nginx 配置：$NGINX_CONF"

# ---------- 安装依赖 ----------
PACKAGES=()
for pkg in nginx rsync curl; do
  dpkg -s "$pkg" >/dev/null 2>&1 || PACKAGES+=("$pkg")
done

if ((${#PACKAGES[@]})); then
  log "安装依赖：${PACKAGES[*]}"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y "${PACKAGES[@]}"
else
  log "nginx / rsync / curl 已安装"
fi

# ---------- 同步网站 ----------
log "同步网站到 $SITE_DEST"
install -d -m 0755 "$SITE_DEST"
rsync -a --delete \
  --exclude '.git/' \
  --exclude 'deploy/' \
  --exclude 'tools/' \
  --exclude '.gallery-cache/' \
  --exclude 'photos/' \
  --exclude 'gallery.config.json' \
  --exclude 'gallery.config.example.json' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  "$SITE_SRC/" "$SITE_DEST/"

log "设置只读权限"
chown -R www-data:www-data "$SITE_DEST"
find "$SITE_DEST" -type d -exec chmod 0755 {} +
find "$SITE_DEST" -type f -exec chmod 0644 {} +

# ---------- 安装 Nginx 配置 ----------
log "安装 Nginx 站点配置"
install -m 0644 "$NGINX_CONF" /etc/nginx/sites-available/album
ln -sf /etc/nginx/sites-available/album /etc/nginx/sites-enabled/album
rm -f /etc/nginx/sites-enabled/default

# 默认监听 0.0.0.0，方便局域网和 Tailscale 访问。
# 只用 Cloudflare Tunnel 时，可设置 BIND_ADDR=127.0.0.1，让 8080 不对局域网开放。
BIND_ADDR="${BIND_ADDR:-0.0.0.0}"
case "$BIND_ADDR" in
  0.0.0.0) ;;
  127.0.0.1)
    log "限制 Nginx 只监听 127.0.0.1:8080"
    sed -i 's/listen 8080;/listen 127.0.0.1:8080;/' /etc/nginx/sites-available/album
    sed -i '/listen \[::\]:8080;/d' /etc/nginx/sites-available/album
    ;;
  *) die "BIND_ADDR 只能是 0.0.0.0 或 127.0.0.1，当前为：$BIND_ADDR" ;;
esac

nginx -t
systemctl enable nginx
systemctl restart nginx

# ---------- 自检 ----------
if curl -fsS --noproxy '*' --max-time 5 http://127.0.0.1:8080/ >/dev/null; then
  log "自检通过：Nginx 已能返回首页"
else
  warn "自检失败：请运行 sudo systemctl status nginx 和 sudo journalctl -u nginx -n 50 查看原因"
fi

LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null \
  | awk '{for (i = 1; i <= NF; i++) if ($i == "src") { print $(i + 1); exit }}')"
[[ -n "${LAN_IP:-}" ]] || LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

cat <<EOF

部署完成。

  本机访问：   http://127.0.0.1:8080
EOF

if [[ "$BIND_ADDR" == "127.0.0.1" ]]; then
  cat <<'EOF'
  当前只监听本机 127.0.0.1:8080，请通过 Cloudflare Tunnel 访问。
EOF
else
  cat <<EOF
  局域网访问： http://${LAN_IP:-<H618-IP>}:8080
EOF
fi

cat <<'EOF'

更新网站：
  先把新文件同步到 H618 的项目目录，再重新运行：
  sudo bash deploy/install-h618.sh

如果局域网打不开，检查防火墙：
  sudo ufw status
  sudo ufw allow 8080/tcp
EOF

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q 'Status: active'; then
  warn "检测到 ufw 已启用。如局域网无法访问，执行：sudo ufw allow 8080/tcp"
fi
