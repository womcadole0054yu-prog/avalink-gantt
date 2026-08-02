# -*- coding: utf-8 -*-
"""毎朝、ガントチャート(avalink-gantt.web.app)のデータを読んで
遅延・進行中・7日以内の公開を Discord(AVALINK) へ通知する。
データ源は Firestore gantt/state（サイトと同じもの）。
タスクスケジューラ GanttReport_Daily から毎朝実行される。
"""
import sys
import json
import datetime
import urllib.request

sys.path.insert(0, r'C:\Users\womca')
from notify_discord import notify  # noqa: E402

API_KEY = "AIzaSyB6lzTulB1ojHKHsToVVzo_fQjOknfDSAY"
URL = ("https://firestore.googleapis.com/v1/projects/slot-judge/"
       f"databases/(default)/documents/gantt/state?key={API_KEY}")
SITE = "https://avalink-gantt.web.app"


def to_date(s):
    y, m, d = map(int, s.split("-"))
    return datetime.date(y, m, d)


def main():
    with urllib.request.urlopen(URL, timeout=15) as r:
        doc = json.load(r)
    state = json.loads(doc["fields"]["json"]["stringValue"])

    today = datetime.date.today()
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
    lines.append(SITE)

    msg = "\n".join(lines)
    print(msg)
    notify(msg, category="AVALINK")


if __name__ == "__main__":
    main()
