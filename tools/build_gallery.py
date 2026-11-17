#!/usr/bin/env python3
"""
水上行走 · NAS 照片自动排版

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

    gallery.html               # 相册目录
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import book_photos  # noqa: E402

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
    parts.extend(
        [
            photo.aperture,
            photo.exposure,
            photo.iso,
            photo.focal,
        ]
    )
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

    raw_hidden = album_config.get("hidden_photos") or []
    if isinstance(raw_hidden, str):
        raw_hidden = [raw_hidden]
    hidden_names = (
        {Path(str(name)).name for name in raw_hidden}
        if isinstance(raw_hidden, (list, tuple))
        else set()
    )
    images = [p for p in images if p.name not in hidden_names]

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
        signature = f"水上行走 · 自动整理于 {datetime.now():%Y 年 %m 月}"

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
      <a class="brand" href="index.html" aria-label="水上行走首页">
        <span class="brand-cn">水上行走</span>
        <span class="brand-en">WALK ON WATER</span>
      </a>
      <nav class="site-nav" id="site-nav" aria-label="主导航">
        {nav("index.html", "首页", "Home")}
        {nav("albums.html", "册集", "Albums")}
        {nav("gallery.html", "相册", "Archive")}
        {nav("about.html", "关于", "About")}
      </nav>
      <button class="menu-toggle" type="button" aria-expanded="false" aria-controls="site-nav">
        <span class="menu-label">菜单</span>
        <span class="menu-icon" aria-hidden="true"><i></i><i></i></span>
      </button>
    </div>
  </header>"""


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
    loading = "eager"
    sizes = "50vw" if in_grid else sizes_for(css_class)
    from urllib.parse import quote as _urlquote
    original_href = "originals/" + _urlquote(str(photo.rel_source))
    photo_file = Path(photo.rel_source).name
    cap_date = photo.date_label
    cap_text = photo.caption
    if cap_date and cap_text.startswith(cap_date):
        cam_text = cap_text[len(cap_date):].lstrip(" ·")
    else:
        cam_text = cap_text
    cam_html = f'<span class="cap-cam">{e(cam_text)}</span>' if cam_text else ""
    right_html = ""
    if photo.location:
        right_html += f'<span class="cap-loc">{e(photo.location)}</span>'
    if cap_date:
        right_html += f'<span class="cap-time">{e(cap_date)}</span>'

    return f"""          <figure class="{e(css_class)}">
            <a class="photo-link" href="{e(original_href)}"
               data-caption="{e(photo.caption)}"{location_attr}
               data-photo-file="{e(photo_file)}">
              <img src="{e(default["path"])}"
                   srcset="{e(srcset_for(photo))}"
                   sizes="{e(sizes)}"
                   alt="{e(alt)}" width="{default["w"]}" height="{default["h"]}" loading="{loading}">
            </a>
            <figcaption>
              <span class="cap-left"><span class="cap-no">No. {number:02d}</span>{cam_html}</span>
              <span class="cap-right">{right_html}</span>
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
    return f"""      <section class="chapter shell{last_class}" aria-labelledby="{chapter_id}">
        <div class="chapter-head">
          <p class="chapter-no">Chapter {index:02d}<span>{e(en_label)}</span></p>
          <h2 id="{chapter_id}">{e(chapter.title)}{en_small}</h2>
        </div>

{photos_html(chapter.photos, start_number)}
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
        else f"""          <a class="next-album" href="gallery.html">
            <span class="next-label"><span>返回 / Back</span><span>{total:02d} / {total:02d}</span></span>
            <h2>相册</h2>
            <span class="next-arrow">返回目录 →</span>
          </a>"""
    )

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
  <meta name="theme-color" content="#141310">
  <title>{e(album.title)} · 水上行走</title>
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
            <a class="back-link" href="gallery.html">返回相册</a>
          </div>
        </div>
        <div class="album-hero-content">
          <div class="shell album-hero-grid">
            <div class="album-hero-main">
              <p class="eyebrow">Auto Album · {e(album.year or album.date_range)}</p>
              <h1>{e(album.title)}</h1>
              {subtitle_html}
              <div class="album-hero-meta">
                <span>约 {album.reading_minutes} 分钟阅读</span>
              </div>
            </div>
            <dl class="album-facts album-facts--hero">
              <div><dt>年份</dt><dd>{e(album.year or "—")}</dd></div>
              <div><dt>地点</dt><dd>{e(album.location or "—")}</dd></div>
              <div><dt>影像</dt><dd>{album.count} 幅</dd></div>
              <div><dt>页数</dt><dd>{album.pages} 页</dd></div>
              <div><dt>介质</dt><dd>数码 · 自动整理</dd></div>
            </dl>
          </div>
        </div>
      </header>

