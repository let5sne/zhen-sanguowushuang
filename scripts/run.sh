#!/bin/zsh
# 用法: scripts/run.sh [提示词文件] [缓存 5m|1h] [预算美元]
# 例:   scripts/run.sh prompts/01-musou.md 5m 20
#       MODEL=claude-opus-4-6 scripts/run.sh prompts/02-photo.md 1h 60
#
# 在仓库根目录运行。产物：
#   runs/<名字>.json   完整 JSON 结果
#   runs/<名字>.err    stderr
#   runs/index.tsv     追加一行运行摘要（时间 / 模型 / 预算 / 实际花费 / 轮数 / 耗时）
#
# 可用环境变量：
#   MODEL     模型名或别名（默认 claude-fable-5-2）
#   SYS       系统提示词路径（默认 prompts/builder_system.md）
#   PERM      permission-mode（默认 auto）
set -e

pf=${1:-prompts/01-musou.md}
ttl=${2:-5m}
budget=${3:-20}
model=${MODEL:-claude-fable-5-2}
sys=${SYS:-prompts/builder_system.md}
perm=${PERM:-auto}

for f in "$pf" "$sys"; do
  [[ -r "$f" ]] || { echo "读不到 $f" >&2; exit 2; }
done

name=$(basename "$pf" .md)
mkdir -p runs
start=$(date +%s)

set +e
claude -p "$(cat "$pf")" \
  --model "$model" \
  --permission-mode "$perm" \
  --append-system-prompt "$(cat "$sys")" \
  --settings "{\"promptCacheTtl\":\"$ttl\"}" \
  --max-budget-usd "$budget" \
  --output-format json < /dev/null > "runs/$name.json" 2> "runs/$name.err"
code=$?
set -e

wall=$(( $(date +%s) - start ))

# 从结果里取花费 / 轮数 / 结束原因，缺字段就留空，不让摘要失败
summary=$(python3 - "$name" "$model" "$budget" "$wall" "$code" "$pf" <<'PY'
import json, sys, datetime, pathlib
name, model, budget, wall, code, pf = sys.argv[1:7]
p = pathlib.Path(f"runs/{name}.json")
cost = turns = stop = ""
try:
    d = json.loads(p.read_text())
    cost = f'{d.get("total_cost_usd", 0):.2f}'
    turns = d.get("num_turns", "")
    stop = d.get("terminal_reason") or d.get("stop_reason") or ""
except Exception:
    pass
ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
print("\t".join([ts, name, model, f"≤{budget}", cost, str(turns), f"{wall}s", f"exit={code}", stop, pf]))
PY
)
echo "$summary" >> runs/index.tsv
echo "$summary" | tee -a runs/wall.log
exit $code