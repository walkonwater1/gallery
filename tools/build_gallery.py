#!/usr/bin/env python3
"""
拾光画册 · NAS 照片自动排版

把一个照片目录扫描成静态画册页面：

    photos/
      2026-冬-长白山/          <- 顶层文件夹 = 一册
        01-初雪/               <- 子文件夹 = 一章
          DSC_0001.NEF
          DSC_0002.NEF
        02-冻海/
          ...
      2025-秋-平潭/
        ...

运行：

    python3 tools/build_gallery.py --source /mnt/nas/photos

生成：

    gallery.html               # 照片库目录
    gallery-<slug>.html        # 每册一个页面
    assets/generated/<slug>/   # 自动压缩后的图片

只依赖 Pillow。RAW 文件需要系统里有 exiftool；HEIC 需要 pillow-heif。

设计原则：
- 不修改原片，原片目录只读。
- 输出图片会去掉 EXIF/GPS，避免把家庭位置带到公网。
- 页面沿用现有画册的 CSS 和交互，不引入前端框架。
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from PIL import Image, ImageOps
except ImportError:
    sys.exit("缺少 Pillow。请先运行：python3 -m pip install --user Pillow")

# 本地照片，允许超大图；不要把这个值用在不可信的上传文件上。
Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT
DEFAULT_CACHE = ROOT / ".gallery-cache" / "manifest.json"

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp",
}
RAW_EXTS = {
    ".nef", ".nrw", ".cr2", ".cr3", ".arw", ".srf", ".sr2",
    ".raf", ".orf", ".rw2", ".dng", ".pef", ".srw", ".raw",
}
HEIC_EXTS = {".heic", ".heif"}
SKIP_DIRS = {
    ".git", ".svn", "__MACOSX", "@eaDir", "#recycle",
    ".thumbnails", "thumbnails", ".gallery-cache",
}


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class Photo:
    source: Path
    rel_source: str
    digest: str
    width: int
    height: int
    taken_at: datetime | None
    camera: str = ""
    lens: str = ""
    exposure: str = ""
    aperture: str = ""
    iso: str = ""
    focal: str = ""
    caption: str = ""
    location: str = ""
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def default(self) -> dict[str, Any]:
        return self.outputs.get("1100") or self.outputs["1800"]

    @property
    def large(self) -> dict[str, Any]:
        return self.outputs["1800"]

    @property
    def date_label(self) -> str:
        return self.taken_at.strftime("%Y.%m.%d") if self.taken_at else ""


@dataclass
class Chapter:
    title: str
    en: str
    intro: str
    quote: str
    quote_cite: str
    photos: list[Photo]


@dataclass
class Album:
    source: Path
    rel: str
    title: str
    subtitle: str
    slug: str
    year: str
    location: str
    prologue: str
    signature: str
    description: str
    chapters: list[Chapter]
    cover: Photo
    config: dict[str, Any]

    @property
    def photos(self) -> list[Photo]:
        return [p for ch in self.chapters for p in ch.photos]

    @property
    def count(self) -> int:
        return len(self.photos)

    @property
    def pages(self) -> int:
        return max(8, self.count * 2 + 4)

    @property
    def reading_minutes(self) -> int:
        return max(1, round(self.count * 0.12))

    @property
    def date_range(self) -> str:
        dates = [p.taken_at for p in self.photos if p.taken_at]
        if not dates:
            return ""
        lo, hi = min(dates), max(dates)
        if lo.date() == hi.date():
            return lo.strftime("%Y.%m.%d")
        if lo.year == hi.year:
            return f"{lo:%Y.%m.%d} — {hi:%m.%d}"
        return f"{lo:%Y.%m.%d} — {hi:%Y.%m.%d}"

    @property
    def page_name(self) -> str:
        return f"gallery-{self.slug}.html"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"  {msg}")


def die(msg: str) -> None:
    sys.exit(f"错误：{msg}")


def e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def natural_key(value: str) -> list[Any]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    return slug


def stable_slug(rel: str) -> str:
    slug = slugify(rel)
    digest = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    # 纯数字（例如文件夹名里的年份）不适合当 slug，用稳定短哈希代替。
    if len(slug) >= 3 and re.search(r"[a-z]", slug):
        return slug[:60].strip("-")
    return f"album-{digest}"


def clean_segment(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value


def display_title(rel: Path, depth: int) -> str:
    parts = list(rel.parts)
    if not parts:
        return "未命名册集"
    take = parts[-min(len(parts), 2):] if depth >= 2 else parts[-1:]
    return " · ".join(clean_segment(p) for p in take)


def find_years(value: str) -> list[str]:
    return re.findall(r"(?:19|20)\d{2}", value)


def derive_year(rel: Path, photos: list[Photo]) -> str:
    years = sorted(set(find_years(str(rel))))
    if years:
        if len(years) == 1:
            return years[0]
        return f"{years[0]}—{years[-1]}"
    dates = [p.taken_at for p in photos if p.taken_at]
    if dates:
        ys = sorted({d.year for d in dates})
        return str(ys[0]) if len(ys) == 1 else f"{ys[0]}—{ys[-1]}"
    return ""


def derive_location(rel: Path) -> str:
    segments = [clean_segment(p) for p in rel.parts]
    candidates = [p for p in segments if not re.fullmatch(r"(?:19|20)\d{2}(?:[—\-](?:19|20)\d{2})?", p)]
    if candidates:
        return candidates[-1]
    return clean_segment(rel.name)


def sha1_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    text = str(value).strip().replace("\x00", "")
    if not text:
        return None
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore").strip("\x00 ")
    return str(value).strip("\x00 ")


def as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def fmt_exposure(value: Any) -> str:
    number = as_float(value)
    if not number or number <= 0:
        return ""
    if number < 1:
        return f"1/{round(1 / number)}s"
    return f"{number:g}s"


def fmt_aperture(value: Any) -> str:
    number = as_float(value)
    return f"f/{number:g}" if number else ""


def fmt_focal(value: Any) -> str:
    number = as_float(value)
    return f"{number:g}mm" if number else ""


def fmt_iso(value: Any) -> str:
    if isinstance(value, (list, tuple)) and value:
        value = value[0]
    number = as_float(value)
    return f"ISO {number:g}" if number else ""


def read_exif(im: Image.Image) -> dict[str, Any]:
    exif = im.getexif()
    sub: dict[int, Any] = {}
    try:
        sub = exif.get_ifd(0x8769) or {}
    except Exception:
        sub = {}

    def pick(tag: int, default: Any = None) -> Any:
        if tag in sub:
            return sub.get(tag)
        return exif.get(tag, default)

    make = as_text(pick(271))
    model = as_text(pick(272))
    make = re.sub(
        r"\s*(?:CORPORATION|CO\.?,?\s*LTD\.?|INC\.?|IMAGING)\s*$",
        "",
        make,
        flags=re.IGNORECASE,
    ).strip()
    if model.lower().startswith(make.lower()) or not make:
        camera = model
    elif model:
        camera = f"{make} {model}"
    else:
        camera = make
    camera = re.sub(r"\s+", " ", camera).strip()

    taken = (
        parse_datetime(pick(36867))
        or parse_datetime(pick(36868))
        or parse_datetime(pick(306))
    )

    return {
        "taken_at": taken,
        "camera": camera,
        "lens": as_text(pick(42036)),
        "exposure": fmt_exposure(pick(33434)),
        "aperture": fmt_aperture(pick(33437)),
        "iso": fmt_iso(pick(34855)),
        "focal": fmt_focal(pick(37386)),
    }


def to_rgb(im: Image.Image) -> Image.Image:
    if im.mode == "RGB":
        return im
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return im.convert("RGB")


def open_image(path: Path) -> Image.Image:
    ext = path.suffix.lower()
    if ext in HEIC_EXTS:
        try:
            import pillow_heif  # type: ignore
        except ImportError:
            raise RuntimeError(
                "HEIC 需要 pillow-heif：python3 -m pip install --user pillow-heif"
            )
        pillow_heif.register_heif_opener()

    if ext in RAW_EXTS:
        return open_raw_preview(path)

    return Image.open(path)


def open_raw_preview(path: Path) -> Image.Image:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        raise RuntimeError(
            "RAW 文件需要 exiftool：sudo apt install -y libimage-exiftool-perl"
        )

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        for tag in ("PreviewImage", "JpgFromRaw", "ThumbnailImage"):
            with tmp_path.open("wb") as out:
                result = subprocess.run(
                    [exiftool, "-b", f"-{tag}", str(path)],
                    stdout=out,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            if result.returncode == 0 and tmp_path.stat().st_size > 1024:
                image = Image.open(tmp_path)
                image.load()
                return image.copy()
        raise RuntimeError("无法从 RAW 中提取预览图")
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        log(f"跳过无法解析的 {path.name}：{exc}")
        return {}


# ---------------------------------------------------------------------------
# 扫描与图片处理
# ---------------------------------------------------------------------------

def iter_images(directory: Path) -> Iterable[Path]:
    for path in sorted(directory.rglob("*"), key=lambda p: natural_key(str(p))):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if "assets" in path.parts and "generated" in path.parts:
            continue
        if path.name.startswith("."):
            continue
        if path.suffix.lower() in IMAGE_EXTS | RAW_EXTS | HEIC_EXTS:
            yield path


def find_album_roots(source: Path, depth: int) -> list[Path]:
    if depth == 0:
        return [source] if any(iter_images(source)) else []
    roots: list[Path] = []
    for path in sorted(source.rglob("*"), key=lambda p: natural_key(str(p))):
        if not path.is_dir() or any(part in SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(source)
        if len(rel.parts) != depth:
            continue
        if any(iter_images(path)):
            roots.append(path)
    return roots


def photo_output_dir(output_root: Path, album_slug: str) -> Path:
    return output_root / "assets" / "generated" / album_slug


def process_photo(
    source: Path,
    output_root: Path,
    image_path: Path,
    output_dir: Path,
    slug: str,
    cache: dict[str, Any],
    options_key: str,
    max_edge: int,
    quality: int,
    force: bool,
) -> tuple[Photo | None, bool]:
    """返回 (Photo, 是否使用了缓存)。无法处理的图片返回 (None, False)。"""
    try:
        stat = image_path.stat()
    except OSError:
        return None, False

    cache_key = str(image_path.resolve())
    cached = cache.get(cache_key)
    if (
        not force
        and cached
        and cached.get("options_key") == options_key
        and cached.get("slug") == slug
        and cached.get("mtime_ns") == stat.st_mtime_ns
        and cached.get("size") == stat.st_size
        and cached.get("outputs")
        and all((output_root / item["path"]).exists() for item in cached["outputs"].values())
    ):
        photo = Photo(
            source=image_path,
            rel_source=str(image_path.relative_to(source)),
            digest=cached["digest"],
            width=cached["width"],
            height=cached["height"],
            taken_at=datetime.fromisoformat(cached["taken_at"]) if cached.get("taken_at") else None,
            camera=cached.get("camera", ""),
            lens=cached.get("lens", ""),
            exposure=cached.get("exposure", ""),
            aperture=cached.get("aperture", ""),
            iso=cached.get("iso", ""),
            focal=cached.get("focal", ""),
            outputs=cached["outputs"],
        )
        return photo, True

    try:
        digest = sha1_file(image_path)
        with open_image(image_path) as opened:
            original_mode = opened.mode
            icc_profile = opened.info.get("icc_profile")
            im = ImageOps.exif_transpose(opened)
            metadata = read_exif(opened)
            if metadata["taken_at"] is None:
                metadata["taken_at"] = datetime.fromtimestamp(stat.st_mtime)
            im = to_rgb(im)
            # CMYK / 灰度转换后的 ICC 不再适用，避免浏览器按错误色彩空间解释。
            if original_mode not in ("RGB", "L"):
                icc_profile = None
            original_w, original_h = im.size

            base = im.copy()
            base.thumbnail((max_edge, max_edge), Image.LANCZOS)

            outputs: dict[str, dict[str, Any]] = {}
            current = base
            for edge in (1800, 1100, 480):
                if edge != max_edge and current.width > edge and current.height > edge:
                    current = current.copy()
                    current.thumbnail((edge, edge), Image.LANCZOS)
                elif edge == max_edge:
                    current = base
                else:
                    current = current.copy()
                    current.thumbnail((edge, edge), Image.LANCZOS)

                filename = f"{digest[:12]}-{edge}.jpg"
                out_path = output_dir / filename
                out_path.parent.mkdir(parents=True, exist_ok=True)
                current.save(
                    out_path,
                    "JPEG",
                    quality=quality,
                    optimize=True,
                    progressive=True,
                    icc_profile=icc_profile,
                )
                outputs[str(edge)] = {
                    "path": str(out_path.relative_to(output_root)),
                    "w": current.width,
                    "h": current.height,
                }

            # 以 1100 版本作为 HTML 的默认尺寸
            default = outputs["1100"]
            photo = Photo(
                source=image_path,
                rel_source=str(image_path.relative_to(source)),
                digest=digest,
                width=default["w"],
                height=default["h"],
                taken_at=metadata["taken_at"],
                camera=metadata.get("camera", ""),
                lens=metadata.get("lens", ""),
                exposure=metadata.get("exposure", ""),
                aperture=metadata.get("aperture", ""),
                iso=metadata.get("iso", ""),
                focal=metadata.get("focal", ""),
                outputs=outputs,
            )
            cache[cache_key] = {
                "options_key": options_key,
                "slug": slug,
                "mtime_ns": stat.st_mtime_ns,
                "size": stat.st_size,
                "digest": photo.digest,
                "width": photo.width,
                "height": photo.height,
                "taken_at": photo.taken_at.isoformat() if photo.taken_at else None,
                "camera": photo.camera,
                "lens": photo.lens,
                "exposure": photo.exposure,
                "aperture": photo.aperture,
                "iso": photo.iso,
                "focal": photo.focal,
                "outputs": photo.outputs,
                "original_width": original_w,
                "original_height": original_h,
            }
            return photo, False
    except Exception as exc:
        log(f"跳过 {image_path.relative_to(source)}：{exc}")
        return None, False


def sidecar_caption(image_path: Path, config: dict[str, Any], album_dir: Path) -> str:
    candidates = config.get("captions") or {}
    if isinstance(candidates, dict):
        for key in (image_path.name, image_path.stem, str(image_path.relative_to(album_dir))):
            if key in candidates:
                return str(candidates[key]).strip()

    for suffix in (".txt", ".caption"):
        sidecar = image_path.with_suffix(suffix)
        if sidecar.exists():
            try:
                text = sidecar.read_text(encoding="utf-8").strip()
                return text.splitlines()[0].strip() if text else ""
            except OSError:
                pass
    return ""


def build_photo_caption(photo: Photo, location: str, configured: str) -> str:
    if configured:
        return configured
    parts = [photo.date_label]
    if photo.camera:
        parts.append(photo.camera)
    return " · ".join(p for p in parts if p) or "影像"


# ---------------------------------------------------------------------------
# 册集构建
# ---------------------------------------------------------------------------

def discover_chapter_dirs(album_dir: Path) -> list[Path]:
    dirs = []
    for path in sorted(album_dir.iterdir(), key=lambda p: natural_key(p.name)):
        if not path.is_dir() or path.name in SKIP_DIRS or path.name.startswith("."):
            continue
        if any(iter_images(path)):
            dirs.append(path)
    return dirs


def build_chapter(
    source: Path,
    output_root: Path,
    album_dir: Path,
    chapter_dir: Path | None,
    chapter_title: str,
    chapter_en: str,
    chapter_intro: str,
    chapter_quote: str,
    chapter_quote_cite: str,
    album_slug: str,
    album_config: dict[str, Any],
    album_location: str,
    cache: dict[str, Any],
    options_key: str,
    max_edge: int,
    quality: int,
    force: bool,
) -> Chapter:
    if chapter_dir is None:
        # 只取册集根目录下的直接图片，避免和子章节重复。
        images = [
            p for p in sorted(album_dir.iterdir(), key=lambda p: natural_key(p.name))
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS | RAW_EXTS | HEIC_EXTS
        ]
    else:
        images = list(iter_images(chapter_dir))

    output_dir = photo_output_dir(output_root, album_slug)
    photos: list[Photo] = []
    seen: set[str] = set()

    for image_path in images:
        photo, _ = process_photo(
            source, output_root, image_path, output_dir, album_slug,
            cache, options_key, max_edge, quality, force,
        )
        if photo is None:
            continue
        if photo.digest in seen:
            continue
        seen.add(photo.digest)
        configured = sidecar_caption(
            image_path,
            album_config,
            album_dir,
        )
        photo.location = album_location
        photo.caption = build_photo_caption(photo, album_location, configured)
        photos.append(photo)

    photos.sort(key=lambda p: (p.taken_at or datetime.min, p.rel_source.lower()))

    return Chapter(
        title=chapter_title,
        en=chapter_en,
        intro=chapter_intro,
        quote=chapter_quote,
        quote_cite=chapter_quote_cite,
        photos=photos,
    )


def build_album(
    source: Path,
    output_root: Path,
    album_dir: Path,
    depth: int,
    cache: dict[str, Any],
    options_key: str,
    max_edge: int,
    quality: int,
    force: bool,
    slug_registry: set[str],
) -> Album | None:
    config = load_json(album_dir / "album.json")
    if config.get("hidden") is True:
        return None

    rel = album_dir.relative_to(source)
    default_title = album_dir.name if not rel.parts else display_title(rel, depth)
    default_location = album_dir.name if not rel.parts else derive_location(rel)
    title = str(config.get("title") or default_title).strip()
    subtitle = str(config.get("subtitle") or config.get("en") or "").strip()
    slug = str(config.get("slug") or stable_slug(str(rel))).strip()
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", slug).strip("-")[:60]
    if not slug:
        slug = stable_slug(str(rel))
    if slug in slug_registry:
        slug = f"{slug}-{hashlib.sha1(str(rel).encode('utf-8')).hexdigest()[:6]}"
    slug_registry.add(slug)
    location = str(config.get("location") or default_location).strip()

    chapter_dirs = discover_chapter_dirs(album_dir)
    chapter_config = config.get("chapters") or {}
    if not isinstance(chapter_config, dict):
        chapter_config = {}

    chapters: list[Chapter] = []

    direct_images = [
        p for p in album_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS | RAW_EXTS | HEIC_EXTS
    ]
    if direct_images:
        chapters.append(build_chapter(
            source, output_root, album_dir, None,
            "影像", "Photographs", "",
            "", "",
            slug, config, location,
            cache, options_key, max_edge, quality, force,
        ))

    for chapter_dir in chapter_dirs:
        raw_name = chapter_dir.name
        chapter_meta = chapter_config.get(raw_name) or chapter_config.get(
            re.sub(r"^\d+[\s._-]+", "", raw_name)
        ) or {}
        if not isinstance(chapter_meta, dict):
            chapter_meta = {}
        chapter_title = str(chapter_meta.get("title") or re.sub(
            r"^\s*\d{1,3}[\s._-]+", "", raw_name
        )).strip() or raw_name
        chapter_en = str(chapter_meta.get("en") or chapter_meta.get("subtitle") or "").strip()
        chapter_intro = str(chapter_meta.get("intro") or "").strip()
        quote = chapter_meta.get("quote") or ""
        quote_cite = chapter_meta.get("quote_cite") or ""
        if isinstance(quote, dict):
            quote_cite = quote.get("cite", quote_cite)
            quote = quote.get("text", "")
        chapters.append(build_chapter(
            source, output_root, album_dir, chapter_dir,
            chapter_title, chapter_en, chapter_intro,
            str(quote), str(quote_cite),
            slug, config, location,
            cache, options_key, max_edge, quality, force,
        ))

    chapters = [ch for ch in chapters if ch.photos]
    if not chapters:
        return None

    # 同一册里重复出现的照片只保留第一次。
    seen_digests: set[str] = set()
    for chapter in chapters:
        unique_photos = []
        for photo in chapter.photos:
            if photo.digest in seen_digests:
                continue
            seen_digests.add(photo.digest)
            unique_photos.append(photo)
        chapter.photos = unique_photos
    chapters = [ch for ch in chapters if ch.photos]
    if not chapters:
        return None

    all_photos = [p for ch in chapters for p in ch.photos]
    all_photos.sort(key=lambda p: (p.taken_at or datetime.min, p.rel_source.lower()))

    cover: Photo | None = None
    cover_name = config.get("cover")
    if cover_name:
        for photo in all_photos:
            if Path(photo.rel_source).name == Path(str(cover_name)).name:
                cover = photo
                break
    cover = cover or all_photos[0]

    year = str(config.get("year") or derive_year(rel, all_photos)).strip()
    date_range = ""
    dates = [p.taken_at for p in all_photos if p.taken_at]
    if dates:
        lo, hi = min(dates), max(dates)
        date_range = lo.strftime("%Y.%m.%d") if lo.date() == hi.date() else f"{lo:%Y.%m.%d} — {hi:%Y.%m.%d}"

    prologue = str(config.get("prologue") or "").strip()
    if not prologue:
        prologue = (
            f"这一册由 NAS 文件夹自动整理，收录 {len(all_photos)} 张照片"
            + (f"，拍摄于 {date_range}" if date_range else "")
            + "。没有经过挑选，按拍摄时间排列。"
        )

    signature = str(config.get("signature") or "").strip()
    if not signature:
        signature = f"拾光 · 自动整理于 {datetime.now():%Y 年 %m 月}"

    description = str(config.get("description") or "").strip()
    if not description:
        first = re.split(r"(?<=[。！？!?])", prologue)[0].strip()
        description = first[:90]

    return Album(
        source=album_dir,
        rel=str(rel),
        title=title,
        subtitle=subtitle,
        slug=slug,
        year=year,
        location=location,
        prologue=prologue,
        signature=signature,
        description=description,
        chapters=chapters,
        cover=cover,
        config=config,
    )


# ---------------------------------------------------------------------------
# HTML 渲染
# ---------------------------------------------------------------------------

def header_html(active: str, overlay: bool = False) -> str:
    def nav(href: str, label: str, en: str) -> str:
        current = ' aria-current="page"' if active == href else ""
        return f'<a href="{href}"{current}>{label} <span>{en}</span></a>'

    header_kind = "overlay" if overlay else "paper"
    return f"""  <header class="site-header" data-header="{header_kind}">
    <div class="shell header-inner">
      <a class="brand" href="index.html" aria-label="拾光画册首页">
        <span class="brand-cn">拾光</span>
        <span class="brand-en">SHIGUANG</span>
      </a>
      <nav class="site-nav" id="site-nav" aria-label="主导航">
        {nav("index.html", "首页", "Home")}
        {nav("albums.html", "册集", "Albums")}
        {nav("gallery.html", "照片库", "Archive")}
        {nav("about.html", "关于", "About")}
      </nav>
      <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="site-nav">
        <span class="menu-label">菜单</span>
        <span class="menu-icon" aria-hidden="true"><i></i><i></i></span>
      </button>
    </div>
  </header>"""


def footer_html() -> str:
    return """  <footer class="site-footer">
    <div class="shell footer-top">
      <div>
        <p class="footer-kicker">STAY IN THE LIGHT</p>
        <p class="footer-title">把日子过成<br>值得翻页的样子。</p>
      </div>
      <div class="footer-side">
        <nav class="footer-nav" aria-label="页脚导航">
          <a href="albums.html">全部册集</a>
          <a href="gallery.html">照片库</a>
          <a href="album-shanhai.html">山海之间</a>
          <a href="album-city.html">城市切片</a>
          <a href="album-daily.html">日常的光</a>
          <a href="album-snow.html">雪线以北</a>
          <a href="about.html">关于画册</a>
          <a href="mailto:hello@shiguang.example">联系我们</a>
        </nav>
        <a class="footer-mail" href="mailto:hello@shiguang.example">hello@shiguang.example</a>
      </div>
    </div>
    <div class="shell footer-bottom">
      <span>© 2026 拾光画册 · SHIGUANG</span>
      <span>电子画册 · Vol. 01</span>
      <a href="#top">回到顶部 ↑</a>
    </div>
  </footer>"""


def srcset_for(photo: Photo) -> str:
    items = []
    for edge in ("480", "1100", "1800"):
        item = photo.outputs.get(edge)
        if item:
            items.append(f'{e(item["path"])} {item["w"]}w')
    return ", ".join(items)


def sizes_for(css_class: str) -> str:
    if "full-bleed" in css_class:
        return "100vw"
    if "inset" in css_class:
        return "(max-width: 760px) 100vw, 760px"
    if "portrait" in css_class:
        return "(max-width: 760px) 100vw, 780px"
    return "(max-width: 760px) 100vw, 900px"


def figure_html(photo: Photo, number: int, css_class: str = "photo", in_grid: bool = False) -> str:
    default = photo.default
    if photo.caption and photo.location:
        separator = " " if photo.caption.endswith(("。", "！", "？", ".", "!", "?")) else "，"
        alt = f"{photo.caption}{separator}{photo.location}"
    else:
        alt = photo.caption or photo.location
    location_attr = f' data-location="{e(photo.location)}"' if photo.location else ""
    loading = "lazy"
    sizes = "50vw" if in_grid else sizes_for(css_class)

    return f"""          <figure class="{e(css_class)}">
            <a class="photo-link" href="{e(photo.large["path"])}"
               data-caption="{e(photo.caption)}"{location_attr}>
              <img src="{e(default["path"])}"
                   srcset="{e(srcset_for(photo))}"
                   sizes="{e(sizes)}"
                   alt="{e(alt)}" width="{default["w"]}" height="{default["h"]}" loading="{loading}">
            </a>
            <figcaption>
              <span class="cap-no">No. {number:02d}</span>
              <span>{e(photo.caption)}</span>
              <span class="cap-loc">{e(photo.location)}</span>
            </figcaption>
          </figure>"""


def is_portrait(photo: Photo) -> bool:
    return photo.width / max(photo.height, 1) < 0.95


def photos_html(photos: list[Photo], start_number: int = 1) -> str:
    blocks: list[str] = []
    i = 0
    number = start_number
    while i < len(photos):
        photo = photos[i]
        ratio = photo.width / max(photo.height, 1)

        # 每章第一张保持整幅，后续成对的竖图组成双栏。
        if (
            i + 1 < len(photos)
            and i > 0
            and is_portrait(photo)
            and is_portrait(photos[i + 1])
            and i % 4 != 0
        ):
            blocks.append(
                '          <div class="photo-grid">\n'
                + figure_html(photo, number, "photo", in_grid=True)
                + "\n"
                + figure_html(photos[i + 1], number + 1, "photo", in_grid=True)
                + "\n          </div>"
            )
            i += 2
            number += 2
            continue

        if i == 0:
            css_class = "photo"
        elif ratio >= 1.75 and i % 6 == 0:
            css_class = "photo photo--full-bleed"
        elif ratio < 0.9:
            css_class = "photo photo--portrait"
        elif ratio >= 1.45:
            css_class = "photo photo--inset-wide"
        elif i % 4 == 0:
            css_class = "photo photo--inset"
        else:
            css_class = "photo"

        blocks.append(figure_html(photo, number, css_class))
        i += 1
        number += 1

    return "\n\n".join(blocks)


def chapter_html(chapter: Chapter, index: int, is_last: bool, start_number: int) -> str:
    chapter_id = f"chapter-{index}"
    last_class = " chapter--last" if is_last else ""
    en_label = chapter.en or "Photographs"
    en_small = f"<small>{e(chapter.en)}</small>" if chapter.en else ""
    intro = f"\n          <p>{e(chapter.intro)}</p>" if chapter.intro else ""
    quote = ""
    if chapter.quote:
        cite = f"<cite>{e(chapter.quote_cite)}</cite>" if chapter.quote_cite else ""
        quote = f"""
        <blockquote class="pull-quote">
          “{e(chapter.quote)}”
          {cite}
        </blockquote>"""

    return f"""      <section class="chapter shell reveal{last_class}" aria-labelledby="{chapter_id}">
        <div class="chapter-head">
          <p class="chapter-no">Chapter {index:02d}<span>{e(en_label)}</span></p>
          <h2 id="{chapter_id}">{e(chapter.title)}{en_small}</h2>{intro}
        </div>

