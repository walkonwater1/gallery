#!/bin/bash
# 在网站上隐藏 / 恢复照片（不删除本地文件，部署到盒子的 /root/start_sh/hide-photo.sh）
#   bash /root/start_sh/hide-photo.sh --list              列出各册已隐藏的照片
#   bash /root/start_sh/hide-photo.sh P1085284.jpg        隐藏这张
#   bash /root/start_sh/hide-photo.sh --show P1085284.jpg 恢复显示
exec python3 /root/lixin/digital_album/tools/hide_photo.py "$@"
