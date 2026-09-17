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

echo "已生成 ${PREFIX}.tar.gz"

# Windows 本机（含 Git for Windows）不带 zip，缺失时只跳过 .zip 并明确告知，
# 这样本地也能跑通 tar 一侧；CI 的 ubuntu runner 一定有 zip，
# 万一将来缺失，ci.yml 中对 .zip 的校验会因文件不存在而失败，不会被静默放过。
if command -v zip >/dev/null 2>&1; then
  zip -qr "${PREFIX}.zip" "${INCLUDE[@]}" -x '*.pyc' '__pycache__/*'
  echo "已生成 ${PREFIX}.zip"
else
  echo "::warning::未找到 zip，已跳过 ${PREFIX}.zip（仅生成 .tar.gz）"
fi