{chapters}

      <section class="album-end">
        <div class="shell album-end-inner">
{next_link}
        </div>
      </section>
    </article>
  </main>


  <script src="js/main.js"></script>
</body>
</html>
"""


def gallery_html(albums: list[Album], depth: int) -> str:
    total_photos = sum(a.count for a in albums)
    years = sorted({a.year for a in albums if a.year})
    year_label = years[-1] if years else "—"
    items = []
    for index, album in enumerate(albums, start=1):
        cover = album.cover.default
        orientation = "is-portrait" if cover["h"] > cover["w"] else "is-landscape"
        subtitle = (album.subtitle or "").strip()
        subtitle_html = (
            f'<p class="album-en">{e(subtitle)}</p>'
            if subtitle and subtitle != album.title
            else ""
        )
        location = (album.location or "").strip()
        location_html = (
            f"<span>{e(location)}</span>"
            if location and location != album.title
            else ""
        )
        items.append(f"""        <article class="archive-item {orientation} reveal">
          <a class="archive-visual" href="{e(album.page_name)}" aria-label="翻阅《{e(album.title)}》" style="--cover-ratio: {cover["w"]} / {cover["h"]}">
            <span class="visual-index">{index:02d}</span>
            <img src="{e(cover["path"])}" alt="{e(album.title)}封面"
                 width="{cover["w"]}" height="{cover["h"]}" loading="lazy">
          </a>
          <div class="archive-copy">
            <span class="archive-no">Auto Album · {e(album.year or album.date_range)}</span>
            <h2>{e(album.title)}</h2>
            {subtitle_html}
            <div class="archive-meta">
              {location_html}
              <span>{album.count} 幅影像</span>
            </div>
          </div>
        </article>""")

    if not items:
        items.append('        <div class="archive-end reveal"></div>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#141310">
  <title>相册 · 水上行走</title>
  <meta name="description" content="相册。">
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <script>document.documentElement.classList.add("js");</script>
  <link rel="stylesheet" href="css/style.css">
</head>
<body id="top" class="page-archive page-gallery">
  <a class="skip-link" href="#main">跳到主要内容</a>

{header_html("gallery.html")}

  <main id="main">
    <section class="page-intro shell">
      <div class="page-intro-head">
        <div class="reveal">
          <h1>相册<small>The Archive</small></h1>
        </div>
        <aside class="page-intro-aside reveal reveal-delay-1">
          <div class="page-stats" aria-label="相册数据">
            <div><strong>{len(albums):02d}</strong><span>自动册集</span></div>
            <div><strong>{total_photos}</strong><span>收录影像</span></div>
            <div><strong>{e(year_label)}</strong><span>最近年份</span></div>
          </div>
        </aside>
      </div>
    </section>

    <section class="archive" aria-label="册集">
      <div class="shell">
{chr(10).join(items)}
      </div>
    </section>
  </main>


  <script src="js/main.js"></script>
</body>
</html>
"""


BOOK_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#141310">
  <title>__BOOK_TITLE__ · 水上行走</title>
  <meta name="description" content="可在线翻阅的摄影画册。">
  <link rel="icon" href="assets/favicon.svg" type="image/svg+xml">
  <script>document.documentElement.classList.add("js");</script>
  <link rel="stylesheet" href="css/style.css">
