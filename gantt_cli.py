# -*- coding: utf-8 -*-
"""ガントの本番データ（Firestore gantt/state）を安全に読み書きする道具。
📅ペトラ（avalink-pm）の手順書 ai-staff/playbooks/gantt-update.md から使う。

  python -X utf8 gantt_cli.py summary                    # 件数・フィールド名・状態の値・遅延・7日以内の公開
  python -X utf8 gantt_cli.py pull [out.json]            # 本番を整形JSONで保存（既定 work/gantt_state.json）
  python -X utf8 gantt_cli.py push <file> --dry-run      # 本番との差分件数だけ表示（書き込まない）
  python -X utf8 gantt_cli.py push <file>                # 自動バックアップ → 書き込み
  python -X utf8 gantt_cli.py push <file> --allow-delete # フェーズの削除を含むときだけ付ける

なぜスクリプトにしたか: 社内の人がリアルタイムで見ている本番データを、AIが毎回手で
REST PATCH すると「バックアップ忘れ」「消してはいけないものを消す」が起こり得る。決まった
安全手順はコードに固定して、AIは中身の編集だけに集中させる（トークンも節約）。
"""
import datetime
import json
import re
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
# APIキーは gantt_report.py にあるものを読む（二重管理しない）
KEY = re.search(r'API_KEY = "([^"]+)"', (ROOT / 'gantt_report.py').read_text(encoding='utf-8')).group(1)
DOC = ('https://firestore.googleapis.com/v1/projects/slot-judge/'
       'databases/(default)/documents/gantt/state')
WORK = ROOT / 'work' / 'gantt_state.json'
BACKUPS = ROOT / 'backups'


def get_raw():
    with urllib.request.urlopen(f'{DOC}?key={KEY}', timeout=20) as r:
        return json.load(r)['fields']['json']['stringValue']


def phases(state):
    for pr in state.get('projects', []):
        for cy in pr.get('cycles', []):
            for p in cy.get('phases', []):
                yield pr, cy, p


def pkey(pr, cy, p):
    return str(p.get('id') or f"{pr.get('name')}|{cy.get('name')}|{p.get('name')}|{p.get('start')}")


def diff(old, new):
    a = {pkey(*t): t[2] for t in phases(old)}
    b = {pkey(*t): t[2] for t in phases(new)}
    added = [k for k in b if k not in a]
    removed = [k for k in a if k not in b]
    changed = [k for k in b if k in a and a[k] != b[k]]
    return added, removed, changed, a, b


def cmd_summary():
    state = json.loads(get_raw())
    today = datetime.date.today()
    keys, statuses = set(), {}
    delayed, releases, n = [], [], 0
    for pr, cy, p in phases(state):
        n += 1
        keys.update(p.keys())
        statuses[p.get('status')] = statuses.get(p.get('status'), 0) + 1
        if p.get('hidden') or pr.get('hidden') or cy.get('hidden'):
            continue
        try:
            s = datetime.date.fromisoformat(p['start'])
            e = datetime.date.fromisoformat(p['end'])
        except Exception:
            continue
        if p.get('status') != 'done' and e < today:
            delayed.append(f"{pr.get('name')} / {cy.get('name')} / {p.get('name')}（終了 {e}・{(today - e).days}日超過）")
        if '公開' in p.get('name', '') and today <= s <= today + datetime.timedelta(days=7):
            releases.append(f"{s} {pr.get('name')} / {p.get('name')}")
    print(f"プロジェクト {len(state.get('projects', []))} / "
          f"サイクル {sum(len(pr.get('cycles', [])) for pr in state.get('projects', []))} / フェーズ {n}")
    print('プロジェクト名:', ', '.join(pr.get('name', '?') for pr in state.get('projects', [])))
    print('フェーズのフィールド名:', ', '.join(sorted(keys)))
    print('status の値と件数:', statuses)
    print(f'遅延 {len(delayed)}件:')
    # 全件出す（30件で切っていたらペトラが work/ から自分で抜き出す手間＝トークンが増えた・2026-09-13）
    for d in delayed:
        print('  -', d)
    print(f'7日以内の公開 {len(releases)}件:')
    for r in sorted(releases):
        print('  -', r)


def cmd_pull(out):
    out = Path(out) if out else WORK
    out.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(get_raw())
    out.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'保存: {out}')


def cmd_push(path, dry, allow_delete):
    new = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(new.get('projects'), list) or not new['projects']:
        print('❌ projects が空か形式が違う。書き込まない')
        return 2
    raw = get_raw()
    old = json.loads(raw)
    added, removed, changed, a, b = diff(old, new)
    print(f'差分: 追加 {len(added)} / 変更 {len(changed)} / 削除 {len(removed)}')
    for k in added[:20]:
        print('  + ', k)
    for k in changed[:20]:
        fields = sorted(f for f in set(a[k]) | set(b[k]) if a[k].get(f) != b[k].get(f))
        print('  ~ ', k, '→', ', '.join(f'{f}: {a[k].get(f)!r}→{b[k].get(f)!r}' for f in fields))
    for k in removed[:20]:
        print('  - ', k)
    if removed and not allow_delete:
        print('❌ 削除が含まれている。依頼どおりの削除なら --allow-delete を付けて実行し直す')
        return 2
    if dry:
        print('（--dry-run なので書き込んでいない）')
        return 0
    if not (added or changed or removed):
        print('差分なし。書き込まない')
        return 0
    BACKUPS.mkdir(exist_ok=True)
    bk = BACKUPS / f'manual-{datetime.datetime.now():%Y%m%d-%H%M%S}.json'
    bk.write_text(raw, encoding='utf-8')
    print(f'バックアップ: {bk}')
    body = json.dumps({'fields': {'json': {'stringValue':
                       json.dumps(new, ensure_ascii=False, separators=(',', ':'))}}}).encode('utf-8')
    req = urllib.request.Request(f'{DOC}?key={KEY}&updateMask.fieldPaths=json', data=body,
                                 method='PATCH', headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()
    after = json.loads(get_raw())
    ok = not any(diff(new, after)[:3])
    print('✅ 書き込み完了・本番と一致' if ok else '⚠️ 書き込んだが本番と一致しない（バックアップから戻すか確認）')
    return 0 if ok else 1


def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    flags = {x for x in sys.argv[1:] if x.startswith('--')}
    if not args:
        print(__doc__)
        return 2
    if args[0] == 'summary':
        cmd_summary()
        return 0
    if args[0] == 'pull':
        cmd_pull(args[1] if len(args) > 1 else None)
        return 0
    if args[0] == 'push' and len(args) > 1:
        return cmd_push(args[1], '--dry-run' in flags, '--allow-delete' in flags)
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main())
