# 水上行走画册 / WALK ON WATER

一本纯静态的个人摄影电子画册，整体采用深色美术馆风格：暖墨底色、象牙文字、黄铜细节与轻微的纸面颗粒。当前已完成第一期内容：四个册集、21 张精选影像、卷首语、章节文字和完整的阅读交互。另有一套由 NAS 文件夹自动生成的相册（`gallery.html`），不需要逐张挑片，也不需要数据库或前端框架。

## 本地预览

在 `digital_album` 目录下运行：

```bash
python3 -m http.server 8000
```

然后访问 <http://localhost:8000>。

也可以直接双击 `index.html` 打开，但使用本地服务器可以获得更稳定的字体与脚本加载体验。

## 在 Windows 上预览

如果画册放在同一局域网的 Ubuntu 机器上，在 Ubuntu 中运行：

```bash
cd /home/lixin/lixin/github/digital_album
python3 -m http.server 8000 --bind 0.0.0.0
```

然后在 Windows 浏览器访问 `http://<Ubuntu 的局域网 IP>:8000`，例如
`http://192.168.0.9:8000`。如果打不开，检查 Ubuntu 防火墙是否放行了 8000 端口。

也可以把整个 `digital_album` 文件夹复制到 Windows，直接双击 `index.html`
离线阅读；所有图片、样式和脚本都使用相对路径，无需服务器。

## 部署到 H618 / Armbian

如果家里有常驻通电的 H618 Armbian 盒子，可以把画册部署成局域网 / 外网可访问的静态站点。
项目已包含 Nginx 配置和一键安装脚本：

```bash
# Ubuntu → H618
rsync -av --exclude '.git' \
  /home/lixin/lixin/github/digital_album/ \
  armbian@<H618-IP>:/home/armbian/digital_album/

# H618
cd ~/digital_album
sudo bash deploy/install-h618.sh
```

安装完成后访问 `http://<H618-IP>:8080`。外网访问可选 Tailscale（私有）或
Cloudflare Tunnel（公开，需要域名），详细步骤见 `deploy/README.md`。

## NAS 照片自动排版

如果不想手工挑片，可以让脚本直接读取 NAS 上的照片文件夹，自动生成相册目录、每册页面和响应式图片。生成结果仍然是纯静态 HTML，可以继续用现有的 Nginx / H618 方案部署。

### 工作流程

```text
NAS 照片目录
   │  只读挂载
   ▼
tools/build_gallery.py
   ├── 扫描册集 / 章节
   ├── 读取 EXIF（拍摄时间、相机、镜头、参数）
   ├── 生成 480 / 1100 / 1800 三档 JPEG
   ├── 写入 gallery.html + gallery-<slug>.html
   └── 更新 .gallery-cache/manifest.json
```

原片不会被修改；网页只引用 `assets/generated/` 里的副本。

### 目录约定

默认下层规则是 **顶层文件夹一册，册集里的子文件夹一章**：

```text
photos/
├── 2026-冬-长白山/
│   ├── 01-初雪/
│   │   ├── DSC_0001.NEF
│   │   └── DSC_0002.NEF
│   └── 02-冻海/
│       └── DSC_0003.NEF
└── 2025-秋-平潭/
    └── 01-海岸/
        └── IMG_1001.JPG
```

运行 `--album-depth 1`（默认）会生成《2026 冬 长白山》《2025 秋 平潭》两册，`01-初雪`、`02-冻海` 是章节。

如果目录是「相机型号 / 城市 / 年份」：

```text
photos/
└── Nikon-Z8/
    └── 上海/
        └── 2026/
            ├── 01-外滩/
            └── 02-雨夜/
```

用 `--album-depth 3`，`Nikon-Z8/上海/2026` 会成为一册，标题为「上海 · 2026」，`01-外滩`、`02-雨夜` 是章节。

常用层级：

| `--album-depth` | 含义 | 示例 |
| --- | --- | --- |
| `0` | `source` 本身是一册 | `photos/` 下直接放照片 |
| `1` | 第一层文件夹一册 | `photos/2026-冬-长白山/01-初雪/` |
| `2` | 第二层文件夹一册 | `photos/Nikon-Z8/上海/` |
| `3` | 第三层文件夹一册 | `photos/Nikon-Z8/上海/2026/` |