</head>
<body class="page-book">
  <a class="book-back" href="index.html" aria-label="返回相册">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M15 5 8 12l7 7"/></svg>
  </a>

  <section class="cover-view" id="cover-view" aria-label="画册封面">
    <button class="cover-book" id="cover-enter" type="button" aria-label="打开画册">
      <span class="cover-book-spine" aria-hidden="true"></span>
      <span class="cover-book-face">
        <span class="cover-book-kicker">Photography Book</span>
        <span class="cover-book-title">__BOOK_TITLE__</span>
        <span class="cover-book-author">摄影　__BOOK_AUTHOR__</span>
        <span class="cover-book-year">__BOOK_YEAR__</span>
      </span>
      <span class="cover-book-edge" aria-hidden="true"></span>
    </button>
    <span class="cover-hint">点击打开</span>
  </section>

  <main class="book-stage" id="book-stage" hidden>
    <div class="book-bar">
      <button class="book-mini" id="book-cover" type="button">封面</button>
      <button class="book-mini" id="book-toc" type="button">目录</button>
      <span class="book-chapter" id="book-chapter"></span>
      <span class="book-page-label" id="book-page-label"></span>
    </div>

    <button class="book-flip book-flip--prev" id="book-prev" type="button" aria-label="上一页">‹</button>
    <div class="book" id="book-volume">
      <div class="book-static book-static--left" id="book-static-left"></div>
      <div class="book-static book-static--right" id="book-static-right"></div>
      <div class="book-leaves" id="book-leaves"></div>
      <div class="book-spine" aria-hidden="true"></div>
    </div>
    <button class="book-flip book-flip--next" id="book-next" type="button" aria-label="下一页">›</button>
  </main>

  <aside class="book-toc" id="book-toc-panel" aria-label="目录" hidden>
    <button class="book-toc-close" id="book-toc-close" type="button" aria-label="关闭目录">×</button>
    <p class="book-toc-kicker">Contents</p>
    <h2 class="book-toc-title">目录</h2>
    <div class="book-toc-grid" id="book-toc-grid"></div>
  </aside>

  <script>window.BOOK_PHOTOS = __BOOK_PHOTOS__; window.BOOK_META = __BOOK_META__;</script>
  <script>
  (function () {
    "use strict";

    var photos = window.BOOK_PHOTOS || [];
    var meta = window.BOOK_META || {};
    var coverView = document.getElementById("cover-view");
    var coverEnter = document.getElementById("cover-enter");
    var coverBook = document.querySelector(".cover-book");
    var bookView = document.getElementById("book-stage");
    var leavesBox = document.getElementById("book-leaves");
    var staticLeft = document.getElementById("book-static-left");
    var staticRight = document.getElementById("book-static-right");
    var volume = document.getElementById("book-volume");
    var prevBtn = document.getElementById("book-prev");
    var nextBtn = document.getElementById("book-next");
    var labelEl = document.getElementById("book-page-label");
    var chapterEl = document.getElementById("book-chapter");
    var tocPanel = document.getElementById("book-toc-panel");
    var tocGrid = document.getElementById("book-toc-grid");
    var tocBtn = document.getElementById("book-toc");
    var tocClose = document.getElementById("book-toc-close");
    var coverBtn = document.getElementById("book-cover");
    var mobileQuery = window.matchMedia("(max-width: 760px)");
    var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    var spreads = [];
    var leaves = [];
    var index = 0;
    var side = 0;
    var animating = false;

    function pad(n) { return n < 10 ? "0" + n : String(n); }
    function isMobile() { return mobileQuery.matches; }

    function chapterOf(p) { return (p && p.album) || meta.album || "画册"; }

    function ratioOf(p) { return (p.w || 3) / (p.h || 2); }
    function dirOf(p) {
      var r = ratioOf(p);
      if (r < 0.95) return "portrait";
      if (r < 1.15) return "square";
      if (r >= 1.45 && r <= 1.55) return "classic";
      if (r < 1.45) return "landscape";
      return "wide";
    }
    function variantFor(d) { return d === "classic" ? "landscape" : d; }
    function photoDesc(p, d) { return { kind: "photo", photo: p, variant: variantFor(d) }; }
    function blankDesc() { return { kind: "blank" }; }

    // 版式节奏：竖幅单/双页、横幅双图、跨页大图、横幅单页、留白页交替。
    // 竖幅一律单独一页或双竖图；横图分两类：接近 3:2 且间隔足够的才跨页，
    // 其余横图做单页大图或双图组合，避免全部硬塞进跨页。
    var plans = ["pair", "portrait", "pair", "single", "blank", "pair"];
    var cursor = 0;
    var lastType = "";
    var sinceSpread = 9;
    var turn = 0;

    while (cursor < photos.length) {
      var p = photos[cursor];
      var q = photos[cursor + 1];
      var d = dirOf(p);
      var d2 = q ? dirOf(q) : null;
      var plan = plans[turn % plans.length];
      var type, left, right, used = 1;

      if (d === "portrait") {
        if (d2 === "portrait" && chapterOf(q) === chapterOf(p)) {
          type = "portrait-pair";
          left = photoDesc(p, d);
          right = photoDesc(q, d2);
          used = 2;
        } else {
          type = "portrait-single";
          left = photoDesc(p, d);
          right = blankDesc();
        }
      } else if (d === "classic" && sinceSpread >= 4 && lastType !== "spread") {
        type = "spread";
        left = { kind: "spread", photo: p, half: "left" };
        right = { kind: "spread", photo: p, half: "right" };
        sinceSpread = 0;
      } else if (plan === "blank") {
        type = "blank";
        left = blankDesc();
        right = blankDesc();
        used = 0;
      } else if (d2 && d2 !== "portrait" && chapterOf(q) === chapterOf(p) && plan !== "single" && lastType !== "pair") {
        type = "pair";
        left = photoDesc(p, d);
        right = photoDesc(q, d2);
        used = 2;
      } else {
        type = "single";
        left = photoDesc(p, d);
        right = blankDesc();
      }

      if (type === lastType && type === "single" && d2 && d2 !== "portrait" && chapterOf(q) === chapterOf(p)) {
        type = "pair";
        left = photoDesc(p, d);
        right = photoDesc(q, d2);
        used = 2;
      }

      spreads.push({ left: left, right: right, chapter: chapterOf(p), type: type });
      cursor += used;
      lastType = type;
      sinceSpread++;
      turn++;
    }
    if (!spreads.length) {
      spreads.push({ left: blankDesc(), right: blankDesc(), chapter: meta.album || "画册", type: "blank" });
    }
    var chapters = [];
    spreads.forEach(function (sp, i) {
      var last = chapters[chapters.length - 1];
      if (!last || last.name !== sp.chapter) {
        chapters.push({ name: sp.chapter, from: i, to: i });
      } else {
        last.to = i;
      }
    });

    var withDividers = [];
    spreads.forEach(function (sp, i) {
      chapters.forEach(function (ch) {
        if (ch.from === i && chapters.indexOf(ch) > 0) {
          withDividers.push({
            left: { kind: "chapter", chapter: ch.name, number: chapters.indexOf(ch) + 1 },
            right: { kind: "blank" },
            chapter: ch.name
          });
        }
      });
      withDividers.push(sp);
    });
    spreads = withDividers;

    function currentChapter() {
      for (var i = index; i >= 0; i--) {
        if (spreads[i] && spreads[i].left.kind === "chapter") {
          return { number: spreads[i].left.number, name: spreads[i].left.chapter };
        }
      }
      return { number: 1, name: meta.album || "画册" };
    }

    function makePage(desc, pageSide) {
      var node = document.createElement("div");
      node.className = "book-page book-page--" + pageSide;
      if (desc.kind === "blank") {
        node.classList.add("book-page--blank");
        return node;
      }
      if (desc.kind === "chapter") {
        node.classList.add("book-page--chapter");
        var mark = document.createElement("div");
        mark.className = "book-chapter-mark";
        var num = document.createElement("span");
        num.className = "book-chapter-no";
        num.textContent = pad(desc.number);
        var name = document.createElement("span");
        name.className = "book-chapter-name";
        name.textContent = desc.chapter;
        mark.appendChild(num);
        mark.appendChild(name);
        node.appendChild(mark);
        return node;
      }
      if (desc.kind === "spread") {
        node.classList.add("book-page--spread");
        var bg = document.createElement("div");
        bg.className = "book-spread-image";
        bg.setAttribute("data-bg", desc.photo.src);
        bg.style.backgroundPosition = desc.half === "left" ? "left center" : "right center";
        node.appendChild(bg);
        return node;
      }
      node.classList.add("book-page--photo", "book-page--" + desc.variant);
      var fig = document.createElement("figure");
      fig.className = "book-photo";
      var a = document.createElement("a");
      a.className = "photo-link";
      a.setAttribute("href", desc.photo.href);
      a.setAttribute("data-caption", desc.photo.caption || "");
      if (desc.photo.location) a.setAttribute("data-location", desc.photo.location);
      a.setAttribute("data-photo-file", desc.photo.file);
      var img = document.createElement("img");
      img.setAttribute("data-src", desc.photo.src);
      img.alt = desc.photo.caption || "";
      img.width = desc.photo.w;
      img.height = desc.photo.h;
      a.appendChild(img);
      fig.appendChild(a);
      node.appendChild(fig);
      return node;
    }

    function loadImages(node) {
      if (!node) return;
      var imgs = node.querySelectorAll("img[data-src]");
      for (var i = 0; i < imgs.length; i++) {
        imgs[i].src = imgs[i].getAttribute("data-src");
        imgs[i].removeAttribute("data-src");
      }
      var bgs = node.querySelectorAll("[data-bg]");
      for (var j = 0; j < bgs.length; j++) {
        bgs[j].style.backgroundImage = 'url("' + bgs[j].getAttribute("data-bg") + '")';
        bgs[j].removeAttribute("data-bg");
      }
    }

    var pages = [];
    spreads.forEach(function (sp) {
      pages.push({ desc: sp.left, side: "left" });
      pages.push({ desc: sp.right, side: "right" });
    });

    staticLeft.appendChild(makePage(pages[0].desc, "left"));
    var evenPages = pages.length % 2 === 0;
    staticRight.appendChild(makePage(evenPages ? pages[pages.length - 1].desc : { kind: "blank" }, "right"));

    var leafCount = Math.floor((pages.length - 1) / 2);
    for (var k = 0; k < leafCount; k++) {
      var leaf = document.createElement("div");
      leaf.className = "book-leaf";
      var front = makePage(pages[2 * k + 1].desc, "right");
      front.className += " book-face book-face--front";
      var back = makePage(pages[2 * k + 2].desc, "left");
      back.className += " book-face book-face--back";
      leaf.appendChild(front);
      leaf.appendChild(back);
      leavesBox.appendChild(leaf);
      leaves.push({ el: leaf, front: front, back: back });
    }

    var tocGroup = null;
    spreads.forEach(function (sp, i) {
      if (sp.left.kind === "chapter" || !tocGroup) {
        var title = document.createElement("p");
        title.className = "book-toc-group-title";
        var ch = sp.left.kind === "chapter"
          ? { number: sp.left.number, name: sp.left.chapter }
          : { number: 1, name: sp.chapter };
        title.textContent = pad(ch.number) + " · " + ch.name;
        tocGrid.appendChild(title);
        tocGroup = document.createElement("div");
        tocGroup.className = "book-toc-grid-row";
        tocGrid.appendChild(tocGroup);
      }
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = pad(i + 1);
      b.setAttribute("aria-label", "跳到第 " + (i + 1) + " 跨页");
      b.addEventListener("click", function () {
        tocPanel.hidden = true;
        goTo(i, 0);
      });
      tocGroup.appendChild(b);
    });

    function updateZ() {
      var total = leaves.length;
      leaves.forEach(function (item, k) {
        item.el.style.zIndex = String(k < index ? k + 1 : total * 2 - k + 1);
      });
    }

    function loadNear() {
      loadImages(staticLeft);
      loadImages(staticRight);
      [index - 1, index, index + 1].forEach(function (n) {
        if (!leaves[n]) return;
        loadImages(leaves[n].front);
        loadImages(leaves[n].back);
      });
    }

    function updateLabel() {
      if (isMobile()) {
        var pageNo = index * 2 + side + 1;
        labelEl.textContent = pad(pageNo) + " / " + pad(pages.length);
      } else {
        labelEl.textContent = pad(index + 1) + " / " + pad(spreads.length);
      }
    }

    function updateChapter() {
      var ch = currentChapter();
      chapterEl.textContent = pad(ch.number) + " · " + ch.name;
    }

    function applyMobileSide() {
      updateChapter();
      document.body.classList.toggle("book-side-right", side === 1);
      document.body.classList.toggle("book-at-start", index === 0 && side === 0);
      document.body.classList.toggle("book-at-end", index === spreads.length - 1 && side === 1);
      updateLabel();
    }

    function turnMs() { return isMobile() ? 700 : 1300; }

    function animateLeaf(delta, targetIndex) {
      var moving = leaves[targetIndex];
      if (!moving || reduceMotion) return;
      moving.el.classList.add(delta > 0 ? "is-turning-next" : "is-turning-prev");
      window.setTimeout(function () {
        moving.el.classList.remove("is-turning-next", "is-turning-prev");
      }, turnMs());
    }

    function goTo(next, direction) {
      index = Math.max(0, Math.min(next, spreads.length - 1));
      leaves.forEach(function (item, k) {
        item.el.classList.toggle("is-turned", k < index);
        item.el.classList.remove("is-turning-next", "is-turning-prev");
      });
      updateZ();
      volume.classList.toggle("is-spread", spreads[index] && spreads[index].type === "spread");
      if (direction && !reduceMotion) {
        animateLeaf(direction, direction > 0 ? index - 1 : index);
      }
      prevBtn.disabled = index === 0 && side === 0;
      nextBtn.disabled = index === spreads.length - 1 && side === 1;
      loadNear();
      applyMobileSide();
      if (window.SHIGUANG_LIGHTBOX && window.SHIGUANG_LIGHTBOX.refresh) {
        window.SHIGUANG_LIGHTBOX.refresh();
      }
    }

    function flip(delta) {
      if (animating) return;
      if (isMobile()) {
        var nextSide = side + delta;
        if (nextSide >= 0 && nextSide <= 1) {
          side = nextSide;
          animating = true;
          goTo(index, 0);
          animateLeaf(delta, index);
          window.setTimeout(function () { animating = false; }, reduceMotion ? 0 : turnMs() + 40);
          return;
        }
        if (delta > 0 && index < spreads.length - 1) {
          index++;
          side = 0;
        } else if (delta < 0 && index > 0) {
          index--;
          side = 1;
        } else {
          return;
        }
        animating = true;
        goTo(index, delta);
        window.setTimeout(function () { animating = false; }, reduceMotion ? 0 : turnMs() + 40);
        return;
      }
      var target = index + delta;
      if (target < 0 || target >= spreads.length) return;
      animating = true;
      goTo(target, delta);
      window.setTimeout(function () { animating = false; }, reduceMotion ? 0 : turnMs() + 40);
    }

    coverEnter.addEventListener("click", function () {
      if (!reduceMotion && coverBook) coverBook.classList.add("is-opening");
      window.setTimeout(function () {
        coverView.hidden = true;
        bookView.hidden = false;
        volume.classList.add("is-opening");
        window.setTimeout(function () { volume.classList.remove("is-opening"); }, 620);
        goTo(0, 0);
      }, reduceMotion ? 0 : 420);
    });
    coverBtn.addEventListener("click", function () {
      bookView.hidden = true;
      tocPanel.hidden = true;
      coverView.hidden = false;
      if (coverBook) coverBook.classList.remove("is-opening");
    });
    tocBtn.addEventListener("click", function () { tocPanel.hidden = false; });
    tocClose.addEventListener("click", function () { tocPanel.hidden = true; });
    tocPanel.addEventListener("click", function (event) {
      if (event.target === tocPanel) tocPanel.hidden = true;
    });
    prevBtn.addEventListener("click", function () { flip(-1); });
    nextBtn.addEventListener("click", function () { flip(1); });

    document.addEventListener("keydown", function (event) {
      if (document.body.classList.contains("lightbox-open")) return;
      if (!tocPanel.hidden) {
        if (event.key === "Escape") { event.preventDefault(); tocPanel.hidden = true; }
        return;
      }
      if (bookView.hidden) {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); coverEnter.click(); }
        return;
      }
      if (event.key === "ArrowLeft") { event.preventDefault(); flip(-1); }
      else if (event.key === "ArrowRight") { event.preventDefault(); flip(1); }
      else if (event.key === "Home") { event.preventDefault(); goTo(0, 0); }
      else if (event.key === "End") { event.preventDefault(); goTo(spreads.length - 1, 0); }
    });

    var touchX = 0;
    var touchY = 0;
    volume.addEventListener("touchstart", function (event) {
      if (event.touches.length !== 1) return;
      touchX = event.touches[0].clientX;
      touchY = event.touches[0].clientY;
    }, { passive: true });
    volume.addEventListener("touchend", function (event) {
      var t = event.changedTouches[0];
      if (!t) return;
      var dx = t.clientX - touchX;
      var dy = t.clientY - touchY;
      if (Math.abs(dx) > 50 && Math.abs(dx) > Math.abs(dy) * 1.2) flip(dx < 0 ? 1 : -1);
    }, { passive: true });

    goTo(0, 0);
  })();
  </script>
  <script src="js/main.js"></script>
