#!/usr/bin/env bash
# 画册清单管理：默认泉州整册 + 手动加入的照片。
# 用法：
#   bash /root/start_sh/book-photo.sh                     查看清单
#   bash /root/start_sh/book-photo.sh --add P100001.jpg    加入画册
#   bash /root/start_sh/book-photo.sh --remove P100001.jpg 移出画册
exec python3 /root/lixin/digital_album/tools/book_photos.py "$@"