册集根目录下的直接照片会进入「影像」章节；子文件夹则各自成为章节。册集文件夹里的 `album.json` 不会被当作章节。

### 挂载 NAS

建议使用凭据文件，不要把密码直接写在命令行里。先在 Ubuntu 上执行：

```bash
sudo apt install -y cifs-utils
sudo mkdir -p /mnt/nas

sudo tee /etc/nas-photos.cred >/dev/null <<'EOF'
username=NAS用户名
password=NAS密码
EOF
sudo chmod 600 /etc/nas-photos.cred

sudo mount -t cifs //NAS-IP/共享名 /mnt/nas \
  -o credentials=/etc/nas-photos.cred,uid=$(id -u),gid=$(id -g),iocharset=utf8,ro
```

`ro` 表示只读挂载，脚本无法改到原片。如果挂载时报协议错误，可以追加 `vers=3.0` 或 `vers=2.1`：

```bash
sudo mount -t cifs //NAS-IP/共享名 /mnt/nas \
  -o credentials=/etc/nas-photos.cred,uid=$(id -u),gid=$(id -g),iocharset=utf8,vers=3.0,ro
```

确认能看到照片：

```bash
ls /mnt/nas/photos
```

### 生成与预览

先试运行，只扫描分组，不写任何文件：

```bash
python3 tools/build_gallery.py \
  --source /mnt/nas/photos \
  --album-depth 3 \
  --dry-run
```

确认册集数量正确后正式生成：

```bash
python3 tools/build_gallery.py \
  --source /mnt/nas/photos \
  --album-depth 3
```

生成后会得到：

```text
gallery.html                 # 相册目录
gallery-<slug>.html          # 每册一个页面
assets/generated/<slug>/     # 压缩后的网页图片
.gallery-cache/manifest.json # 构建缓存，不部署
```

打开 `gallery.html` 即可预览。本机启动预览服务后访问：

```text
http://localhost:8000/gallery.html
```

### 固定参数：gallery.config.json

不想每次敲参数，可以复制示例配置：

```bash
cp gallery.config.example.json gallery.config.json
```

编辑成自己的路径：

```json
{
  "source": "/mnt/nas/photos",
  "album_depth": 3,
  "max_edge": 1800,
  "quality": 82
}
```

之后直接运行：

```bash
python3 tools/build_gallery.py
```

命令行参数优先级高于配置文件；输出目录默认是项目根目录，可以用 `--output` 指定其他位置。

### 自动排版规则

- 照片按 EXIF `DateTimeOriginal` 排序；没有拍摄时间时使用文件修改时间
- 封面默认取最早的一张；册集页灯箱里的「设为封面」按钮会复制好设置命令，也可以在 `album.json` 里用 `cover` 指定文件名（见「修改册集封面」）
- 每章第一张保持整幅；竖图使用竖幅版式，成对的竖图自动组成双栏
- 宽横图使用内嵌宽度，超宽横图在合适位置使用全幅出血
- 照片编号跨章节连续，不会每章从 `No. 01` 重新开始
- 页面只去掉解释性文案（如自动生成规则的段落、卷首语正文、章节说明和结束语）；册数、年份、地点、页数、章节编号和照片图注等参数照常显示
- 生成的页面沿用现有 `css/style.css` 和 `js/main.js`，包括导航、滚动渐入、全屏预览、键盘切换和打印样式
- 每册页面会自动接入上一册 / 下一册链接；`gallery.html` 会显示所有册集

### 可选：album.json

在册集根目录放一个 `album.json`，可以覆盖自动生成的标题、卷首语、封面和章节名。所有字段都可以省略：

```json
{
  "title": "雪线以北",
  "subtitle": "Beyond the Snow Line",
  "slug": "snow",
  "year": "2026 冬",
  "location": "长白山 · 吉林",
  "cover": "DSC_0001.NEF",
  "lead": "雪落下的时候，世界先安静下来。",
  "prologue": "从第一场雪开始，沿着山路向北。这里收录的是同一段冬天里，光线落在雪上的不同方式。",
  "signature": "水上行走 · 2026 年 11 月",
  "description": "从第一场雪开始，沿着山路向北。",
  "end_quote": "照片会记得我们走过的地方，也会记得当时的光。",
  "chapters": {
    "01-初雪": {
      "title": "初雪",
      "en": "First Snow",
      "intro": "雪把声音收走，只留下脚步。",
      "quote": "雪不制造寂静，它只是把声音还给了世界。",
      "quote_cite": "旅行笔记 · 十二月"
    }
  },
  "captions": {
    "DSC_0001.NEF": "雪落在没有人走过的路上。"
  },
  "hidden": false
}
```

