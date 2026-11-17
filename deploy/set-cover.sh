#!/bin/bash
# 水上行走画册封面设置（部署到盒子的 /root/set-cover.sh）
# 用法: bash /root/set-cover.sh [册名] [文件名或序号]
#   bash /root/set-cover.sh                   列出所有册集和当前封面
#   bash /root/set-cover.sh --photos 泉州     列出该册照片和序号
#   bash /root/set-cover.sh 泉州 12           按序号设置封面
#   bash /root/set-cover.sh P1096445.jpg      按文件名设置封面
#   bash /root/set-cover.sh --clear 泉州      恢复默认封面
exec python3 /root/digital_album/tools/set_cover.py "$@"
