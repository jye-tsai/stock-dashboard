#!/usr/bin/env bash
# git 歷史瘦身:拿掉 data.json(v1 每 10 分鐘一版密文)、chips/data/*.png、chips/backtest/result.json 的舊版,
# 再把目前這一版 data.json / result.json / series 放回 main。2026-10-31 雲端實測:99.75 MiB → 26.9 MiB(media 分支 97 張 PNG 約 18 MB 留著)、4,031 → 564 commits。
# 什麼時候跑:data.json v2(PR #1)、media 分支(PR #2)、series 拆檔(PR #3)跑穩一週後;**週末跑**(平日每 10 分鐘有 Action 在 push)。
# 用法(Mac / Linux / Git Bash;需要 git-filter-repo:pip install git-filter-repo):
#   bash tools/slim-history.sh                     只重寫到暫存資料夾、印大小,不推
#   PUSH=1 bash tools/slim-history.sh              重寫完直接 force push 所有分支與 tag
# 推完:本機 clone 刪掉重新 clone(歷史不同了,pull 會衝突);Actions 每次都是新 checkout,不用動;Cloudflare / cron-job 不受影響。
set -eu
REPO="${REPO:-https://github.com/jye-tsai/stock-dashboard.git}"
TMP="${TMP:-$(mktemp -d)/slim}"
command -v git-filter-repo >/dev/null 2>&1 || git filter-repo --version >/dev/null 2>&1 || { echo "先 pip install git-filter-repo"; exit 1; }
echo "暫存:$TMP"
git clone -q --mirror "$REPO" "$TMP"
cd "$TMP"
echo "重寫前:$(git count-objects -vH | grep size-pack)、$(git rev-list --count --all) commits"
# mirror 會帶 GitHub 的 refs/pull/*(PR 的 head / merge),它們指著舊歷史、也推不回去:先刪,不然舊物件清不掉(2026-10-31 實測)
git for-each-ref --format='%(refname)' refs/pull | xargs -r -n1 git update-ref -d
# 先留住目前 main 上要放回去的檔
KEEP=$(mktemp -d)
git show main:data.json > "$KEEP/data.json"
git show main:chips/backtest/result.json > "$KEEP/result.json"
# 拿掉三類路徑的全部歷史(data.json 現版含 history,過去的值都在裡面,舊版沒有資訊)
# 只重寫 media 以外的分支:media 全是 PNG,拿掉 PNG 它就整個消失(2026-10-31 實測踩到)
REFS=$(git for-each-ref --format='%(refname)' refs/heads refs/tags | grep -v '^refs/heads/media$' | tr '\n' ' ')
# shellcheck disable=SC2086
git filter-repo --force --invert-paths \
  --path data.json \
  --path chips/backtest/result.json \
  --path-glob 'chips/data/*.png' \
  --refs $REFS
git reflog expire --expire=now --all
git gc --prune=now --aggressive -q
echo "重寫後:$(git count-objects -vH | grep size-pack)、$(git rev-list --count --all) commits"
# 放回目前版本(mirror 是 bare,worktree 出 main)
git worktree add -q "$TMP/_wt" main
cp "$KEEP/data.json" "$TMP/_wt/data.json"
mkdir -p "$TMP/_wt/chips/backtest"; cp "$KEEP/result.json" "$TMP/_wt/chips/backtest/result.json"
git -C "$TMP/_wt" -c user.name=panghu-bot -c user.email=bot@users.noreply.github.com add data.json chips/backtest/result.json
git -C "$TMP/_wt" -c user.name=panghu-bot -c user.email=bot@users.noreply.github.com commit -q -m "git 瘦身:歷史拿掉 data.json / PNG / result.json 舊版後,放回目前版本"
git worktree remove --force "$TMP/_wt"
echo "放回後 main:$(git ls-tree --name-only main | grep -c '^data.json$') data.json、$(git ls-tree -r --name-only main | grep -c 'chips/backtest/') backtest 檔"
if [ "${PUSH:-0}" = "1" ]; then
  # 不用 --mirror:mirror clone 帶 refs/pull/*,GitHub 拒收
  git push --force --all "$REPO"
  git push --force --tags "$REPO"
  echo "推完。本機 clone 重新 clone;Actions 下一班自動用新歷史。"
else
  echo "沒推(PUSH=1 才推)。要推:cd $TMP && git push --force --all $REPO && git push --force --tags $REPO"
fi
