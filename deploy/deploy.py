#!/usr/bin/env python3
"""水上行走画册一键部署：生成 → 精简 → 部署（防缓存）

部署到盒子的 /root/lixin/digital_album/deploy.py，由 /root/start_sh/update-album.sh 调用。
"""
import os
import re
import sys
import shutil
import fcntl
from datetime import datetime
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/root/photograph')
MAX_ALBUMS = int(sys.argv[2]) if len(sys.argv) > 2 else None
WORK = Path('/root/lixin/digital_album')
SITE = Path('/srv/digital_album')
STAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
MAIN = f'album_{STAMP}.html'
PREFIX = f'album_{STAMP}-'
BOOK_URL = f'book.html?v={STAMP}'


def nav_html(active: str) -> str:
    gallery = ' aria-current="page"' if active == 'gallery' else ''
    book = ' aria-current="page"' if active == 'book' else ''
    years = ''.join(
        f'<a href="index.html#year-{y}">{y}</a>' for y in (2026, 2025, 2024, 2023, 2022)
    )
    return (
        '<nav class="site-nav" id="site-nav" aria-label="主导航">'
        f'{years}'
        '<a href="index.html#film">胶片</a>'
        f'<a href="{BOOK_URL}"{book}>画册 <span>Photo Book</span></a>'
        '</nav>'
    )


def foot_nav_html() -> str:
    years = ''.join(
        f'<a href="index.html#year-{y}">{y}</a>' for y in (2026, 2025, 2024, 2023, 2022)
    )
    return (
        '<nav class="footer-nav" aria-label="页脚导航">'
        f'{years}'
        '<a href="index.html#film">胶片</a>'
        f'<a href="{BOOK_URL}">画册</a>'
        '</nav>'
    )


def clean(html: str, active: str = 'gallery') -> str:
    html = re.sub(r'<nav class="site-nav".*?</nav>', nav_html(active), html, flags=re.S)
    html = re.sub(r'<nav class="footer-nav".*?</nav>', foot_nav_html(), html, flags=re.S)
    html = re.sub(r'<a class="text-link" href="albums\.html">返回手工册集</a>', '', html)
    html = re.sub(
        r'href="gallery-([^"]+\.html)"',
        lambda m: f'href="{PREFIX}{m.group(1)}"',
        html,
    )
    html = html.replace('href="gallery.html"', 'href="index.html"')
    html = html.replace('href="css/style.css"', f'href="css/style.css?v={STAMP}"')
    html = html.replace('src="js/main.js"', f'src="js/main.js?v={STAMP}"')
    html = html.replace('href="assets/favicon.svg"', f'href="assets/favicon.svg?v={STAMP}"')
    return html


def main():
    # 同一时间只允许一个重建；等待锁而不是跳过，确保每次删除最终都会被生成
    lock_path = Path('/tmp/digital-album-deploy.lock')
    lock_file = lock_path.open('w')
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    print(f'源目录: {SRC}')
    print(f'时间戳: {STAMP}')

    # 1. 生成
    import subprocess
    cmd = [sys.executable, str(WORK / 'tools/build_gallery.py'),
           '--source', str(SRC), '--config', str(WORK / 'gallery.config.json')]
    if MAX_ALBUMS is not None:
        cmd += ['--max-albums', str(MAX_ALBUMS)]
    subprocess.run(cmd, check=True, cwd=WORK)

    # 2. 精简 + 部署到带时间戳的新文件名（浏览器无缓存）
    gallery = clean((WORK / 'gallery.html').read_text(encoding='utf-8'))
    (SITE / MAIN).write_text(gallery, encoding='utf-8')
    (SITE / 'index.html').write_text(gallery, encoding='utf-8')

    count = 0
    for p in sorted(WORK.glob('gallery-*.html')):
        html = clean(p.read_text(encoding='utf-8'))
        slug = p.stem[len('gallery-'):]
        (SITE / f'{PREFIX}{slug}.html').write_text(html, encoding='utf-8')
        count += 1

    book_src = WORK / 'book.html'
    if book_src.exists():
        (SITE / 'book.html').write_text(
            clean(book_src.read_text(encoding='utf-8'), 'book'), encoding='utf-8'
        )
        print('写入：book.html（画册页）')

    # 3. 复制生成图：先复制到临时目录，再原子替换，避免中途失败留下残缺目录
    if (WORK / 'assets/generated').exists():
        dest = SITE / 'assets/generated'
        tmp = SITE / '.assets-generated-next'
        if tmp.exists():
            shutil.rmtree(tmp)
        shutil.copytree(WORK / 'assets/generated', tmp)
        if dest.exists():
            shutil.rmtree(dest)
        tmp.rename(dest)
        for root, dirs, files in os.walk(dest):
            for name in dirs + files:
                shutil.chown(os.path.join(root, name), 33, 33)

    # 4. 清理旧的时间戳页面（保留最新一套 + index）
    for p in SITE.glob('album_*.html'):
        if p.name != MAIN and not p.name.startswith(PREFIX):
            p.unlink()

    print(f'完成：{count} 册，入口 index.html，新页面 {MAIN}')


if __name__ == '__main__':
    main()