说明：

- `slug` 决定生成的文件名，建议使用英文短词；纯中文或纯数字文件夹会自动生成 `album-xxxxxxxx`，可以在 `album.json` 里改成更短的名字
- `chapters` 的键要和实际文件夹名一致，例如 `01-初雪`
- `cover` 和 `captions` 使用照片文件名
- `end_quote` 会覆盖册集末尾的结束语
- `hidden: true` 会暂时隐藏整册，不生成页面
- 两册 slug 相同时，脚本会自动追加短哈希避免覆盖

### 修改册集封面

封面同时用于相册首页的册集卡片和册集页顶部大图，改一处就会一起变。生成器按 `album.json` 里的 `cover` 取图，值是**照片文件名**，不用写路径：

```json
{"cover": "P1096445.jpg"}
```

现在**在网页上点一下就生效**：打开册集或画册，点开想做封面的照片，在灯箱工具条点「设为封面」。浏览器调用盒子上的本地管理接口写入 `album.json` 并自动重新生成，完成后跳回相册，封面已经换好，不需要再跑命令或强刷。

如果管理接口没在运行（例如只把静态文件拷到别处托管），按钮会自动回退成「复制一行命令」的模式：

```bash
bash /root/set-cover.sh P1096445.jpg       # 按文件名设置，自动定位册集
```

命令行还支持完整的查看与恢复：

```bash
bash /root/set-cover.sh                    # 列出所有册集和当前封面
bash /root/set-cover.sh --photos 泉州      # 列出该册照片和序号
bash /root/set-cover.sh 泉州 12            # 按序号设置
bash /root/set-cover.sh --clear 泉州       # 恢复默认（拍摄时间最早的一张）
```

设置后会自动重新生成并部署。批量改多册时可加 `--no-rebuild`，全部改完再运行一次 `bash /root/update-album.sh`。也可以直接编辑 `album.json`，已有的 `title`、`prologue`、`chapters` 等字段会保留，工具只改 `cover`。

`cover` 里的文件名必须真的在该册集目录（或子目录）中；填错时生成器会静默回退到默认封面，可用 `bash /root/set-cover.sh` 检查当前配置。

### 隐藏不想展示的照片

有些照片不想放进网站，但原片还要留着。把文件名写进册集目录的 `album.json`：

```json
{"hidden_photos": ["P1085284.jpg", "P1085285.jpg"]}
```

生成器会跳过它们，相册首页、册集页和画册页都不会再出现；**本地原文件不会被删除或移动**，随时可以恢复。被隐藏的照片也不参与封面选取和照片编号。

- **网页上**：点开照片，灯箱工具条点「不显示」，会先弹出带文件名的确认框；点「确认隐藏」（或按 `Enter`）才会执行，点「取消」或按 `Esc` 不会改动任何配置。确认后管理接口写入 `hidden_photos` 并自动重新生成，完成后这张照片在所有设备上都不再出现，原文件原封不动。
- 接口没运行时会自动回退为「本机立即隐藏 + 复制命令」，提示条里还有「撤销本机隐藏」按钮。
- **命令行**（在盒子上）：

  ```bash
  bash /root/hide-photo.sh --list              # 查看各册隐藏了哪些
  bash /root/hide-photo.sh P1085284.jpg        # 隐藏，自动定位册集
  bash /root/hide-photo.sh --show P1085284.jpg # 恢复显示
  ```

  执行后自动重新生成。批量操作可加 `--no-rebuild`，最后统一运行 `bash /root/update-album.sh`。

### 画册模式

独立页 `book.html` 是模拟实体摄影画册的在线作品集：默认显示**闭合的书壳**（书脊、书口纸层、标题/作者/年份），点击后书本展开，直接进入第一跨页的照片。顶部「封面」可回到闭合状态。

