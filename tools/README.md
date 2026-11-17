# NAS 照片自动排版

`build_gallery.py` 会扫描一个照片目录，自动生成：

- `gallery.html`：相册目录
- `gallery-<slug>.html`：每册一个页面
- `assets/generated/<slug>/`：压缩后的网页图片

页面沿用现有画册的 CSS 和交互，不需要数据库、后台或前端框架。

## 目录约定

默认情况下，**顶层文件夹是一册，里面的子文件夹是一章**：

```text
photos/
├── 2026-冬-长白山/
│   ├── 01-初雪/
│   │   ├── DSC_0001.NEF
│   │   ├── DSC_0002.NEF
│   │   └── DSC_0003.NEF
│   ├── 02-冻海/
│   │   └── DSC_0004.NEF
│   └── album.json          # 可选
└── 2025-秋-平潭/
    └── 01-海岸/
        └── IMG_1001.JPG
```

运行：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos
```

然后打开 `gallery.html`。册集根目录下的直接照片会进入「影像」章节，里面的子文件夹各自成为一章；`album.json` 不会被当作章节。

### 如果目录是“相机型号/城市/年份”

例如：

```text
photos/
└── Nikon-Z8/
    └── 上海/
        └── 2026/
            ├── 01-外滩/
            └── 02-雨夜/
```

把 `--album-depth` 设为 3：

```bash
python3 tools/build_gallery.py \
  --source /mnt/nas/photos \
  --album-depth 3
```

这样 `Nikon-Z8/上海/2026` 会成为一册，标题为「上海 · 2026」，
`01-外滩`、`02-雨夜` 是章节。

常用层级：

| `--album-depth` | 含义 | 适合的目录 |
| --- | --- | --- |
| `1` | 顶层文件夹一册 | `照片/长白山/初雪/` |
| `2` | 第二层文件夹一册 | `相机/上海/` |
| `3` | 第三层文件夹一册 | `相机/上海/2026/` |
| `0` | 整个 source 是一册 | 只有一个相册目录 |

## 固定参数

可以复制项目根目录的示例配置，避免每次输入参数：

```bash
cp gallery.config.example.json gallery.config.json
```

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

命令行参数优先于配置文件。先用 `--dry-run` 可以只查看识别到的册集，不写任何文件：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos --album-depth 3 --dry-run
```

## 页面节奏是怎么来的

- 照片按 EXIF `DateTimeOriginal` 排序，没有 EXIF 时用文件修改时间
- 竖图使用 `photo--portrait`；从第二张起，成对的竖图通常组成双栏
- 宽横图使用 `photo--inset-wide`，部分横图使用 `photo--inset`
- 每章第一张保持整幅
- 长宽比 ≥ 1.75 的超宽横图在每 6 张的位置使用全幅出血，避免页面节奏过于平均
- 封面默认取最早的一张，也可以用 `album.json` 指定
- 照片编号跨章节连续

## 可选：album.json

在册集根目录放一个 `album.json`，可以覆盖自动生成的标题、卷首语和章节名：

```json
{
  "title": "雪线以北",
  "subtitle": "Beyond the Snow Line",
  "slug": "snow",
  "year": "2026 冬",
  "location": "长白山 · 阿那亚 · 漠河",
  "cover": "DSC_0001.NEF",
  "lead": "雪落下的时候，世界先安静下来。",
  "prologue": "从第一场雪开始，沿着山路向北。这里收录的是同一段冬天里，光线落在雪上的不同方式。",
  "signature": "水上行走 · 2026 年 11 月",
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
  }
}
```

所有字段都可以省略。`slug` 会决定生成的文件名，建议用英文短词。`end_quote` 覆盖结束语；`hidden: true` 可以暂时隐藏整册。

## 图注

优先级从高到低：

1. `album.json` 里的 `captions`
2. 与照片同名的 `.txt` 或 `.caption` 文件（第一行）
3. 自动生成：日期 + 相机型号

