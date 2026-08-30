#!/usr/bin/env bash
# publish_release.sh — 把构建产物发布为 GitHub Release（生产通道，替代 raw 直链）
# 用法: ./publish_release.sh <tag> <bin路径> [<bin路径>...]
# 例如: ./publish_release.sh v1.0.0 firmware/releases/v1.0.0.bin
# 前提: 本机装有 gh CLI 且已认证 (gh auth login)，或设置 GH_TOKEN 环境变量。
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "usage: $0 <tag> <bin> [<bin>...]" >&2
  exit 1
fi
TAG="$1"; shift

if ! command -v gh >/dev/null 2>&1 && [ -z "${GH_TOKEN:-}" ]; then
  echo "需要 gh CLI（已认证）或 GH_TOKEN 环境变量" >&2
  exit 1
fi

# 创建 release（不存在时），tag 指向 main 最新提交
if ! gh release view "$TAG" >/dev/null 2>&1; then
  gh release create "$TAG" --title "$TAG" --notes "Agent Widget 固件 $TAG" --target main
  echo "release $TAG created"
else
  echo "release $TAG exists, uploading assets"
fi

for bin in "$@"; do
  gh release upload "$TAG" "$bin" --clobber
  echo "uploaded $bin"
done

echo "done: https://github.com/agent-widget/agent-widget/releases/tag/$TAG"
