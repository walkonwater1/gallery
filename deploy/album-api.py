#!/usr/bin/env python3
"""水上行走画册本地管理接口。

让网页上的「设为封面」「不显示这张」等操作点一下就生效：写 album.json，
然后调用 /root/start_sh/update-album.sh 重新生成。只监听 127.0.0.1，由 Nginx 反代。

    POST /api/cover        {"file": "P1096445.jpg"}
    POST /api/clear-cover  {"album": "泉州"}
    POST /api/hide         {"file": "P1085284.jpg"}
    POST /api/show         {"file": "P1085284.jpg"}
    POST /api/book-add     {"file": "P1096445.jpg"}
    POST /api/book-remove  {"file": "P1096445.jpg"}
    POST /api/delete       {"file": "P1096445.jpg"}
    GET  /api/book
    GET  /api/status
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/root/lixin/digital_album/tools")
import set_cover as cover  # noqa: E402
import hide_photo as hide  # noqa: E402
import book_photos  # noqa: E402
import tag_photos  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765
UPDATE = "/root/start_sh/update-album.sh"
LOCK = threading.Lock()
ACTIONS = {"cover", "clear-cover", "hide", "show", "book-add", "book-remove", "delete", "tag"}


def album_root_for(photo: Path) -> Path:
    rel = photo.relative_to(cover.SOURCE)
    if rel.parts and rel.parts[0] == "胶片":
        # 胶片册集按型号建册，日期只是册内小节。
        return photo.parent.parent if len(rel.parts) >= 3 else photo.parent
    return photo.parent if len(rel.parts) > 1 else cover.SOURCE


def list_digital_albums() -> list[str]:
    root = cover.SOURCE / "数码"
    if not root.is_dir():
        return []
    albums: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda p: str(p)):
        if not path.is_dir() or path.name.startswith("."):
            continue
        rel = path.relative_to(cover.SOURCE)
        if len(rel.parts) != 3 or rel.parts[0] != "数码":
            continue
        if any(p.is_file() and p.suffix.lower() in cover.IMAGE_EXTS for p in path.iterdir()):
            albums.append(str(rel))
    return albums


def unique_destination(directory: Path, name: str) -> str:
    candidate = directory / name
    if not candidate.exists():
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    index = 1
    while True:
        new_name = f"{stem}_film{index}{suffix}"
        if not (directory / new_name).exists():
            return new_name
        index += 1


def find_photo_path(name: str) -> Path:
    matches = sorted(
        (
            p
            for p in cover.SOURCE.rglob("*")
            if p.is_file()
            and p.name == name
            and p.suffix.lower() in cover.IMAGE_EXTS
        ),
        key=lambda p: str(p),
    )
    if not matches:
        raise ValueError(f"找不到照片 {name}")
    if len(matches) > 1:
        raise ValueError(f"有 {len(matches)} 个同名文件，请用命令行指定册集")
    return matches[0]


def find_photo(name: str):
    photo = find_photo_path(name)
    return album_root_for(photo), photo.name


def book_state() -> dict:
    config = book_photos.load()
    names: list[str] = []
    try:
        album_dir = cover.find_album(config["album"])
        hidden = set(hide.hidden_of(album_dir))
        names = [
            p.name for p in cover.photos_of(album_dir)
            if p.name not in config["removed"] and p.name not in hidden
        ]
    except SystemExit:
        pass
    names += [n for n in config["added"] if n not in names]
    return {"ok": True, "album": config["album"], "photos": names}


def apply_action(action: str, payload: dict) -> str:
    file_name = str(payload.get("file") or "").strip()
    album_name = str(payload.get("album") or "").strip()

    if action == "cover":
        if not file_name:
            raise ValueError("缺少照片文件名")
        album_dir, name = find_photo(file_name)
        config = cover.load_config(album_dir)
        config["cover"] = name
        cover.save_config(album_dir, config)
        return f"《{album_dir.name}》封面已设为 {name}"

    if action == "clear-cover":
        if not album_name:
            raise ValueError("缺少册名")
        album_dir = cover.find_album(album_name)
        config = cover.load_config(album_dir)
        config.pop("cover", None)
        cover.save_config(album_dir, config)
        return f"《{album_dir.name}》封面已恢复默认"

    if action in ("hide", "show"):
        if not file_name:
            raise ValueError("缺少照片文件名")
        album_dir, name = find_photo(file_name)
        config = cover.load_config(album_dir)
        names = hide.hidden_of(album_dir)
        if action == "hide":
            if name not in names:
                names.append(name)
            config["hidden_photos"] = names
            message = f"《{album_dir.name}》已隐藏 {name}"
        else:
            remaining = [n for n in names if n != name]
            if remaining:
                config["hidden_photos"] = remaining
            else:
                config.pop("hidden_photos", None)
            message = f"《{album_dir.name}》已恢复显示 {name}"
        cover.save_config(album_dir, config)
        return message

    if action in ("book-add", "book-remove"):
        if not file_name:
            raise ValueError("缺少照片文件名")
        if action == "book-add":
            return book_photos.add(file_name)
        return book_photos.remove(file_name)

    if action == "tag":
        tag = str(payload.get("tag") or "").strip()
        target = str(payload.get("target") or "").strip().strip("/\\")
        if not file_name or not tag:
            raise ValueError("缺少照片文件名或标签")
        if not target:
            return tag_photos.set_tag(file_name, tag)

        if not target.startswith("数码/"):
            raise ValueError("目标必须是数码册集")
        dest_dir = (cover.SOURCE / target).resolve()
        if cover.SOURCE not in dest_dir.parents or not dest_dir.is_dir():
            raise ValueError(f"找不到目标册集 {target}")

        rel_path = str(payload.get("path") or "").strip().lstrip("/")
        if rel_path:
            photo = (cover.SOURCE / rel_path).resolve()
            if cover.SOURCE not in photo.parents or not photo.is_file():
                raise ValueError(f"找不到照片 {rel_path}")
        else:
            photo = find_photo_path(file_name)

        old_name = photo.name
        old_config_dirs = sorted({photo.parent, album_root_for(photo)}, key=str)
        new_name = unique_destination(dest_dir, old_name)
        dest = dest_dir / new_name
        os.replace(photo, dest)
        tag_photos.migrate_cache([(photo, dest)])

        for config_dir in old_config_dirs:
            config = tag_photos.load_config(config_dir)
            tags = config.get("tags") or {}
            if isinstance(tags, dict) and old_name in tags:
                tags.pop(old_name, None)
                if tags:
                    config["tags"] = tags
                else:
                    config.pop("tags", None)
                tag_photos.save_config(config_dir, config)

        config = tag_photos.load_config(dest_dir)
        tags = config.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        tags[new_name] = tag
        config["tags"] = tags
        tag_photos.save_config(dest_dir, config)
        return f"已将 {new_name} 移到《{dest_dir.parent.name}/{dest_dir.name}》并标注 {tag}"

    if action == "delete":
        if not file_name:
            raise ValueError("缺少照片文件名")
        rel_path = str(payload.get("path") or "").strip().lstrip("/")
        if rel_path:
            photo = (cover.SOURCE / rel_path).resolve()
            if cover.SOURCE not in photo.parents or not photo.is_file():
                raise ValueError(f"找不到照片 {rel_path}")
        else:
            photo = find_photo_path(file_name)
        album_dir = album_root_for(photo)
        name = photo.name
        config = cover.load_config(album_dir)
        changed = False
        if config.get("cover") == name:
            config.pop("cover", None)
            changed = True
        hidden = [n for n in hide.hidden_of(album_dir) if n != name]
        if len(hidden) != len(hide.hidden_of(album_dir)):
            if hidden:
                config["hidden_photos"] = hidden
            else:
                config.pop("hidden_photos", None)
            changed = True
        if changed:
            cover.save_config(album_dir, config)
        try:
            book_photos.remove(name, photo_path=photo)
        except (Exception, SystemExit):
            pass
        os.remove(photo)
        return f"已永久删除 {name}（{album_dir.name}）"

    raise ValueError("未知操作")


def update_cover_page(photo_name: str) -> None:
    """封面设置后只更新首页封面引用，避免整站重建导致 504。"""
    result = subprocess.run(
        [sys.executable, "/root/lixin/digital_album/deploy/update_cover_page.py", photo_name],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print((result.stderr or '').strip()[-300:], file=sys.stderr)


def rebuild() -> None:
    result = subprocess.run(
        ["bash", UPDATE], capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise RuntimeError("重新生成失败：" + detail)


_rebuild_timer: threading.Timer | None = None


def rebuild_async() -> None:
    """后台重建，20 秒防抖：连续删片期间的多次删除合并为一次重建。"""
    global _rebuild_timer
    if _rebuild_timer is not None:
        _rebuild_timer.cancel()
    def run():
        subprocess.Popen(
            ["bash", UPDATE],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    _rebuild_timer = threading.Timer(20.0, run)
    _rebuild_timer.daemon = True
    _rebuild_timer.start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/status":
            self.send_json(200, {"ok": True, "building": LOCK.locked()})
        elif path == "/api/book":
            try:
                self.send_json(200, book_state())
            except SystemExit:
                self.send_json(400, {"ok": False, "message": "画册默认册集不存在"})
            except Exception as exc:
                self.send_json(500, {"ok": False, "message": str(exc)[:300]})
        elif path == "/api/albums":
            self.send_json(200, {"ok": True, "albums": list_digital_albums()})
        else:
            self.send_json(404, {"ok": False, "message": "not found"})

    def do_POST(self):
        action = self.path.split("/api/")[-1].split("?")[0].strip("/")
        if action not in ACTIONS:
            self.send_json(404, {"ok": False, "message": "unknown action"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(payload, dict):
                raise ValueError("bad payload")
        except Exception:
            self.send_json(400, {"ok": False, "message": "请求格式错误"})
            return

        with LOCK:
            try:
                message = apply_action(action, payload)
                if action == "cover":
                    update_cover_page(str(payload.get("file") or "").strip())
                elif action == "delete":
                    rebuild_async()
                elif action == "tag":
                    rebuild_async()
                else:
                    rebuild()
                self.send_json(200, {"ok": True, "message": message, "rebuilt": action not in ("delete", "cover", "tag")})
            except SystemExit:
                self.send_json(400, {"ok": False, "message": "找不到该册集或照片"})
            except Exception as exc:
                self.send_json(500, {"ok": False, "message": str(exc)[:300]})


if __name__ == "__main__":
    if not Path(UPDATE).is_file():
        sys.exit(f"未找到 {UPDATE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"album-api listening on {HOST}:{PORT}", flush=True)
    server.serve_forever()