{photos_html(chapter.photos, start_number)}
{quote}
      </section>"""


def album_html(album: Album, index: int, total: int, next_album: Album | None) -> str:
    cover = album.cover.large
    next_link = (
        f"""          <a class="next-album" href="{e(next_album.page_name)}">
            <span class="next-label"><span>下一册 / Next Album</span><span>{index + 1:02d} / {total:02d}</span></span>
            <h2>{e(next_album.title)}</h2>
            <p>{e(next_album.subtitle or next_album.year)}</p>
            <span class="next-arrow">继续翻阅 →</span>
          </a>"""
        if next_album
        else """          <a class="next-album" href="gallery.html">
            <span class="next-label"><span>返回 / Back</span><span>Archive</span></span>
            <h2>照片库</h2>
            <p>所有自动整理的册集</p>
            <span class="next-arrow">返回目录 →</span>
          </a>"""
    )

    end_quote = str(album.config.get("end_quote") or "").strip()
    if not end_quote:
        end_quote = "照片会记得我们走过的地方，<span><br>也会记得当时的光。</span>"

    meta_location = album.location or album.title
    lead = str(album.config.get("lead") or "").strip() or f"{album.count} 个片刻，按时间排列。"
    subtitle_html = f'<p class="album-en">{e(album.subtitle)}</p>' if album.subtitle else ""
    chapter_blocks = []
    photo_number = 1
    for i, ch in enumerate(album.chapters, start=1):
        chapter_blocks.append(
            chapter_html(ch, i, i == len(album.chapters), photo_number)
        )
        photo_number += len(ch.photos)
    chapters = "\n\n".join(chapter_blocks)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{e(album.title)} · 拾光画册</title>
  <meta name="description" content="{e(album.description)}">
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <script>document.documentElement.classList.add("js");</script>
  <link rel="stylesheet" href="css/style.css">
</head>
<body id="top" class="page-album album-auto">
  <a class="skip-link" href="#main">跳到主要内容</a>

{header_html("gallery.html", overlay=True)}

  <div class="reading-progress" aria-hidden="true"><span></span></div>

  <main id="main">
    <article class="album">
      <header class="album-hero">
        <img class="album-hero-bg" src="{e(cover["path"])}" alt="{e(album.title)}封面"
             width="{cover["w"]}" height="{cover["h"]}">
        <div class="album-hero-top">
          <div class="shell album-hero-actions">
            <a class="back-link" href="gallery.html">返回照片库</a>
            <button class="print-link" type="button" data-print>打印 / 存为 PDF</button>
          </div>
        </div>
        <div class="album-hero-content">
          <div class="shell">
            <p class="eyebrow">Auto Album · {e(album.year or album.date_range)}</p>
            <h1>{e(album.title)}</h1>
            {subtitle_html}
            <div class="album-hero-meta">
              <span>{e(meta_location)}</span>
              <span>{album.count} 幅影像</span>
              <span>约 {album.reading_minutes} 分钟阅读</span>
            </div>
          </div>
        </div>
        <p class="scroll-note" aria-hidden="true">向下翻阅 · SCROLL TO UNFOLD</p>
      </header>

      <section class="album-opening shell reveal" aria-labelledby="prologue-title">
        <dl class="album-facts">
          <div><dt>年份</dt><dd>{e(album.year or "—")}</dd></div>
          <div><dt>地点</dt><dd>{e(album.location or "—")}</dd></div>
          <div><dt>影像</dt><dd>{album.count} 幅</dd></div>
          <div><dt>页数</dt><dd>{album.pages} 页</dd></div>
          <div><dt>介质</dt><dd>数码 · 自动整理</dd></div>
        </dl>
        <div class="album-intro">
          <span class="kicker">卷首语 / Prologue</span>
          <h2 class="lead" id="prologue-title">{e(lead)}</h2>
          <p>{e(album.prologue)}</p>
          <p class="album-signature">{e(album.signature)}</p>
        </div>
      </section>

{chapters}

      <section class="album-end">
        <div class="shell album-end-inner reveal">
          <div>
            <p class="kicker">End Note · {index:02d} / {total:02d}</p>
            <blockquote>
              {end_quote}
            </blockquote>
          </div>
{next_link}
        </div>
      </section>
    </article>
  </main>

{footer_html()}

  <script src="js/main.js"></script>
</body>
</html>
"""


