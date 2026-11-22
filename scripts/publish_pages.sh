#!/usr/bin/env bash
# 把游戏发布到 GitHub Pages（gh-pages 分支根目录）
# 用法：
#   scripts/publish_pages.sh            # 默认：WebGPU 版为主页，原 WebGL 版保留在 /classic.html
#   scripts/publish_pages.sh classic    # 回退：原 WebGL 版为主页（旧行为）
set -euo pipefail

cd "$(dirname "$0")/.."

URL="https://let5sne.github.io/zhen-sanguowushuang/"
WT=/tmp/zs-pages
MODE="${1:-webgpu}"

git fetch -q origin gh-pages

if [ -d "$WT" ]; then
  git -C "$WT" fetch -q origin
  git -C "$WT" checkout -q gh-pages
  git -C "$WT" reset -q --hard origin/gh-pages
else
  git worktree add -q "$WT" gh-pages
fi

if [ "$MODE" = "classic" ]; then
  cp demos/index.html "$WT/index.html"
  rm -f "$WT/classic.html"
else
  # 主页：WebGPU 版（浏览器不支持 WebGPU 时自动回退 WebGL2 后端）
  cp demos/index-webgpu.html "$WT/index.html"
  # 旧版：原 WebGL 渲染器，留作对照与兜底
  cp demos/index.html "$WT/classic.html"
fi
: > "$WT/.nojekyll"

git -C "$WT" add -A index.html classic.html .nojekyll 2>/dev/null || git -C "$WT" add -A
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="dsh" -c user.email="dsh@local" \
    commit -q -m "deploy($MODE): $(date '+%Y-%m-%d %H:%M')"
  git -C "$WT" push -q origin HEAD:gh-pages
  echo "已推送新构建（$MODE）"
else
  echo "内容未变化，跳过"
fi

echo "线上地址: $URL"
[ "$MODE" != "classic" ] && echo "旧版:     ${URL}classic.html"
exit 0