- **内容来源**：默认收录整个「泉州」册，之后只把你在相册里点「加入画册」的照片追加进来；其他册不会自动进入画册
- 双页跨页为核心，保留宽阔页边距和清晰书脊；版式有节奏变化：竖幅单页 / 双竖图、横幅单页大图 / 双图组合、跨页大图、留白页交替
- 按原始宽高比分类：竖幅优先单独一页并垂直居中；接近 3:2 的横幅且间隔足够时才做跨页大图（书脊自动淡化，不切主体）；其余横幅、方图、超宽图做单页或双图组合，并采用左右非对称留白，避免机械居中
- 所有照片统一 `object-fit: contain`，不拉伸、不裁切；移动端跨页图改为完整等比显示
- 画册直接加载 NAS 原图（浏览器无法直接显示的 RAW / HEIC 等格式才退回生成图），不再使用 1100px 压缩版；单页与跨页都以原图显示
- 阅读器接近全屏：桌面按「视口宽」与「可用高度 × 3/2」取较小值铺满，翻页按钮悬浮在书页两侧；闭合封面也同步放大，手机保持单页阅读
- 书页内部纯白、页面背景为深墨色，白色书页从暗底浮出；单页照片保留均匀白边，跨页大图在书脊处直接衔接、不留白缝；照片下方不再显示日期
- 模拟真实纸张：每张纸有正反面，以书脊为轴做 3D 旋转，桌面 1.3 秒、手机 0.7 秒的慢节奏翻页，阴影轻微；翻页期间会锁定连续点击
- 顶部有「封面」「目录」入口、当前章节和页码；目录按章节分组列出跨页，可直接跳转；左上角箭头返回相册
- 章节按照片来源册集自动区分：第一章直接看照片，后续章节插入一张只有序号和册名的留白占位页，不做文字描述
- 翻页：左右箭头、`←` / `→`、`Home` / `End`、手机上左右滑动；手机改为单页阅读，每次翻一面
- 在相册（或册集页）点开任意照片，灯箱工具条的「加入画册 / 移出画册」可随时调整；也可看原图、缩放、设为封面或隐藏
- 只加载当前跨页和相邻跨页的图片，不会一次拉取全部照片

画册清单保存在 `/root/digital_album/book.json`，只记录文件名，不复制也不改动原图。也可以在盒子上维护：

```bash
bash /root/book-photo.sh                       # 查看当前画册清单
bash /root/book-photo.sh --add P1096445.jpg     # 加入画册
bash /root/book-photo.sh --remove P1096445.jpg  # 移出画册
```

想换默认册集，把 `book.json` 里的 `album` 改成对应文件夹名即可。画册页由 `tools/build_gallery.py` 生成的 `book.html` 提供，照片数据内嵌在页面里，不需要数据库；隐藏名单同样生效。

### 本地管理接口

网页上的「设为封面」「不显示」之所以能点一下生效，是因为盒子上跑了一个很小的管理服务：

- `deploy/album-api.py` 只监听 `127.0.0.1:8765`，由 Nginx 把 `/api/` 反代过去，对外仍是同一个站点、同一个端口
- `deploy/album-api.service` 是 systemd 单元，`systemctl enable --now album-api` 后开机自启
- 接口收到请求后写 `album.json` 或 `book.json`，串行执行 `/root/update-album.sh`，完成后才返回；封面/隐藏操作后前端跳回相册，画册加入/移出则原地更新按钮
- `POST /api/book-add`、`POST /api/book-remove` 维护画册清单，`GET /api/book` 返回当前画册照片，供灯箱按钮判断状态
- `GET /api/status` 可查看服务是否在跑、是否正在重新生成

`deploy/deploy.py` 会给每个页面的 `css/style.css` 和 `js/main.js` 加上本次部署的版本号，配合 Nginx 的「HTML 不缓存、静态资源缓存 7 天」策略，改完脚本后浏览器会自动拿到新版本，不用再手动 `Ctrl+F5`。

> 接口对能访问站点的所有人开放（只改配置，不删除任何文件）。如果站点会暴露到公网，建议给 `/api/` 加一层访问控制。生成的页面本身仍是纯静态 HTML，拷到任意静态托管都能看，只是管理按钮会回退成命令行模式。

