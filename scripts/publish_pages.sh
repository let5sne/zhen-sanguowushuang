#!/usr/bin/env bash
# 把 demos/index.html 发布到 GitHub Pages（gh-pages 分支根目录）
# 用法：scripts/publish_pages.sh
set -euo pipefail

cd "$(dirname "$0")/.."

URL="https://let5sne.github.io/zhen-sanguowushuang/"
WT=/tmp/zs-pages

git fetch -q origin gh-pages

if [ -d "$WT" ]; then
  git -C "$WT" fetch -q origin
  git -C "$WT" checkout -q gh-pages
  git -C "$WT" reset -q --hard origin/gh-pages
else
  git worktree add -q "$WT" gh-pages
fi

cp demos/index.html "$WT/index.html"
: > "$WT/.nojekyll"

git -C "$WT" add index.html .nojekyll
if ! git -C "$WT" diff --cached --quiet; then
  git -C "$WT" -c user.name="dsh" -c user.email="dsh@local" \
    commit -q -m "deploy: $(date '+%Y-%m-%d %H:%M')"
  git -C "$WT" push -q origin HEAD:gh-pages
  echo "已推送新构建"
else
  echo "内容未变化，跳过"
fi

echo "线上地址: $URL"