#!/bin/zsh
# 用法: scripts/run.sh [提示词文件] [缓存 5m|1h] [预算美元]
# 例:   scripts/run.sh prompts/01-musou.md 5m 20
# 在仓库根目录运行；结果写到 runs/<名字>.json
set -e
pf=${1:-prompts/01-musou.md}
ttl=${2:-5m}
budget=${3:-20}
sys=prompts/builder_system.md
name=$(basename "$pf" .md)

mkdir -p runs
start=$(date +%s)

claude -p "$(cat "$pf")" \
  --model claude-fable-5-2 \
  --permission-mode auto \
  --append-system-prompt "$(cat "$sys")" \
  --settings "{\"promptCacheTtl\":\"$ttl\"}" \
  --max-budget-usd "$budget" \
  --output-format json < /dev/null > "runs/$name.json" 2> "runs/$name.err"

echo "$name exit=$? wall=$(( $(date +%s) - start ))s" | tee -a runs/wall.log