</body>
</html>
"""


def select_book_photos(albums: list[Album], config: dict[str, Any]) -> list[Photo]:
    """默认取整个泉州册，再追加网页上手动加入的照片。"""
    if not albums:
        return []

    by_name: dict[str, Photo] = {}
    for album in albums:
        for photo in album.photos:
            photo.book_album = album.title
            by_name.setdefault(Path(photo.rel_source).name, photo)

    base_album = next((a for a in albums if a.title == config["album"]), None)
    removed = set(config["removed"])
    base = []
    if base_album:
        base = [p for p in base_album.photos if Path(p.rel_source).name not in removed]
    else:
        print(f"警告：画册默认册集「{config['album']}」不存在，画册只保留手动加入的照片。")

    result: list[Photo] = []
    seen: set[str] = set()
    for photo in base:
        key = str(photo.rel_source)
        if key not in seen:
            seen.add(key)
            result.append(photo)
    for name in config["added"]:
        photo = by_name.get(name)
        if not photo:
            continue
        key = str(photo.rel_source)
        if key not in seen:
            seen.add(key)
            result.append(photo)
    return result


def book_html(photos: list[Photo], meta: dict[str, str] | None = None) -> str:
    """把选中的照片渲染为唯一一本画册，不保留册集标题与选择器。"""
    from urllib.parse import quote as _urlquote

    meta = meta or {}
    title = meta.get("title") or "水上行走影像"
    author = meta.get("author") or "水上行走"
    year = meta.get("year") or str(datetime.now().year)

    data = []
    supported = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
    for photo in photos:
        view = photo.default
        original = "originals/" + _urlquote(str(photo.rel_source))
        # 画册优先直接使用原图；浏览器无法直接显示的格式才退回生成图。
        src = original if Path(photo.rel_source).suffix.lower() in supported else view["path"]
        data.append(
            {
                "src": src,
                "w": view["w"],
                "h": view["h"],
                "href": original,
                "caption": photo.caption,
                "location": photo.location,
                "file": Path(photo.rel_source).name,
                "album": getattr(photo, "book_album", "") or meta.get("album", ""),
            }
        )

    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    meta_payload = json.dumps(
        {"title": title, "author": author, "year": year, "album": meta.get("album", "")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        BOOK_TEMPLATE.replace("__BOOK_TITLE__", e(title))
        .replace("__BOOK_AUTHOR__", e(author))
        .replace("__BOOK_YEAR__", e(year))
        .replace("__BOOK_PHOTOS__", payload)
        .replace("__BOOK_META__", meta_payload)
    )


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
        print("没有找到包含照片的册集文件夹，生成空白相册。")
        write_if_changed(output / "gallery.html", gallery_html([], depth))
        write_if_changed(
            output / "book.html",
            book_html([], {
                "title": "水上行走影像",
                "author": "水上行走",
                "year": str(datetime.now().year),
                "album": book_photos.load(args.config)["album"],
            }),
        )
        book_photos.write_manifest(
            output, book_photos.load(args.config)["album"], []
        )
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

    book_config = book_photos.load(args.config)
    book_meta = {
        "title": f"{book_config['album']}影像",
        "author": "水上行走",
        "year": str(datetime.now().year),
        "album": book_config["album"],
    }

    if not albums:
        print("所有文件夹都没有可用照片，生成空白相册。")
        write_if_changed(output / "gallery.html", gallery_html([], depth))
        write_if_changed(output / "book.html", book_html([], book_meta))
        book_photos.write_manifest(output, book_config["album"], [])
        return

    # 新册在前；同一年按标题排序。
    albums.sort(key=lambda a: (a.year or "", a.title), reverse=True)

    book_selected = select_book_photos(albums, book_config)
    print(f"画册：默认《{book_config['album']}》+ 手动添加 {len(book_config['added'])} 张 → {len(book_selected)} 张")

    new_files: set[str] = {"gallery.html", "book.html", book_photos.MANIFEST_NAME}
    pages: dict[str, str] = {
        "gallery.html": gallery_html(albums, depth),
        "book.html": book_html(book_selected, book_meta),
    }

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

    book_photos.write_manifest(
        output,
        book_config["album"],
        [Path(p.rel_source).name for p in book_selected],
    )

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