### 图注优先级

图注会显示在照片下方，并同时用于图片替代文本和全屏灯箱。取值从高到低：

1. `album.json` 里的 `captions`
2. 与照片同名的 `.txt` 或 `.caption` 文件（取第一行）
3. 自动生成：拍摄日期 + 相机型号 + 光圈 / 快门 / ISO / 焦段（缺失的参数会自动跳过）

例如 `DSC_0001.NEF` 旁边放一个 `DSC_0001.txt`：

```text
雪落在没有人走过的路上。
```

### 图片处理与隐私

每张照片会经过以下处理：

- 根据 EXIF 方向自动旋转，竖拍照片不会横着显示
- RGB 照片保留原始 ICC 色彩配置；CMYK / 灰度转换后不再使用原 ICC，避免浏览器按错误色彩空间解释
- 最长边缩放为 480 / 1100 / 1800 三档，网页通过 `srcset` 自动选择
- 输出 JPEG，默认质量 82，开启渐进式加载和优化
- **输出图会重新编码，不包含原图的 EXIF 和 GPS 信息**
- 页面只显示你配置的地点、日期和相机型号，不会公开拍摄坐标
- 无法解码的文件会跳过并继续，不会中断整批构建

原片始终只读，脚本不会写入 NAS。发布前仍建议检查照片本身是否包含敏感信息，例如窗外地标、门牌或人物。

### RAW / HEIC

- JPEG、PNG、WebP、TIFF 直接支持
- RAW（NEF / CR2 / ARW / RAF / DNG 等）需要 `exiftool`：

  ```bash
  sudo apt install -y libimage-exiftool-perl
  ```

  脚本会从 RAW 中提取内嵌预览图（`PreviewImage`、`JpgFromRaw` 或 `ThumbnailImage`）来生成网页图，不做完整 RAW 解码；如果相机没有写入足够大的预览图，输出分辨率可能低于原片。

- HEIC 需要 `pillow-heif`：

  ```bash
  python3 -m pip install --user pillow-heif
  ```

- 某个文件无法提取预览时，终端会提示并跳过，其他照片继续处理

### 增量构建

生成器会把每张照片的修改时间、尺寸、输出路径和 EXIF 信息缓存到：

```text
.gallery-cache/manifest.json
```

第二次运行只处理新增或修改过的照片，未变化的页面不会重写。强制全部重做：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos --force
```

修改 `--max-edge` 或 `--quality` 会自动让缓存失效。移动或删除照片后，旧的多余生成文件也会根据清单清理。

### 部署生成结果

生成仍然在 Ubuntu 上完成，H618 只负责提供静态文件。同步项目时，`gallery.html`、`gallery-*.html` 和 `assets/generated/` 会一起部署；`tools/`、`photos/`、`.gallery-cache/`、`gallery.config*.json` 不会进入网站目录：

```bash
rsync -av --exclude '.git' \
  /home/lixin/lixin/github/digital_album/ \
  armbian@<H618-IP>:/home/armbian/digital_album/

ssh armbian@<H618-IP> \
  'cd ~/digital_album && sudo bash deploy/install-h618.sh'
```

### 常见问题

**生成后没有册集**

先用 `--dry-run` 看脚本识别到了哪些文件夹。如果层级不对，调整 `--album-depth`：

```bash
python3 tools/build_gallery.py \
  --source /mnt/nas/photos \
  --album-depth 3 \
  --dry-run
```

**标题是 `album-xxxxxxxx`**

文件夹名是纯中文或纯数字，无法生成英文 slug。在册集里放一个 `album.json`：

```json
{"slug": "snow"}
```

**照片顺序不对**

检查照片的 EXIF 拍摄时间。没有 EXIF 的图片会按文件修改时间排序，可以在文件名前加日期，例如 `2026-01-12-001.jpg`。

**一册照片太多，页面太长**

用 `--album-depth` 把年份或城市拆成多册，或者在 `album.json` 里设置 `"hidden": true` 暂时隐藏某一册。

**挂载 NAS 失败**

确认共享名、用户名和密码正确，并尝试不同的 SMB 协议版本：

```bash
sudo mount -t cifs //NAS-IP/共享名 /mnt/nas \
  -o credentials=/etc/nas-photos.cred,uid=$(id -u),gid=$(id -g),iocharset=utf8,vers=2.1,ro
