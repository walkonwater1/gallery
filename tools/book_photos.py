#!/usr/bin/env python3
"""画册的独立维护清单。

画册默认收录「泉州」整册，之后只把网页上点「加入画册」的照片追加进来。
清单写在 book.json（与 gallery.config.json 同级），不会改动任何原图。

    python3 book_photos.py                     查看当前清单
    python3 book_photos.py --add P100001.jpg   加入画册
    python3 book_photos.py --remove P100001.jpg 移出画册
    python3 book_photos.py --no-rebuild ...    只改清单，不重新生成

照片源目录默认是 /root/photograph，可用 ALBUM_SOURCE 覆盖；
清单路径可用 ALBUM_BOOK_CONFIG 覆盖（生成器会用 --config 的同级目录）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
CONFIG_NAME = "book.json"
MANIFEST_NAME = "book-photos.json"
DEFAULT_ALBUM = "泉州"
SOURCE = Path(os.environ.get("ALBUM_SOURCE", "/root/photograph"))
UPDATE = Path("/root/start_sh/update-album.sh")

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    ".heic", ".heif", ".avif", ".nef", ".nrw", ".cr2", ".cr3", ".arw",
    ".raf", ".orf", ".rw2", ".dng", ".pef", ".srw", ".raw",
}


def die(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def config_path(reference: str | Path | None = None) -> Path:
    if reference:
        return Path(reference).expanduser().resolve().with_name(CONFIG_NAME)
    env = os.environ.get("ALBUM_BOOK_CONFIG")
    if env:
        return Path(env).expanduser().resolve()
    return ROOT / CONFIG_NAME


def manifest_path(output_root: str | Path) -> Path:
    return Path(output_root) / MANIFEST_NAME


def _names(raw: Any) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    result: list[str] = []
    for item in raw:
        name = Path(str(item)).name.strip()
        if name and name not in result:
            result.append(name)
    return result


def load(reference: str | Path | None = None) -> dict[str, Any]:
    path = config_path(reference)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError) as exc:
            die(f"读取 {path} 失败：{exc}")
    album = str(data.get("album") or DEFAULT_ALBUM).strip() or DEFAULT_ALBUM
    return {
        "album": album,
        "added": _names(data.get("added")),
        "removed": _names(data.get("removed")),
    }


def save(config: dict[str, Any], reference: str | Path | None = None) -> None:
    path = config_path(reference)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_manifest(output_root: str | Path, album: str, photos: Iterable[str]) -> None:
    path = manifest_path(output_root)
    path.write_text(
        json.dumps(
            {"album": album, "photos": list(photos)},
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def find_photo(name: str) -> Path:
    matches = sorted(
        (
            p for p in SOURCE.rglob("*")
            if p.is_file() and p.name == name and p.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda p: str(p),
    )
    if not matches:
        die(f"在 {SOURCE} 下找不到照片「{name}」")
    if len(matches) > 1:
        print(f"找到 {len(matches)} 个同名文件：", file=sys.stderr)
        for path in matches:
            print(f"  {path.relative_to(SOURCE)}", file=sys.stderr)
        raise SystemExit(1)
    return matches[0]


def add(name: str, reference: str | Path | None = None) -> str:
    photo = find_photo(name)
    config = load(reference)
    config["removed"] = [n for n in config["removed"] if n != photo.name]
    if photo.name not in config["added"]:
        config["added"].append(photo.name)
    save(config, reference)
    return f"已加入画册：{photo.name}"


def remove(name: str, reference: str | Path | None = None) -> str:
    photo = find_photo(name)
    config = load(reference)
    config["added"] = [n for n in config["added"] if n != photo.name]
    try:
        album_name = photo.relative_to(SOURCE).parts[0]
    except ValueError:
        album_name = ""
    if album_name == config["album"] and photo.name not in config["removed"]:
        config["removed"].append(photo.name)
    save(config, reference)
    return f"已移出画册：{photo.name}"


def rebuild(enabled: bool) -> None:
    if not enabled:
        print("已跳过重新生成；下次运行 bash /root/start_sh/update-album.sh 后生效。")
        return
    if not UPDATE.is_file():
        print(f"未找到 {UPDATE}，请手动重新生成画册。", file=sys.stderr)
        return
    print("正在重新生成画册…")
    subprocess.run(["bash", str(UPDATE)], check=True)


def main() -> None:
    raw = sys.argv[1:]
    rebuild_now = "--no-rebuild" not in raw
    args = [a for a in raw if a != "--no-rebuild"]
    reference = os.environ.get("ALBUM_BOOK_CONFIG")

    if not args or args[0] in ("--list", "-l", "list"):
        config = load(reference)
        print(f"画册默认册集：{config['album']}")
        print(f"额外添加：{len(config['added'])} 张")
        for name in config["added"]:
            print(f"  + {name}")
        print(f"已移出：{len(config['removed'])} 张")
        for name in config["removed"]:
            print(f"  - {name}")
        return
    if args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return
    if args[0] in ("--add", "-a") and len(args) > 1:
        message = add(args[1], reference)
    elif args[0] in ("--remove", "-r") and len(args) > 1:
        message = remove(args[1], reference)
    else:
        die("用法：book_photos.py --add <文件名> | --remove <文件名> | --list")
    print(message)
    rebuild(rebuild_now)


if __name__ == "__main__":
    main()