def gallery_html(albums: list[Album], depth: int) -> str:
    total_photos = sum(a.count for a in albums)
    years = sorted({a.year for a in albums if a.year})
    year_label = years[-1] if years else "—"
    depth_text = {
        0: "照片目录本身是一册",
        1: "每个顶层文件夹是一册",
        2: "每个第二层文件夹是一册",
        3: "每个第三层文件夹是一册",
    }.get(depth, f"每个第 {depth} 层文件夹是一册")
    items = []
    for index, album in enumerate(albums, start=1):
        cover = album.cover.default
        subtitle_html = f'<p class="album-en">{e(album.subtitle)}</p>' if album.subtitle else ""
        items.append(f"""        <article class="archive-item reveal">
          <a class="archive-visual" href="{e(album.page_name)}" aria-label="翻阅《{e(album.title)}》">
            <span class="visual-index">{index:02d}</span>
            <img src="{e(cover["path"])}" alt="{e(album.title)}封面"
                 width="{cover["w"]}" height="{cover["h"]}" loading="lazy">
          </a>
          <div class="archive-copy">
            <span class="archive-no">Auto Album · {e(album.year or album.date_range)}</span>
            <h2>{e(album.title)}</h2>
            {subtitle_html}
            <p>{e(album.description)}</p>
            <div class="archive-meta">
              <span>{e(album.location or "—")}</span>
              <span>{album.count} 幅影像</span>
              <span>{album.pages} 页</span>
            </div>
            <span class="archive-link">翻阅这一册</span>
          </div>
        </article>""")

    if not items:
        items.append("""        <div class="archive-end reveal">
          <p><span class="pulse-dot" aria-hidden="true"></span>还没有可生成的册集。把照片放进 NAS 文件夹，再运行一次脚本。</p>
        </div>""")

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>照片库 · 拾光画册</title>
  <meta name="description" content="由 NAS 文件夹自动整理的照片库，按册集与章节排列。">
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <script>document.documentElement.classList.add("js");</script>
  <link rel="stylesheet" href="css/style.css">
