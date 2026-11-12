# 部署到 H618 / Armbian

这套方案把 H618 电视盒子当作常驻网站主机：

```text
Windows / 手机 / 外网
        │
        ├── Tailscale（只给家人，最安全）
        └── Cloudflare Tunnel（公开访问，需要域名）
                    │
              H618 Armbian
              Nginx :8080
              /srv/digital_album
                    │  定期 rsync
              Mage 20（SMB 备份）
```

网站是纯静态文件，总共不到 1 MB。H618 只需要提供 HTTP 服务，不需要 Docker、数据库或后台程序。

## 一次性部署

### 1. 把项目复制到 H618

在 Ubuntu 上执行（把 `armbian` 和 `192.168.0.50` 换成 H618 的实际用户名和 IP）：

```bash
rsync -av --exclude '.git' \
  /home/lixin/lixin/github/digital_album/ \
  armbian@192.168.0.50:/home/armbian/digital_album/
```

如果 Ubuntu 上没有 rsync：

```bash
sudo apt install -y rsync
```

### 2. 在 H618 上运行安装脚本

```bash
ssh armbian@192.168.0.50
cd ~/digital_album
sudo bash deploy/install-h618.sh
```

脚本会自动完成：

- 安装 `nginx`、`rsync`、`curl`
- 把网站同步到 `/srv/digital_album`
- 安装 Nginx 配置，监听 `8080`
- 设置 `www-data` 只读权限
- 启动并设置 Nginx 开机自启
- 自检首页是否能正常返回

完成后会打印局域网地址，例如：

```text
http://192.168.0.50:8080
```

先在 Windows 浏览器里打开这个地址确认。

### 3. 建议给 H618 固定 IP

在路由器里给 H618 做 DHCP 地址保留，否则重启后 IP 可能变化，局域网地址和端口转发都会失效。

## 外网访问

### 方案 A：Tailscale（推荐，只给家人或自己）

H618 上安装：

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip -4
```

Windows 和手机安装 Tailscale 客户端，登录同一个账号。之后直接访问：

```text
http://<H618 的 Tailscale IP>:8080
```

如果开启了 MagicDNS，也可以用机器名：

```text
http://h618:8080
```

这个方案不需要域名、不需要公网 IP、不需要在路由器开端口。只有加入你 tailnet 的设备能访问。

临时把网站公开给某个人：

```bash
sudo tailscale funnel --bg 8080
sudo tailscale funnel status
```

会得到一个 `https://<机器名>.<tailnet>.ts.net` 地址。用完关闭：

```bash
sudo tailscale funnel --bg off
```

> Funnel 需要在 Tailscale 管理后台启用 HTTPS 证书。它适合临时分享，不适合长期公开站点。

### 方案 B：Cloudflare Tunnel（公开访问，需要域名）

前提：你有一个域名，并且 DNS 托管在 Cloudflare。

#### 1. 安装 cloudflared（ARM64）

```bash
curl -L -o /tmp/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64

sudo install -m 0755 /tmp/cloudflared /usr/local/bin/cloudflared
cloudflared --version
```

#### 2. 在 Cloudflare 面板创建隧道

1. 打开 Cloudflare Zero Trust → Networks → Tunnels
2. Create a tunnel → 选择 Cloudflared → 取名，例如 `shiguang`
3. 复制页面上的 Token
4. 在 H618 上安装为系统服务：

```bash
sudo cloudflared service install <TOKEN>
```

5. 回到隧道配置，添加 Public Hostname：

```text
Subdomain: album
Domain:    你的域名.com
Path:      留空
Service:   HTTP
URL:       localhost:8080
```

保存后访问：

```text
https://album.你的域名.com
```

Cloudflare 会自动处理 HTTPS 证书，不需要在 H618 上配置证书，也不需要路由器端口映射。

#### 可选：用本地配置文件而不是 Token

项目里提供了示例：

```bash
deploy/cloudflared-ingress.example.yml
```

复制到 `/etc/cloudflared/config.yml`，修改 tunnel UUID、credentials 路径和域名，然后：

```bash
sudo cloudflared tunnel ingress validate
sudo cloudflared --config /etc/cloudflared/config.yml service install
```

### 没有域名怎么办

- 只给家人看：用 Tailscale，不需要域名。
- 想公开但不想买域名：可以继续用 Tailscale Funnel 临时分享，或者直接用 Cloudflare Pages / GitHub Pages 托管静态站点。后者甚至不需要 H618 常开。
- 想长期自建公开站点：买一个便宜域名并托管到 Cloudflare，通常一年几十元。

## 更新网站

在 Ubuntu 上修改完内容后：

```bash
# 1. 同步到 H618 的项目目录
rsync -av --delete --exclude '.git' \
  /home/lixin/lixin/github/digital_album/ \
  armbian@192.168.0.50:/home/armbian/digital_album/

# 2. 在 H618 上重新部署
ssh armbian@192.168.0.50
cd ~/digital_album
sudo bash deploy/install-h618.sh
```

