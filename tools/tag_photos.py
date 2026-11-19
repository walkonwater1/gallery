#!/usr/bin/env python3
"""照片景点标签：给照片打 tag，并按 tag 生成子文件夹。

用法（在盒子上）：
  python3 tools/tag_photos.py set <照片文件名> <标签>       # 记录 tag 到该册 album.json
  python3 tools/tag_photos.py unset <照片文件名>            # 移除 tag
  python3 tools/tag_photos.py list [册名]                   # 查看 tag
  python3 tools/tag_photos.py apply [册名]                  # 按 tag 把照片移动到子文件夹（并迁移缓存）

tag 存在相册目录的 album.json 中："tags": {"P1060894.jpg": "五花海"}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SOURCE = Path(os.environ.get("ALBUM_SOURCE", "/root/photograph"))
CACHE = Path("/root/lixin/digital_album/.gallery-cache/manifest.json")
CONFIG_NAME = "album.json"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif", ".heic", ".raw", ".dng", ".cr2", ".cr3", ".nef"}


def die(msg: str) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def load_config(album_dir: Path) -> dict:
    path = album_dir / CONFIG_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(album_dir: Path, config: dict) -> None:
    (album_dir / CONFIG_NAME).write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def find_photo(name: str) -> Path:
    matches = sorted(
        (p for p in SOURCE.rglob("*") if p.is_file() and p.name == name and p.suffix.lower() in IMAGE_EXTS),
        key=lambda p: str(p),
    )
    if not matches:
        die(f"找不到照片：{name}")
    if len(matches) > 1:
        die(f"有 {len(matches)} 个同名文件 {name}，请用命令行进入对应册操作")
    return matches[0]


def set_tag(name: str, tag: str) -> str:
    photo = find_photo(name)
    album_dir = photo.parent
    config = load_config(album_dir)
    tags = config.get("tags") or {}
    if not isinstance(tags, dict):
        tags = {}
    tag = tag.strip().strip("/\\")
    if not tag:
        die("标签不能为空")
    tags[name] = tag
    config["tags"] = tags
    save_config(album_dir, config)
    return f"已标注《{album_dir.name}》{name} → {tag}"


def unset_tag(name: str) -> str:
    photo = find_photo(name)
    album_dir = photo.parent
    config = load_config(album_dir)
    tags = config.get("tags") or {}
    tags.pop(name, None)
    if tags:
        config["tags"] = tags
    else:
        config.pop("tags", None)
    save_config(album_dir, config)
    return f"已移除 {name} 的标签"


def list_tags(album: str | None) -> str:
    dirs = [p for p in SOURCE.rglob(CONFIG_NAME)]
    if album:
        dirs = [p for p in dirs if album in p.parent.name or album in str(p.parent.relative_to(SOURCE))]
    lines = []
    for cfg in sorted(dirs):
        data = load_config(cfg.parent)
        tags = data.get("tags") or {}
        if not tags:
            continue
        lines.append(f"《{cfg.parent.relative_to(SOURCE)}》")
        for name, tag in tags.items():
            lines.append(f"  {name} → {tag}")
    return "\n".join(lines) if lines else "没有标注"


def migrate_cache(moves: list[tuple[Path, Path]]) -> None:
    """把缓存里的照片绝对路径从旧位置改为新位置，避免重新处理图片。"""
    if not CACHE.exists() or not moves:
        return
    doc = json.loads(CACHE.read_text(encoding="utf-8"))
    photos = doc.get("photos") or {}
    mapping = {str(old): str(new) for old, new in moves}
    updated = {}
    for key, value in photos.items():
        updated[mapping.get(key, key)] = value
    doc["photos"] = updated
    CACHE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_tags(album: str | None) -> str:
    cfgs = [p for p in SOURCE.rglob(CONFIG_NAME)]
    if album:
        cfgs = [p for p in cfgs if album in p.parent.name or album in str(p.parent.relative_to(SOURCE))]
    if not cfgs:
        die(f"找不到册集：{album or ''}")

    moves: list[tuple[Path, Path]] = []
    count = 0
    for cfg in cfgs:
        album_dir = cfg.parent
        config = load_config(album_dir)
        tags = config.get("tags") or {}
        if not isinstance(tags, dict) or not tags:
            continue
        for name, tag in tags.items():
            if not isinstance(tag, str) or not tag.strip():
                continue
            tag = tag.strip().strip("/\\")
            photo = album_dir / name
            if not photo.exists():
                continue
            sub = album_dir / tag
            dest = sub / name
            if photo.parent == sub:
                continue
            sub.mkdir(parents=True, exist_ok=True)
            os.replace(photo, dest)
            moves.append((photo, dest))
            count += 1
        # 生成子文件夹后清空 tags 标记（照片已就位）
        config.pop("tags", None)
        save_config(album_dir, config)

    migrate_cache(moves)
    return f"已按标签移动 {count} 张照片到子文件夹，缓存已迁移"


def main() -> None:
    if len(sys.argv) < 2:
        die(__doc__)
    action = sys.argv[1]
    if action == "set":
        if len(sys.argv) < 4:
            die("用法: tag_photos.py set <照片文件名> <标签>")
        print(set_tag(sys.argv[2], sys.argv[3]))
    elif action == "unset":
        if len(sys.argv) < 3:
            die("用法: tag_photos.py unset <照片文件名>")
        print(unset_tag(sys.argv[2]))
    elif action == "list":
        print(list_tags(sys.argv[2] if len(sys.argv) > 2 else None))
    elif action == "apply":
        print(apply_tags(sys.argv[2] if len(sys.argv) > 2 else None))
    else:
        die(f"未知操作：{action}")


if __name__ == "__main__":
    main()