</head>
<body id="top" class="page-archive">
  <a class="skip-link" href="#main">跳到主要内容</a>

{header_html("gallery.html")}

  <main id="main">
    <section class="page-intro shell">
      <div class="page-intro-head">
        <div class="reveal">
          <p class="eyebrow">Auto Archive · NAS</p>
          <h1>照片库<small>The Archive</small></h1>
        </div>
        <aside class="page-intro-aside reveal reveal-delay-1">
          <p>
            这里没有手工选片。{e(depth_text)}，子文件夹是一章；
            照片按 EXIF 拍摄时间排序，自动生成封面、图注与缩略图。
          </p>
          <div class="page-stats" aria-label="照片库数据">
            <div><strong>{len(albums):02d}</strong><span>自动册集</span></div>
            <div><strong>{total_photos}</strong><span>收录影像</span></div>
            <div><strong>{e(year_label)}</strong><span>最近年份</span></div>
          </div>
        </aside>
      </div>
    </section>

    <section class="archive" aria-label="自动册集列表">
      <div class="shell">
{chr(10).join(items)}

        <div class="archive-end reveal">
          <p><span class="pulse-dot" aria-hidden="true"></span>此页由 NAS 文件夹自动生成 · 增删照片后重新运行脚本即可</p>
          <a class="text-link" href="albums.html">返回手工册集</a>
        </div>
      </div>
    </section>
  </main>

