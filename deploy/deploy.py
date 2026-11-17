#!/usr/bin/env python3
"""水上行走画册一键部署：生成 → 精简 → 部署（防缓存）

部署到盒子的 /root/digital_album/deploy.py，由 /root/update-album.sh 调用。
"""
import re
import sys
import shutil
from datetime import datetime
from pathlib import Path

SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/root/photograph')
WORK = Path('/root/digital_album')
SITE = Path('/srv/digital_album')
STAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
MAIN = f'album_{STAMP}.html'
PREFIX = f'album_{STAMP}-'
BOOK_URL = f'book.html?v={STAMP}'


def nav_html(active: str) -> str:
    gallery = ' aria-current="page"' if active == 'gallery' else ''
    book = ' aria-current="page"' if active == 'book' else ''
    return (
        '<nav class="site-nav" id="site-nav" aria-label="主导航">'
        f'<a href="index.html"{gallery}>照片库 <span>Archive</span></a>'
        f'<a href="{BOOK_URL}"{book}>画册 <span>Photo Book</span></a>'
        '</nav>'
    )


def foot_nav_html() -> str:
    return (
        '<nav class="footer-nav" aria-label="页脚导航">'
        '<a href="index.html">照片库</a>'
        f'<a href="{BOOK_URL}">画册</a>'
        '</nav>'
    )


def clean(html: str, active: str = 'gallery') -> str:
    html = re.sub(r'<nav class="site-nav".*?</nav>', nav_html(active), html, flags=re.S)
    html = re.sub(r'<nav class="footer-nav".*?</nav>', foot_nav_html(), html, flags=re.S)
    html = re.sub(r'<a class="text-link" href="albums\.html">返回手工册集</a>', '', html)
    html = html.replace('href="gallery-album-', f'href="{PREFIX}')
    html = html.replace('href="gallery.html"', 'href="index.html"')
    html = html.replace('href="css/style.css"', f'href="css/style.css?v={STAMP}"')
    html = html.replace('src="js/main.js"', f'src="js/main.js?v={STAMP}"')
    return html


def main():
    print(f'源目录: {SRC}')
    print(f'时间戳: {STAMP}')

    # 1. 生成
    import subprocess
    subprocess.run(
        [sys.executable, str(WORK / 'tools/build_gallery.py'),
         '--source', str(SRC), '--config', str(WORK / 'gallery.config.json')],
        check=True, cwd=WORK,
    )

    # 2. 精简 + 部署到带时间戳的新文件名（浏览器无缓存）
    gallery = clean((WORK / 'gallery.html').read_text(encoding='utf-8'))
    (SITE / MAIN).write_text(gallery, encoding='utf-8')
    (SITE / 'index.html').write_text(gallery, encoding='utf-8')

    count = 0
    for p in sorted(WORK.glob('gallery-album-*.html')):
        html = clean(p.read_text(encoding='utf-8'))
        slug = p.stem.replace('gallery-album-', '')
        (SITE / f'{PREFIX}{slug}.html').write_text(html, encoding='utf-8')
        count += 1

    book_src = WORK / 'book.html'
    if book_src.exists():
        (SITE / 'book.html').write_text(
            clean(book_src.read_text(encoding='utf-8'), 'book'), encoding='utf-8'
        )
        print('写入：book.html（画册页）')

    # 3. 复制生成图（覆盖即可）
    if (WORK / 'assets/generated').exists():
        dest = SITE / 'assets/generated'
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(WORK / 'assets/generated', dest)

    # 4. 清理旧的时间戳页面（保留最新一套 + index）
    for p in SITE.glob('album_*.html'):
        if p.name != MAIN and not p.name.startswith(PREFIX):
            p.unlink()

    print(f'完成：{count} 册，入口 index.html，新页面 {MAIN}')


if __name__ == '__main__':
    main()