```

更多挂载和开机自动挂载示例见 `deploy/README.md`。

### 后续修改入口

如果要继续调整自动排版，主要改这些位置：

| 位置 | 作用 |
| --- | --- |
| `find_album_roots()` | 识别第几层文件夹是一册 |
| `display_title()` / `stable_slug()` | 自动标题、文件名和中文目录兜底 |
| `build_album()` | 读取 `album.json`、章节发现、封面和排序 |
| `process_photo()` | EXIF 方向、ICC、缩放、JPEG 质量和缓存 |
| `photos_html()` | 竖图双栏、全幅图、内嵌宽度等页面节奏 |
| `chapter_html()` / `album_html()` / `gallery_html()` | 生成的 HTML 结构；相册页面会自动带 `page-gallery` 类 |
| `main()` | 命令行参数、配置文件、输出和缓存清理 |
| `css/style.css` | `photo--portrait`、`photo--inset-wide`、`photo--full-bleed` 等生成页使用的样式 |
| `css/style.css` 末尾「深色美术馆」主题段 | 全站颜色、字体、卡片、首屏与画册阅读器尺寸 |
| `body.page-gallery` 的 `--archive-backdrop` | 相册的背景图，路径相对 `css/` 目录 |

修改图片处理流程后，记得同步提高 `main()` 里的 `options_key` 版本（当前为 `v2`），否则旧缓存可能被继续复用。推荐用临时目录测试，避免覆盖站点里的正式生成结果：

```bash
python3 -m py_compile tools/build_gallery.py

python3 tools/build_gallery.py \
  --source /tmp/gallery-test/photos \
  --output /tmp/gallery-test/site \
  --cache /tmp/gallery-test/cache.json \
  --album-depth 2 \
  --dry-run
