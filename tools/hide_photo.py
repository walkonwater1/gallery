#!/usr/bin/env python3
"""在网站上隐藏 / 恢复照片，不改动本地原文件。

隐藏名单写在册集目录的 album.json 里：
    {"hidden_photos": ["P1085284.jpg", "P1085285.jpg"]}

生成器会跳过这些照片，首页、册集页和画册页都不会再出现它们；原片始终留在
照片目录里，随时可以恢复。

常用命令（盒子上用 /root/hide-photo.sh）：
    bash /root/hide-photo.sh --list              列出各册已隐藏的照片
    bash /root/hide-photo.sh P1085284.jpg        隐藏（自动定位册集）
    bash /root/hide-photo.sh --show P1085284.jpg 恢复显示
    bash /root/hide-photo.sh --no-rebuild ...    只改配置，暂不重新生成
"""
from __future__ import annotations

import sys
from pathlib import Path

from set_cover import (
    SOURCE,
    IMAGE_EXTS,
    album_dirs,
    load_config,
    save_config,
    rebuild,
    die,
)


def locate(name: str) -> tuple[Path, str]:
    matches = sorted(
        (
            p
            for p in SOURCE.rglob("*")
            if p.is_file() and p.name == name and p.suffix.lower() in IMAGE_EXTS
        ),
        key=lambda p: str(p),
    )
    if not matches:
        die(f"在 {SOURCE} 下找不到照片「{name}」。")
    if len(matches) > 1:
        print(f"找到 {len(matches)} 个同名文件：", file=sys.stderr)
        for p in matches:
            print(f"  {p.relative_to(SOURCE)}", file=sys.stderr)
        raise SystemExit(1)
    photo = matches[0]
    rel = photo.relative_to(SOURCE)
    album_dir = SOURCE / rel.parts[0] if len(rel.parts) > 1 else SOURCE
    return album_dir, photo.name


def hidden_of(album_dir: Path) -> list[str]:
    raw = load_config(album_dir).get("hidden_photos") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(x) for x in raw] if isinstance(raw, (list, tuple)) else []


def cmd_list() -> None:
    dirs = album_dirs()
    total = 0
    print(f"照片目录：{SOURCE}")
    print(f"共 {len(dirs)} 册\n")
    for d in dirs:
        names = hidden_of(d)
        total += len(names)
        if not names:
            print(f"  {d.name}  ·  没有隐藏照片")
        else:
            print(f"  {d.name}  ·  隐藏 {len(names)} 张：{'、'.join(names)}")
    print(f"\n合计隐藏 {total} 张。恢复：bash /root/hide-photo.sh --show <文件名>")


def cmd_hide(name: str, rebuild_now: bool) -> None:
    album_dir, filename = locate(name)
    config = load_config(album_dir)
    names = hidden_of(album_dir)
    if filename in names:
        print(f"《{album_dir.name}》的 {filename} 已处于隐藏状态。")
        return
    names.append(filename)
    config["hidden_photos"] = names
    save_config(album_dir, config)
    print(f"《{album_dir.name}》已隐藏 {filename}（原文件保持不变）")
    rebuild(rebuild_now)


def cmd_show(name: str, rebuild_now: bool) -> None:
    album_dir, filename = locate(name)
    config = load_config(album_dir)
    names = hidden_of(album_dir)
    if filename not in names:
        print(f"《{album_dir.name}》的 {filename} 本来就是显示的。")
        return
    remaining = [n for n in names if n != filename]
    if remaining:
        config["hidden_photos"] = remaining
    else:
        config.pop("hidden_photos", None)
    save_config(album_dir, config)
    print(f"《{album_dir.name}》已恢复显示 {filename}")
    rebuild(rebuild_now)


def main() -> None:
    raw = sys.argv[1:]
    rebuild_now = "--no-rebuild" not in raw
    args = [a for a in raw if a != "--no-rebuild"]

    if not args or args[0] in ("--list", "-l", "list"):
        cmd_list()
    elif args[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
    elif args[0] in ("--show", "-s"):
        if len(args) < 2:
            die("用法：hide_photo.py --show <照片文件名>")
        cmd_show(args[1], rebuild_now)
    else:
        cmd_hide(args[0], rebuild_now)


if __name__ == "__main__":
    main()