脚本是幂等的，可以反复运行。它会用新文件覆盖 `/srv/digital_album`，并保留 Nginx 配置。

如果使用 `tools/build_gallery.py` 生成照片库，`gallery.html` 和
`assets/generated/` 会一起部署；`tools/`、`photos/`、`.gallery-cache/` 和
`gallery.config*.json` 会被排除，不会进入网站目录。

如果只想快速替换页面、不想跑完整脚本：

```bash
sudo rsync -a --delete \
  --exclude '.git/' --exclude 'deploy/' \
  ~/digital_album/ /srv/digital_album/

sudo chown -R www-data:www-data /srv/digital_album
sudo systemctl reload nginx
```

## 备份到 Mage 20

H618 的 SD 卡或 eMMC 不适合作为唯一副本。建议定期把网站同步到 Mage 20 的 SMB 共享。

### 手动挂载并备份

```bash
sudo apt install -y cifs-utils
sudo mkdir -p /mnt/mage

sudo mount -t cifs \
  //192.168.0.10/共享名 /mnt/mage \
  -o username=NAS用户名,uid=www-data,gid=www-data,iocharset=utf8

sudo rsync -a --delete \
  /srv/digital_album/ /mnt/mage/digital_album/
```

### 开机自动挂载

创建凭据文件：

```bash
sudo tee /etc/cifs-mage.cred >/dev/null <<'EOF'
username=NAS用户名
password=NAS密码
EOF
sudo chmod 600 /etc/cifs-mage.cred
```

写入 `/etc/fstab`：

```fstab
//192.168.0.10/共享名 /mnt/mage cifs credentials=/etc/cifs-mage.cred,uid=www-data,gid=www-data,iocharset=utf8,nofail 0 0
```

然后：

```bash
sudo mkdir -p /mnt/mage
sudo mount -a
```

### 每天自动备份

```bash
sudo crontab -e
```

加入一行（每天凌晨 3 点）：

```cron
0 3 * * * mountpoint -q /mnt/mage && rsync -a --delete /srv/digital_album/ /mnt/mage/digital_album/
```

## 日常维护

```bash
# 查看 Nginx 状态
sudo systemctl status nginx

# 查看错误日志
sudo journalctl -u nginx -n 100 --no-pager
sudo tail -n 100 /var/log/nginx/error.log

# 检查 8080 是否被占用
sudo ss -ltnp | grep ':8080'

# 更新系统
sudo apt update && sudo apt upgrade -y

# 检查时间（时间不对会影响 HTTPS）
timedatectl
```

### 常见问题

**局域网打不开**

```bash
# 在 H618 本机测试
curl -I http://127.0.0.1:8080/

# 检查监听地址
sudo ss -ltnp | grep ':8080'

# 检查防火墙
sudo ufw status
```

如果本机能访问、Windows 不能，通常是防火墙没有放行：

```bash
sudo ufw allow 8080/tcp
```

**403 Forbidden**

```bash
namei -l /srv/digital_album/index.html
```

确认 `/srv`、`/srv/digital_album` 和文件对 `www-data` 可读：

```bash
sudo chown -R www-data:www-data /srv/digital_album
sudo find /srv/digital_album -type d -exec chmod 755 {} +
sudo find /srv/digital_album -type f -exec chmod 644 {} +
```

**404 Not Found**

确认 Nginx 配置里的 `root` 是 `/srv/digital_album`，并且 `index.html` 存在：

```bash
ls -l /srv/digital_album/index.html
sudo nginx -T | grep -A2 'root /srv'
```

**改了页面但浏览器还是旧的**

HTML 默认不缓存，静态资源缓存 7 天。强制刷新：

```text
Ctrl + F5
```

或者临时在地址后加 `?v=2`。

**Cloudflare 显示 502 / 1033**

说明隧道没有连上或后端 8080 不通：

```bash
sudo systemctl status cloudflared
curl -I http://127.0.0.1:8080/
sudo journalctl -u cloudflared -n 100 --no-pager
```

## 安全建议

- 只暴露网站本身，不要把 SSH、Mage 20 管理后台映射到公网。
- 用 Cloudflare Tunnel 时，可以让 Nginx 只监听本机：

  ```bash
  sudo BIND_ADDR=127.0.0.1 bash deploy/install-h618.sh
  ```

  这样局域网也无法直接访问 8080，所有访问都必须经过 Cloudflare。若同时使用 Tailscale，则保持默认的 `0.0.0.0`。

- SSH 建议使用密钥登录，并只允许局域网访问。
- 定期更新 Armbian 和 Nginx。
- 站点没有后台、数据库和上传功能，攻击面很小；主要风险来自系统本身和弱密码。

## 硬件与供电

- 使用质量可靠的 5V 电源，避免电压不稳导致 SD 卡损坏。
- 盒子保持通风，不要放在封闭柜子里。
- 建议把系统装在质量较好的 SD 卡或 eMMC 上，并保留 Mage 20 上的备份。
- 如果盒子有闲置的 USB 接口，可以接一个 U 盘做第二份备份，但不要作为唯一副本。
