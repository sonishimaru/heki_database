#!/usr/bin/env python3
"""自動実行の生成物を、実行中に他が押した内容と突き合わせて統合する。

取り込みは 1 時間かかることがあり、その間に別の実行（push トリガや日次）が
先にコミットしてしまうと、最後の rebase が characters_auto.yaml で必ず衝突する。
生成物は行単位でマージできる種類のファイルではないので、rebase に任せず
「id 単位の集合演算」でここで解決する。

  python3 tools/ingest/reconcile.py <保存しておいた自分の出力ディレクトリ>

作業ツリー側（＝リモート最新）のファイルへ、自分の出力を id 単位で上書き統合する。
同じ id が両方にある場合は analysis.date が新しい方を採り、同日なら要素数が多い方を残す。
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ROOT = common.ROOT
TARGETS = ("data/characters_auto.yaml", "data/suggestions.yaml")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as err:
        print(f"  警告: {path} を読めません（{err.__class__.__name__}）。空として扱います。")
        return []


def newer(a: dict, b: dict) -> dict:
    """同じ id の 2 件から残す方を選ぶ。新しい分析日、同日なら要素数の多い方。"""
    da = (a.get("analysis") or {}).get("date", "") or a.get("date", "")
    db = (b.get("analysis") or {}).get("date", "") or b.get("date", "")
    if da != db:
        return a if da > db else b
    return a if len(a.get("elements") or []) >= len(b.get("elements") or []) else b


def union(mine: list[dict], theirs: list[dict]) -> list[dict]:
    merged = {e["id"]: e for e in theirs if e.get("id")}
    for entry in mine:
        cid = entry.get("id")
        if not cid:
            continue
        merged[cid] = newer(entry, merged[cid]) if cid in merged else entry
    return [merged[k] for k in sorted(merged)]


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("使い方: reconcile.py <自分の出力を保存したディレクトリ>")
    saved = Path(sys.argv[1])

    for rel in TARGETS:
        target = ROOT / rel
        backup = saved / Path(rel).name
        if not backup.exists():
            continue
        mine, theirs = load(backup), load(target)
        merged = union(mine, theirs)
        header = "\n".join(
            line for line in backup.read_text(encoding="utf-8").splitlines()
            if line.startswith("#")
        )
        if rel.endswith("characters_auto.yaml"):
            body = "\n".join(common.emit_character_yaml(e) for e in merged)
        else:
            body = yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, default_flow_style=False)
        target.write_text(header + "\n" + body, encoding="utf-8")
        print(f"  統合: {rel}（自分 {len(mine)} 件 + 相手 {len(theirs)} 件 → {len(merged)} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
