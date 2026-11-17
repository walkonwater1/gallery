#!/usr/bin/env python3
"""水上行走画册本地管理接口。

让网页上的「设为封面」「不显示这张」等操作点一下就生效：写 album.json，
然后调用 /root/update-album.sh 重新生成。只监听 127.0.0.1，由 Nginx 反代。

    POST /api/cover        {"file": "P1096445.jpg"}
    POST /api/clear-cover  {"album": "泉州"}
    POST /api/hide         {"file": "P1085284.jpg"}
    POST /api/show         {"file": "P1085284.jpg"}
    POST /api/book-add     {"file": "P1096445.jpg"}
    POST /api/book-remove  {"file": "P1096445.jpg"}
    GET  /api/book
    GET  /api/status
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, "/root/digital_album/tools")
import set_cover as cover  # noqa: E402
import hide_photo as hide  # noqa: E402
import book_photos  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765
UPDATE = "/root/update-album.sh"
LOCK = threading.Lock()
ACTIONS = {"cover", "clear-cover", "hide", "show", "book-add", "book-remove"}


def find_photo(name: str):
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
    photo = matches[0]
    rel = photo.relative_to(cover.SOURCE)
    album_dir = cover.SOURCE / rel.parts[0] if len(rel.parts) > 1 else cover.SOURCE
    return album_dir, photo.name


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

    raise ValueError("未知操作")


def rebuild() -> None:
    result = subprocess.run(
        ["bash", UPDATE], capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-400:]
        raise RuntimeError("重新生成失败：" + detail)


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
                rebuild()
                self.send_json(200, {"ok": True, "message": message})
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