例如 `DSC_0001.NEF` 旁边放一个 `DSC_0001.txt`：

```text
雪落在没有人走过的路上。
```

## 挂载 NAS

在 Ubuntu 上以只读方式挂载 SMB 共享。建议把凭据放在单独的权限文件里：

```bash
sudo apt install -y cifs-utils
sudo mkdir -p /mnt/nas

sudo tee /etc/nas-photos.cred >/dev/null <<'EOF'
username=NAS用户名
password=NAS密码
EOF
sudo chmod 600 /etc/nas-photos.cred

sudo mount -t cifs \
  //NAS-IP/共享名 /mnt/nas \
  -o credentials=/etc/nas-photos.cred,uid=$(id -u),gid=$(id -g),iocharset=utf8,ro
```

如果协议不兼容，在挂载参数里追加 `vers=3.0` 或 `vers=2.1`。`ro` 表示只读，生成器不会修改 NAS 上的原片。

确认能看到照片：

```bash
ls /mnt/nas/photos
```

然后运行生成器：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos --album-depth 1
```

生成器只读取 NAS，不会修改原片。

## RAW / HEIC

- JPEG、PNG、WebP、TIFF 直接支持。
- RAW（NEF / CR2 / ARW / RAF / DNG 等）需要 `exiftool`：

  ```bash
  sudo apt install -y libimage-exiftool-perl
  ```

- HEIC 需要 `pillow-heif`：

  ```bash
  python3 -m pip install --user pillow-heif
  ```

如果某个 RAW 无法提取预览，脚本会跳过并在终端提示，不会中断整次构建。

## 增量构建

生成器会把图片元数据和输出路径缓存到：

```text
.gallery-cache/manifest.json
```

第二次运行只处理新增或修改过的照片，未变化的页面不会重写。修改 `--max-edge` 或 `--quality` 会让图片缓存自动失效；移动或删除照片后，旧的多余生成文件会按清单清理。强制全部重做：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos --force
```

## 隐私

输出图片会重新编码，**不会带上原图的 EXIF 和 GPS 信息**。页面只显示你配置的地点、日期和相机型号，不会公开拍摄坐标。

图片会按 EXIF 方向自动旋转；RGB 照片保留原始 ICC 色彩配置，CMYK / 灰度照片转换为 RGB 后不再沿用原 ICC，避免浏览器按错误色彩空间解释。

如果照片本身包含敏感信息（例如家里窗外的地标），发布前仍然需要自己检查。

## 部署到 H618

生成完成后，按项目根目录的 `deploy/README.md` 同步到 H618：

```bash
rsync -av --exclude '.git' \
  /home/lixin/lixin/github/digital_album/ \
  armbian@<H618-IP>:/home/armbian/digital_album/

ssh armbian@<H618-IP> \
  'cd ~/digital_album && sudo bash deploy/install-h618.sh'
```

`gallery.html` 和 `assets/generated/` 会一起部署；`tools/`、`photos/` 和 `.gallery-cache/` 不会进入网站目录。

## 常见问题

**生成后页面是空白 / 没有图片**

确认输出目录是项目根目录：

```bash
python3 tools/build_gallery.py --source /mnt/nas/photos --output /home/lixin/lixin/github/digital_album
```

**标题是 `album-xxxxxxxx`**

文件夹名是纯中文或纯数字，无法生成英文 slug。可以在 `album.json` 里指定：

```json
{"slug": "snow"}
```

**一册里照片顺序不对**

检查照片的 EXIF 拍摄时间。没有 EXIF 的图片会按文件修改时间排序。可以在文件名前加日期，例如 `2026-01-12-001.jpg`。

**照片太多，页面很长**

默认全部收录，不挑选。可以先用 `--album-depth` 把年份或城市拆成多册；如果仍然太长，可以在 `album.json` 里设置 `"hidden": true` 暂时隐藏某一册。
