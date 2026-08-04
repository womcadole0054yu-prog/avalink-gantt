# -*- coding: utf-8 -*-
"""毎朝、ガントチャート(avalink-gantt.web.app)のデータを読んで
遅延・進行中・7日以内の公開を Discord(AVALINK) へ通知する。
データ源は Firestore gantt/state（サイトと同じもの）。
タスクスケジューラ GanttReport_Daily から毎朝実行される。
"""
import os
import sys
import glob
import json
import datetime
import subprocess
import urllib.request

sys.path.insert(0, r'C:\Users\womca')
from notify_discord import notify  # noqa: E402

REPO_DIR = r'C:\Users\womca\avalink-gantt'
BACKUP_DIR = os.path.join(REPO_DIR, 'backups')
KEEP = 30  # 保持する世代数

API_KEY = "AIzaSyB6lzTulB1ojHKHsToVVzo_fQjOknfDSAY"
URL = ("https://firestore.googleapis.com/v1/projects/slot-judge/"
       f"databases/(default)/documents/gantt/state?key={API_KEY}")
SITE = "https://avalink-gantt.web.app"


def to_date(s):
    y, m, d = map(int, s.split("-"))
    return datetime.date(y, m, d)


def backup(state_json: str, today: datetime.date) -> bool:
    """クラウドの生JSONを日付付きで保存して30世代キープ。
    GitHubにもpushして事故（誤削除・全消し）に備える。失敗してもレポートは止めない。"""
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        path = os.path.join(BACKUP_DIR, f"gantt-{today:%Y%m%d}.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write(state_json)
        files = sorted(glob.glob(os.path.join(BACKUP_DIR, "gantt-*.json")))
        for old in files[:-KEEP]:
            os.remove(old)
        # GitHubへ退避（失敗しても無視。ネット断・認証切れ等）
        try:
            subprocess.run(["git", "-C", REPO_DIR, "add", "backups"],
                           capture_output=True, timeout=60)
            r = subprocess.run(["git", "-C", REPO_DIR, "commit", "-m",
                                f"backup {today:%Y-%m-%d}"],
                               capture_output=True, timeout=60)
            if r.returncode == 0:  # 変更があった時だけpush
                subprocess.run(["git", "-C", REPO_DIR, "push"],
                               capture_output=True, timeout=120)
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[backup] 失敗: {e}")
        return False


def main():
    no_notify = "--no-notify" in sys.argv
    with urllib.request.urlopen(URL, timeout=15) as r:
        doc = json.load(r)
    raw_json = doc["fields"]["json"]["stringValue"]
    state = json.loads(raw_json)

    today = datetime.date.today()
    backup_ok = backup(raw_json, today)
    delayed, running, releases = [], [], []
    for pr in state.get("projects", []):
        if pr.get("hidden"):
            continue
        for cy in pr.get("cycles", []):
            if cy.get("hidden"):
                continue
            for p in cy.get("phases", []):
                if p.get("hidden"):
                    continue
                try:
                    s, e = to_date(p["start"]), to_date(p["end"])
                except Exception:
                    continue
                is_release = "公開" in p.get("name", "")
                if p.get("status") != "done" and e < today:
                    delayed.append((pr["name"], p["name"], (today - e).days))
                    continue
                if is_release:
                    diff = (s - today).days
                    if 0 <= diff <= 7:
                        releases.append((pr["name"], p["name"], diff))
                elif s <= today <= e and p.get("status") != "done":
                    running.append((pr["name"], p["name"]))

    delayed.sort(key=lambda x: -x[2])
    releases.sort(key=lambda x: x[2])

    lines = [f"📅 **制作スケジュール 朝レポ {today.month}/{today.day}**"]
    if delayed:
        lines.append(f"⚠️ **遅延 {len(delayed)}件**（終了日超過なのに未完了）")
        for pr, name, days in delayed[:8]:
            lines.append(f"・{pr}｜{name}（+{days}日）")
        if len(delayed) > 8:
            lines.append(f"　…他{len(delayed) - 8}件")
    if releases:
        lines.append("🎬 **7日以内の公開**")
        for pr, name, diff in releases:
            when = "今日!" if diff == 0 else f"{diff}日後"
            lines.append(f"・{pr}｜{name}（{when}）")
    if running:
        head = " / ".join(f"{pr}｜{name}" for pr, name in running[:6])
        tail = f" 他{len(running) - 6}件" if len(running) > 6 else ""
        lines.append(f"▶ 進行中: {head}{tail}")
    if len(lines) == 1:
        lines.append("遅延なし・直近の公開なし ✨")
    if not backup_ok:
        lines.append("⚠️ 自動バックアップに失敗（要確認）")
    lines.append(SITE)

    msg = "\n".join(lines)
    print(msg)
    if not no_notify:
        notify(msg, category="AVALINK")


if __name__ == "__main__":
    main()
