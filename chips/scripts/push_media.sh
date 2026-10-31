#!/usr/bin/env bash
# 把 chips/data/*.png(圖卡、永豐 PDF 轉圖)推到孤兒分支 media,main 不再帶 PNG。
# 為什麼(2026-10-31):每天 3～5 張 × 0.4～1 MB 進 main,30 天清掉也只是清工作樹,歷史每月多 30 MB 永遠不會小。
# media 分支每次重建成「單一 commit」再 force push(歷史永遠只有一層),只留 KEEP_DAYS 天的圖;
# 網址:https://raw.githubusercontent.com/<owner>/<repo>/media/chips/data/<檔名>(render_card.media_url 組;LINE 與籌碼站都用它)
# 用法(chips.yml 畫完圖、Commit 之前):bash chips/scripts/push_media.sh
set -eu
KEEP_DAYS="${KEEP_DAYS:-30}"
SRC=chips/data
shopt -s nullglob
NEW=( "$SRC"/*.png )
if [ ${#NEW[@]} -eq 0 ]; then echo "沒有新圖"; exit 0; fi
git config user.name  "panghu-bot"
git config user.email "bot@users.noreply.github.com"
W=$(mktemp -d)
# 明確寫 refspec:actions/checkout 與淺 clone 的 remote.origin.fetch 常只涵蓋 main,寫 `git fetch origin media` 不會產生 origin/media
if git fetch -q origin +refs/heads/media:refs/remotes/origin/media 2>/dev/null; then
  git worktree add -q --detach "$W" origin/media
  BASE_TREE=$(git rev-parse 'origin/media^{tree}')
else
  git worktree add -q --orphan -b media-tmp "$W"      # 第一次:還沒有 media 分支
  BASE_TREE=""
fi
mkdir -p "$W/$SRC"
cp -f "${NEW[@]}" "$W/$SRC/"
cutoff=$(TZ=Asia/Taipei date -d "-$KEEP_DAYS days" +%Y%m%d)
for f in "$W/$SRC"/*.png; do
  d=$(basename "$f" | grep -oE '[0-9]{8}' | head -1 || true)
  if [ -n "$d" ] && [ "$d" -lt "$cutoff" ]; then rm -f "$f"; fi
done
git -C "$W" checkout -q --orphan media-new
git -C "$W" add -A
if [ "$(git -C "$W" write-tree)" = "$BASE_TREE" ]; then
  echo "media 沒變"; git worktree remove --force "$W"; git branch -D media-tmp media-new >/dev/null 2>&1 || true; exit 0
fi
git -C "$W" commit -q -m "media $(TZ=Asia/Taipei date '+%Y-%m-%d %H:%M')"
for i in 1 2 3; do
  if git -C "$W" push -q --force origin HEAD:media; then echo "pushed media:$(ls "$W/$SRC" | wc -l) 張"; break; fi
  [ "$i" = 3 ] && { echo "::warning::media 推送三次都失敗,這班 LINE 只發文字"; break; }
  sleep 5
done
git worktree remove --force "$W"; git branch -D media-tmp media-new >/dev/null 2>&1 || true