```

完整参数和更多示例见 `tools/README.md`。

## 页面结构

```text
digital_album/
├── index.html              # 封面、编辑手记、本期推荐
├── albums.html             # 册集目录
├── album-shanhai.html      # 《山海之间》
├── album-city.html         # 《城市切片》
├── album-daily.html        # 《日常的光》
├── album-snow.html         # 《雪线以北》
├── gallery.html            # 自动生成的相册目录
├── gallery-*.html          # 自动生成的册集页面
├── book.html               # 自动生成的画册页（逐页翻阅）
├── about.html              # 关于画册与阅读说明
├── 404.html                # 找不到页面时的兜底页
├── css/style.css           # 深色美术馆主题、版式与打印 / PDF 样式
├── js/main.js              # 菜单、滚动动效、阅读进度、图片预览、缩放与隐藏
├── tools/                  # NAS 照片自动排版
│   ├── build_gallery.py
│   ├── set_cover.py         # 查看 / 修改册集封面
│   ├── hide_photo.py        # 隐藏 / 恢复照片
│   └── README.md
├── deploy/                 # H618 / Armbian 部署配置与说明
│   ├── deploy.py           # 一键生成 + 精简 + 发布
│   ├── album-api.py        # 网页管理操作的本地接口
│   ├── album-api.service   # 接口的 systemd 单元
│   ├── set-cover.sh        # 盒子上改封面的入口
│   ├── hide-photo.sh       # 盒子上隐藏照片的入口
│   ├── nginx-album.conf    # 站点配置（含 /api/ 反代）
│   ├── install-h618.sh
│   ├── nginx-album.conf
│   ├── cloudflared-ingress.example.yml
│   └── README.md
├── gallery.config.example.json
├── gallery.config.json     # 可选，本地生成参数（不部署）
├── .gallery-cache/         # 可选，增量构建缓存（不部署）
├── assets/
│   ├── favicon.svg
│   ├── images/             # 25 张原创 SVG 占位插画
│   └── generated/          # 自动生成的网页图片
└── README.md
```

`assets/generated/` 和 `gallery*.html` 由生成器维护，重新运行会被覆盖。需要长期保留的标题、卷首语、章节名和封面，应写进对应册集的 `album.json`；需要改变所有册集的排版，则修改 `tools/build_gallery.py` 或 `css/style.css`。

相册页面的 `<body>` 会带 `page-gallery` 类（生成器模板已同步），用于和册集目录区分网格列数与背景；手工复制相册页面时记得保留这个类。

## 已实现的内容与功能

- 完整的画册叙事：封面 → 编辑手记 → 本期册集 → 其他册集 → 结尾
- 四个可独立阅读的册集，每册包含卷首语、章节文字、图注与结束语
- 点击照片打开全屏预览；支持左右方向键、Home / End 切换，Esc 关闭
- 全屏预览可放大查看原图局部：滚轮缩放（以光标为中心）、双击、顶部 `−` / `+` / `1:1` / `适应` 按钮、`+` `-` `0` 键；放大后按住拖动平移，移动端支持双指捏合；`1:1` 直接跳到原图像素
- 照片预览会预加载相邻影像；移动端可左右滑动切换
- 灯箱里可把照片设为封面，或「不显示」这张；通过本地管理接口点一下就生效，隐藏只写 `album.json` 的 `hidden_photos`，不删本地原文件
- 导航里的「画册」提供书本式左右翻页浏览，每跨页 2–3 张，复用同一个原图灯箱
- 部署时给 `css`/`js` 加版本号，HTML 不缓存，浏览器总能拿到最新脚本
- 册集页可一键「打印 / 存为 PDF」，自动排版为 A4：封面、卷首语、章节各自分页
- 册集详情页顶部阅读进度条
- 滚动渐入、移动端全屏菜单；照片悬停不再有提示气泡，点击直接进入预览
- 册集目录为 2 列大幅卡片（桌面），相册为紧凑的 3 列网格（窄屏 2 列）：横幅封面铺满卡片、文字在下，竖幅封面按原始比例占左侧、文字在右侧；封面始终等比完整显示，不裁切
- 相册页面有一层虚化、压暗的城市夜景背景，从标题区向下渐隐；背景图由 CSS 变量 `--archive-backdrop` 控制，可一键替换
- 相册卡片使用半透明暖白卡纸与深墨文字，在暗底上像一张张浅色印相卡；其余版块保持深色
- 卡片小字只保留不重复的信息：与册名相同的副标题和地点不再显示，年份和影像数照常保留，页数不再显示；地点与册名不同时仍会显示
- 全站为「深色美术馆」主题：暖墨底 `#141310`、象牙字 `#f1ecdf`、黄铜强调色 `#c6aa7c`，叠加极淡纸面颗粒、右上角柔光和发丝细线；阴影克制，不再是纯色平铺
- 画册阅读器接近全屏（桌面约 92% 宽、98% 高），闭合封面同步放大；书壳为深色布面，内页保持纯白，从暗底中浮出
- 图片统一用 CSS 比例约束并显式设置 `height: auto`，避免 HTML 的 `height` 属性把卡片和首屏拉长
- 页面附带 `theme-color`（`#141310`），手机浏览器地址栏与站点底色一致
- 响应式布局，支持手机、平板与桌面
- 支持 `prefers-reduced-motion`，减少动效偏好下自动关闭动画
- 全站零第三方依赖，可离线打开
- 带一个与画册风格一致的 `404.html` 兜底页
- `tools/build_gallery.py` 可直接扫描 NAS 文件夹，自动生成相册、册集页面与响应式图片
- 支持 `--album-depth` 适配「册集 / 章节」「相机 / 城市 / 年份」等不同目录结构
- 自动读取 EXIF 拍摄时间排序，按竖图、横图、超宽图生成不同排版节奏
- 输出 480 / 1100 / 1800 三档 JPEG，保留 RGB ICC 色彩配置，自动校正 EXIF 方向
- 生成图去掉 EXIF 与 GPS；原片只读，不修改 NAS 文件
- 支持 `album.json` 覆盖标题、卷首语、封面、章节和图注，也支持同名 `.txt` / `.caption` 图注
- 支持增量构建、`--dry-run` 试运行和 `gallery.config.json` 固定参数
- 支持 JPEG / PNG / WebP / TIFF；RAW 需要 `exiftool`，HEIC 需要 `pillow-heif`
- 生成结果仍为纯静态文件，可直接用 Nginx / H618 部署

## 如何替换成自己的内容

