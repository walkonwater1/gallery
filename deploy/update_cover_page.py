#!/usr/bin/env python3
"""增量更新封面：设置封面后只改首页对应册集的封面图引用，秒级完成。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

WORK = Path('/root/lixin/digital_album')
SITE = Path('/srv/digital_album')
CACHE = WORK / '.gallery-cache/manifest.json'


def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding='utf-8'))


def find_cover(photo_name: str, cache: dict) -> dict:
    matches = [v for k, v in cache['photos'].items() if Path(k).name == photo_name]
    if not matches:
        raise SystemExit(f'缓存里找不到照片 {photo_name}')
    if len(matches) > 1:
        raise SystemExit(f'有 {len(matches)} 张同名照片，请用完整相对路径')
    return matches[0]


def patch_html(html: str, slug: str, thumb: str, hi: str, cover_w: int, cover_h: int):
    count = 0
    orientation = 'is-portrait' if cover_h > cover_w else 'is-landscape'
    ratio = f'{cover_w} / {cover_h}'

    # 更新外层 article 的朝向 class
    def article_repl(m):
        block = m.group(0)
        if f'/{slug}/' not in block:
            return block
        new = re.sub(r'archive-item (is-portrait|is-landscape)', f'archive-item {orientation}', block)
        return new

    html = re.sub(r'<article class="archive-item[^"]*">.*?</article>', article_repl, html, flags=re.S)

    # 更新封面图链接的比例与图片路径
    def visual_repl(m):
        nonlocal count
        block = m.group(0)
        if f'/{slug}/' not in block:
            return block
        new = re.sub(r'--cover-ratio: [^;"]+', f'--cover-ratio: {ratio}', block)
        new = re.sub(r'src="[^"]*"', f'src="{thumb}"', new)
        new = re.sub(r'data-hi="[^"]*"', f'data-hi="{hi}"', new)
        new = re.sub(r'width="\d+"', f'width="{cover_w}"', new)
        new = re.sub(r'height="\d+"', f'height="{cover_h}"', new)
        count += 1
        return new

    return re.sub(r'<a class="archive-visual[^"]*".*?</a>', visual_repl, html, flags=re.S), count


def patch_index(slug: str, thumb: str, hi: str, large: str, cover_w: int, cover_h: int) -> int:
    """首页封面与册集页头图路径都含 slug，按 slug 定位更新。"""
    total = 0
    pages = [SITE / 'index.html'] + sorted(
        SITE.glob('album_*.html'), key=lambda p: p.stat().st_mtime, reverse=True
    )[:1]
    for page in pages:
        if not page.exists():
            continue
        html = page.read_text(encoding='utf-8')
        new_html, count = patch_html(html, slug, thumb, hi, cover_w, cover_h)
        # 册集页头图（album-hero-bg）用 1800 大图
        new_html = re.sub(
            r'<img class="album-hero-bg"[^>]*>',
            lambda m: re.sub(r'src="[^"]*"', f'src="{large}"', m.group(0))
            if f'/{slug}/' in m.group(0) else m.group(0),
            new_html,
        )
        if new_html != html:
            page.write_text(new_html, encoding='utf-8')
            total += max(count, 1)
    return total


def main() -> None:
    photo_name = str(sys.argv[1]).strip()
    cache = load_cache()
    cover = find_cover(photo_name, cache)
    slug = cover['slug']
    out = cover['outputs']
    thumb = out['480']['path']
    hi = out['1100']['path']
    large = out['1800']['path']
    cover_w = out['1100']['w']
    cover_h = out['1100']['h']
    n = patch_index(slug, thumb, hi, large, cover_w, cover_h)
    print(f'封面已更新：{photo_name} → {n} 处（册集 {slug}）')


if __name__ == '__main__':
    main()