{footer_html()}

  <script src="js/main.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# 写文件与清理
# ---------------------------------------------------------------------------

def write_if_changed(path: Path, content: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            if path.read_text(encoding="utf-8") == content:
                return False
        except OSError:
            pass
    path.write_text(content, encoding="utf-8")
    return True


def cleanup_old(output: Path, old_files: list[str], new_files: set[str]) -> None:
    for rel in old_files:
        if rel in new_files:
            continue
        target = (output / rel).resolve()
        try:
            target.relative_to(output.resolve())
        except ValueError:
            continue
        if target.is_file():
            target.unlink()
        # 清理空的生成目录
        parent = target.parent
        generated_root = (output / "assets" / "generated").resolve()
        while parent != generated_root and generated_root in parent.parents:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="扫描 NAS 照片文件夹，生成静态画册页面。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--source", help="照片根目录，例如 /mnt/nas/photos")
    parser.add_argument("--config", default=str(ROOT / "gallery.config.json"),
                        help="可选配置文件")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT),
                        help="输出目录（网站根目录）")
    parser.add_argument("--album-depth", type=int, default=None,
                        help="第几层文件夹算一册：1=顶层，2=第二层，0=source 本身")
    parser.add_argument("--max-edge", type=int, default=None,
                        help="大图最长边像素")
    parser.add_argument("--quality", type=int, default=None,
                        help="JPEG 质量 1-100")
    parser.add_argument("--cache", default=str(DEFAULT_CACHE),
                        help="构建缓存文件")
    parser.add_argument("--force", action="store_true",
                        help="忽略缓存，重新处理所有图片")
    parser.add_argument("--dry-run", action="store_true",
                        help="只扫描和统计，不写文件")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_json(Path(args.config))

    source_value = args.source or config.get("source")
    if not source_value:
        die("请用 --source 指定照片目录，或在 gallery.config.json 里设置 source")
    source = Path(source_value).expanduser().resolve()
    if not source.is_dir():
        die(f"照片目录不存在或不是目录：{source}")

    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    depth = args.album_depth if args.album_depth is not None else int(config.get("album_depth", 1))
    max_edge = args.max_edge if args.max_edge is not None else int(config.get("max_edge", 1800))
    quality = args.quality if args.quality is not None else int(config.get("quality", 82))
    if depth < 0:
        die("--album-depth 不能小于 0")
    if not 1 <= quality <= 100:
        die("--quality 必须在 1 到 100 之间")

    cache_path = Path(args.cache).expanduser().resolve()
    cache_doc: dict[str, Any] = load_json(cache_path)
    options_key = f"v2:{max_edge}:{quality}:1800,1100,480"
    if cache_doc.get("options_key") != options_key:
        cache: dict[str, Any] = {}
    else:
        cache = cache_doc.get("photos") or {}
    old_files = cache_doc.get("files") or []

    print(f"照片目录：{source}")
    print(f"输出目录：{output}")
    print(f"册集层级：{depth}  ·  大图 {max_edge}px  ·  JPEG {quality}")
    print()

    roots = find_album_roots(source, depth)
    if not roots:
        if args.dry_run:
            print("没有找到包含照片的册集文件夹")
            return
        print("没有找到包含照片的册集文件夹，生成空白照片库。")
        write_if_changed(output / "gallery.html", gallery_html([], depth))
        return

    if args.dry_run:
        total = sum(1 for root in roots for _ in iter_images(root))
        print(f"试运行：{len(roots)} 个册集文件夹，约 {total} 张照片")
        for root in roots:
            print(f"  - {root.relative_to(source)}")
        return

    albums: list[Album] = []
    slug_registry: set[str] = set()
    for root in roots:
        rel = root.relative_to(source)
        print(f"扫描：{rel}")
        album = build_album(
            source, output, root, depth, cache, options_key,
            max_edge, quality, args.force, slug_registry,
        )
        if album:
            albums.append(album)
            print(f"  ✓ {album.title} · {album.count} 张 · {len(album.chapters)} 章")
        else:
            print("  - 跳过（没有可用照片）")

    if not albums:
        print("所有文件夹都没有可用照片，生成空白照片库。")
        write_if_changed(output / "gallery.html", gallery_html([], depth))
        return

    # 新册在前；同一年按标题排序。
    albums.sort(key=lambda a: (a.year or "", a.title), reverse=True)

    new_files: set[str] = {"gallery.html"}
    pages: dict[str, str] = {"gallery.html": gallery_html(albums, depth)}

    for index, album in enumerate(albums, start=1):
        next_album = albums[index] if index < len(albums) else None
        pages[album.page_name] = album_html(album, index, len(albums), next_album)
        new_files.add(album.page_name)
        for photo in album.photos:
            for item in photo.outputs.values():
                new_files.add(item["path"])

    if args.dry_run:
        print()
        print(f"试运行：{len(albums)} 册，{sum(a.count for a in albums)} 张照片")
        print(f"将生成 {len(pages)} 个页面，{len(new_files) - len(pages)} 个图片文件")
        return

    changed = 0
    for name, content in pages.items():
        if write_if_changed(output / name, content):
            changed += 1
            print(f"写入：{name}")

    cleanup_old(output, old_files, new_files)

    active_keys = {str(p.source.resolve()) for a in albums for p in a.photos}
    cache = {key: value for key, value in cache.items() if key in active_keys}

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_doc = {
        "options_key": options_key,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(source),
        "files": sorted(new_files),
        "photos": cache,
    }
    cache_path.write_text(
        json.dumps(cache_doc, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"完成：{len(albums)} 册，{sum(a.count for a in albums)} 张照片，{changed} 个页面有更新")
    print(f"打开：{output / 'gallery.html'}")
    print(f"缓存：{cache_path}")


if __name__ == "__main__":
    main()
