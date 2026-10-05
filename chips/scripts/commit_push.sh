#!/usr/bin/env bash
# chips.yml 的兩個 Commit 步驟共用:把 chips/data 的變動 commit 並推上 main。
# 用法:bash chips/scripts/commit_push.sh "chips:"   → commit 訊息「chips: 2026-10-05 15:41」(通知標記那步傳 "chips: notified")
# 股價排程每 5 分鐘也在 push data.json,可能落在 checkout 與 push 之間 → 先 rebase 再 push,失敗重試 3 次。
# --autostash:工作目錄有 chips/data 以外的變動(例:被 commit 進去的 __pycache__)也照樣 rebase,不會整班推不上去;失敗時列出是哪些檔。
set -u
git config user.name  "panghu-bot"
git config user.email "bot@users.noreply.github.com"
git add chips/data
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git commit -q -m "$1 $(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M')"
for i in 1 2 3; do
  if git pull -q --rebase --autostash origin main && git push -q; then echo "pushed"; exit 0; fi
  git rebase --abort 2>/dev/null || true
  git status --porcelain | grep -v "^??" | head -5
  echo "push 失敗,重試 $i"; sleep 5
done
echo "::error::push 三次都失敗"; exit 1
