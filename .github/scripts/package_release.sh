#!/usr/bin/env bash
# 打包发布归档。清单只在此处维护：release.yml 发版与 ci.yml 的归档校验调用同一份脚本，
# 避免「发版清单」与「校验清单」各写一份之后逐渐漂移。
#
# 用法：bash .github/scripts/package_release.sh <前缀，例如 xhs-crawler-v0.1.0>
set -euo pipefail

PREFIX="${1:?用法: package_release.sh <前缀>}"

# desktop/ 与 extension/ 必须一并打包：包内 pyproject.toml 声明了
# xhs-insight = desktop.main:main 且 packages = ["desktop"]，
# 缺失会让下载者执行 uv sync 时因找不到 desktop 包而构建失败；
# extension/ 是桌面端浏览器桥接的运行前提。
INCLUDE=(
  skills scripts desktop extension
  SKILL.md pyproject.toml uv.lock LICENSE README.md
)

tar czf "${PREFIX}.tar.gz" \
  --transform "s,^,${PREFIX}/," \
  --exclude='__pycache__' --exclude='*.pyc' \
  "${INCLUDE[@]}"

zip -qr "${PREFIX}.zip" "${INCLUDE[@]}" -x '*.pyc' '__pycache__/*'

echo "已生成 ${PREFIX}.tar.gz 与 ${PREFIX}.zip"