如果照片都在 NAS 上，优先用上面的自动排版流程，不需要逐页修改 HTML。下面的手工替换方式适合精修四个正式册集，或调整首页、关于页等固定内容。

### 1. 换照片

把 `assets/images/` 中的 SVG 换成自己的图片，并同步修改 HTML 中的：

- `<img src="...">` 路径
- `alt` 图片描述
- `<figcaption>` 中的图注与地点
- `.photo-link` 的 `data-caption` 与 `data-location`（用于全屏预览）

建议的图片尺寸：

| 用途 | 比例 | 建议宽度 |
| --- | --- | --- |
| 册集封面 / 竖图 | 4:5 | 1200–1600px |
| 横图 | 3:2 | 1600–2400px |
| 全屏横幅 | 3:2 或 16:9 | 2000px 以上 |

图片可以保留 SVG，也可以换成 JPG / WebP。换格式时记得更新路径，并使用
`loading="lazy"` 优化下方图片的加载。

### 2. 改文字

- 首页文案：`index.html`
- 册集列表：`albums.html`
- 每册正文：对应的 `album-*.html`
- 关于页：`about.html`
- 画册名称、期号、页脚：各页面中的 `水上行走`、`WALK ON WATER`、`Vol. 01`、`2026`

### 3. 改配色与字体

颜色、字体与节奏集中在 `css/style.css` 末尾的「深色美术馆 · Gallery Noir」段落（文件最后一部分；顶部的旧 `:root` 是早期浅色基础，不要再改它）。核心变量：

```css
--bg: #141310;       /* 页面暖墨底 */
--ink: #f1ecdf;      /* 正文象牙白 */
--muted: #aaa394;    /* 次级文字 */
--muted-light: #918b7e;
--accent: #c6aa7c;   /* 黄铜强调色 */
--accent-soft: #ddc9a5;
--line: rgba(241, 236, 223, 0.14);
```

字体使用系统中文字体栈（思源宋体 / Noto Serif CJK / 宋体），无需联网；
若要换成品牌字体，修改 `--font-serif`、`--font-sans` 与 `--font-latin`。

相册背景和阅读器尺寸也在这里：

```css
/* 相册背景图，路径相对 css/ 目录；换一张图即可 */
body.page-gallery {
  --archive-backdrop: url("../assets/images/city-04.svg");
}

/* 画册阅读器：按视口宽与「可用高度 × 3/2」取较小值，尽量接近全屏 */
.book {
  width: min(calc(100vw - 2 * clamp(6px, 1vh, 14px)),
             calc((100svh - 2 * clamp(6px, 1vh, 14px)) * 3 / 2));
}
```

改完主色后，记得同步修改所有页面和 `tools/build_gallery.py` 三个模板里的
`<meta name="theme-color" content="#141310">`，否则手机状态栏颜色会和页面不一致。

### 4. 打印 / 导出 PDF

在任意册集页右上角点击「打印 / 存为 PDF」，或在浏览器中按 `Ctrl / ⌘ + P`。
打印样式会把封面、卷首语与每一章分别分页，隐藏导航、页脚和交互按钮，
并让照片保持在单页高度内。目标选择「另存为 PDF」即可得到可分享的文件。

打印字号、页边距与图片最大高度都集中在 `css/style.css` 末尾的
`@media print` 中，可按自己的打印机或纸张调整。

### 5. 404 页面

部署到 GitHub Pages、Vercel、Netlify 等静态托管后，把 `404.html` 配置为
自定义 404 页面即可（GitHub Pages 会自动识别根目录下的 `404.html`）。

## 后续可扩展

- 增加第 5 册：复制任一 `album-*.html`，替换正文与图片，并在 `albums.html`、页脚和上一册的“下一册”链接中接入
- 加入英文版本：新增 `/en/` 目录与对应页面
- 在自动相册中接入 WebP / AVIF 输出
- 部署到 GitHub Pages、Vercel 或任意静态托管

## 说明

站内 25 张图片均为本项目生成的原创抽象 SVG 插画，用作占位与风格演示，
不涉及第三方图片授权。`assets/generated/` 中的图片由你自己的照片自动生成；
替换为自己的摄影作品后，请确认作品版权与肖像权。
