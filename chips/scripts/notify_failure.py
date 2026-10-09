# -*- coding: utf-8 -*-
"""notify_failure.py ─ chips.yml 有步驟失敗時發一則 LINE,寫哪一班、哪一步、執行紀錄網址。
2026-10-05 盤後三班都推不上去,LINE 沒發、也沒人知道,是使用者問了才發現 → 之後失敗會主動說。
只在排程觸發時跑(Cloudflare / cron-job.org / GitHub schedule),手動跑失敗看畫面就知道,不另外通知。
失敗步驟名稱用 GitHub API 查本次執行的 job(需 workflow 有 actions: read);查不到就只給網址。
需要:LINE_CHANNEL_TOKEN、LINE_USER_ID;GITHUB_TOKEN、GITHUB_REPOSITORY、GITHUB_RUN_ID(Actions 內建)、RUN_TITLE。
本機試訊息:python chips/scripts/notify_failure.py --dry-run"""
import os, sys

DRY = "--dry-run" in sys.argv

def failed_steps(get, repo, run_id, token):
    """本次執行裡 conclusion=failure 的步驟名稱(查不到回 [])"""
    try:
        r = get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/jobs",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=20)
        return [s["name"] for j in r.json().get("jobs", []) for s in j.get("steps", []) if s.get("conclusion") == "failure"]
    except Exception as e:
        print("notify_failure: 查失敗步驟失敗", repr(e)); return []

def message(title, steps, url):
    L = [f"⚠ 胖虎排程失敗:{title or 'chips'}"]
    L.append(f"失敗步驟:{'、'.join(steps)}" if steps else "失敗步驟:(查不到,看執行紀錄)")
    L.append("資料或 LINE 可能沒更新;同一班別的另一條路(Cloudflare / cron-job.org)若成功會補上。")
    if url: L.append(url)
    return "\n".join(L)

def main():
    repo, run_id = os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_RUN_ID", "")
    url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id else ""
    steps = []
    if not DRY and repo and run_id and os.getenv("GITHUB_TOKEN"):
        import requests
        steps = failed_steps(requests.get, repo, run_id, os.getenv("GITHUB_TOKEN"))
    text = message(os.getenv("RUN_TITLE", ""), steps, url)
    print(text)
    tok, uid = os.getenv("LINE_CHANNEL_TOKEN"), os.getenv("LINE_USER_ID")
    if DRY or not tok or not uid: return
    import requests
    r = requests.post("https://api.line.me/v2/bot/message/push",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
                      json={"to": uid, "messages": [{"type": "text", "text": text[:4900]}]}, timeout=20)
    print("notify_failure:", r.status_code, r.text[:120])

if __name__ == "__main__":
    main()
