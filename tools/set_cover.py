#!/usr/bin/env python3
"""查看 / 修改自动照片库的册集封面。

封面写在册集目录的 album.json 里，例如 {"cover": "P1096445.jpg"}。
生成器 build_gallery.py 会优先用这张图做首页卡片和册集页头图。

常用命令（盒子上也可以用 /root/set-cover.sh）：
    python3 set_cover.py                     列出所有册集与当前封面
    python3 set_cover.py --photos 泉州       列出该册照片及序号
    python3 set_cover.py P1096445.jpg        按文件名设为封面（自动定位册集）
    python3 set_cover.py 泉州 12             按序号设为封面
    python3 set_cover.py --clear 泉州        恢复默认封面
    python3 set_cover.py --no-rebuild ...    只改配置，暂不重新生成

照片源目录默认是 /root/photograph，可用环境变量 ALBUM_SOURCE 覆盖。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SOURCE = Path(os.environ.get("ALBUM_SOURCE", "/root/photograph"))
UPDATE = Path("/root/update-album.sh")
CONFIG_NAME = "album.json"

IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif",
    ".heic", ".heif", ".avif",
    ".nef", ".cr2", ".cr3", ".arw", ".raf", ".dng", ".orf", ".rw2",
    ".pef", ".srw", ".rwl", ".3fr", ".fff", ".iiq",
}


def die(message: str) -> None:
    print(f"错误：{message}", file=sys.stderr)
    raise SystemExit(1)


def album_dirs() -> list[Path]:
    if not SOURCE.is_dir():
        die(f"照片目录不存在：{SOURCE}（可用环境变量 ALBUM_SOURCE 指定）")
    return sorted(
        (p for p in SOURCE.iterdir() if p.is_dir() and not p.name.startswith(".")),
        key=lambda p: p.name,
    )


def photos_of(album_dir: Path) -> list[Path]:
    return sorted(
        (
            p
            for p in album_dir.rglob("*")
            if p.is_file()
            and not p.name.startswith(".")
            and p.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda p: str(p.relative_to(album_dir)).lower(),
    )


def load_config(album_dir: Path) -> dict:
    path = album_dir / CONFIG_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        die(f"读取 {path} 失败：{exc}")


def save_config(album_dir: Path, config: dict) -> None:
    path = album_dir / CONFIG_NAME
    if config:
        path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    elif path.exists():
        path.unlink()


def find_album(name: str) -> Path:
    dirs = album_dirs()
    for d in dirs:
        if d.name == name:
            return d
    matched = [d for d in dirs if name in d.name]
    if not matched:
        die(f"没有找到册集「{name}」。可用：{'、'.join(d.name for d in dirs)}")
    if len(matched) > 1:
        die(f"「{name}」匹配到多个册集：{'、'.join(d.name for d in matched)}")
    return matched[0]


def rebuild(enabled: bool) -> None:
    if not enabled:
        print("已跳过重新生成；下次运行 bash /root/update-album.sh 后生效。")
        return
    if not UPDATE.is_file():
        print(f"未找到 {UPDATE}，请手动重新生成画册。", file=sys.stderr)
        return
    print("正在重新生成画册…")
    subprocess.run(["bash", str(UPDATE)], check=True)


def apply_cover(album_dir: Path, photo: Path, rebuild_now: bool) -> None:
    config = load_config(album_dir)
    previous = config.get("cover")
    config["cover"] = photo.name
    save_config(album_dir, config)
    suffix = f"（原为 {previous}）" if previous else ""
    print(f"《{album_dir.name}》封面已设为 {photo.name}{suffix}")
    print(f"配置文件：{album_dir / CONFIG_NAME}")
    rebuild(rebuild_now)


def cmd_list() -> None:
    dirs = album_dirs()
    print(f"照片目录：{SOURCE}")
    print(f"共 {len(dirs)} 册\n")
    for index, d in enumerate(dirs, start=1):
        count = len(photos_of(d))
        cover = str(load_config(d).get("cover") or "").strip()
        current = cover or "默认（按拍摄时间最早的一张）"
        print(f"  [{index:02d}] {d.name}  ·  {count} 张  ·  封面：{current}")
    print("\n改封面：bash /root/set-cover.sh <照片文件名>")
    print("看某册照片：bash /root/set-cover.sh --photos <册名>")


def cmd_photos(name: str) -> None:
    album_dir = find_album(name)
    photos = photos_of(album_dir)
    if not photos:
        die(f"「{album_dir.name}」里没有找到照片")
    cover = str(load_config(album_dir).get("cover") or "").strip()
    print(f"{album_dir.name} 共 {len(photos)} 张：\n")
    for index, photo in enumerate(photos, start=1):
        mark = ""
        if cover:
            if photo.name == Path(cover).name:
                mark = "  ← 当前封面"
        elif index == 1:
            mark = "  ← 当前封面（默认）"
        print(f"  {index:03d}  {photo.name}{mark}")
    print(f"\n设置封面：bash /root/set-cover.sh {album_dir.name} <序号>")


def cmd_set_file(name: str, rebuild_now: bool) -> None:
    matches = sorted(
        (
            p
            for p in SOURCE.rglob("*")
            if p.is_file() and p.name == name and p.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda p: str(p),
    )
    if not matches:
        die(f"在 {SOURCE} 下找不到照片「{name}」。可先用 --photos <册名> 查文件名。")
    if len(matches) > 1:
        print(f"找到 {len(matches)} 个同名文件，请改用「<册名> <序号>」：", file=sys.stderr)
        for p in matches:
            print(f"  {p.relative_to(SOURCE)}", file=sys.stderr)
        raise SystemExit(1)
    photo = matches[0]
    rel = photo.relative_to(SOURCE)
    album_dir = SOURCE / rel.parts[0] if len(rel.parts) > 1 else SOURCE
    apply_cover(album_dir, photo, rebuild_now)


def cmd_set_index(name: str, index: int, rebuild_now: bool) -> None:
    album_dir = find_album(name)
    photos = photos_of(album_dir)
    if index < 1 or index > len(photos):
        die(f"序号超出范围（1–{len(photos)}）")
    apply_cover(album_dir, photos[index - 1], rebuild_now)


def cmd_clear(name: str, rebuild_now: bool) -> None:
    album_dir = find_album(name)
    config = load_config(album_dir)
    if "cover" not in config:
        print(f"《{album_dir.name}》本来就是默认封面，无需修改。")
        return
    config.pop("cover", None)
    save_config(album_dir, config)
    print(f"《{album_dir.name}》已恢复默认封面。")
    rebuild(rebuild_now)


def main() -> None:
    raw = sys.argv[1:]
    rebuild_now = "--no-rebuild" not in raw
    args = [a for a in raw if a != "--no-rebuild"]

    if not args or args[0] in ("--list", "-l", "list"):
        cmd_list()
    elif args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
    elif args[0] in ("--photos", "-p"):
        if len(args) < 2:
            die("用法：set_cover.py --photos <册名>")
        cmd_photos(args[1])
    elif args[0] in ("--clear", "-c"):
        if len(args) < 2:
            die("用法：set_cover.py --clear <册名>")
        cmd_clear(args[1], rebuild_now)
    elif len(args) >= 2 and args[1].isdigit():
        cmd_set_index(args[0], int(args[1]), rebuild_now)
    else:
        cmd_set_file(args[0], rebuild_now)


if __name__ == "__main__":
    main()
