#!/usr/bin/env python3
"""語彙の穴の定期レビュー用レポート。

毎巡「実例0の語はどれか」「どの軸が薄いか」「閾値に届かなかったタグは何か」を
その場限りのワンライナーで数えていたので、同じ数え方を毎回できるようにまとめた。

  python3 tools/report.py            … 全部
  python3 tools/report.py gaps       … 実例0の見出し語だけ
  python3 tools/report.py near       … 閾値に届かなかったタグの実測値だけ
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "docs" / "data" / "db.json"
SUGGESTIONS = ROOT / "data" / "suggestions.yaml"


def load_db() -> dict:
    if not DB.exists():
        raise SystemExit("docs/data/db.json がありません。先に python3 tools/build.py を実行してください。")
    return json.loads(DB.read_text(encoding="utf-8"))


def load_suggestions() -> list[dict]:
    if not SUGGESTIONS.exists():
        return []
    try:
        return yaml.safe_load(SUGGESTIONS.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as err:
        print(f"警告: {SUGGESTIONS} を読めません（{err.__class__.__name__}）")
        return []


def axis_names(db: dict) -> dict[str, str]:
    return {
        axis["id"]: f"{group['name']}/{axis['name']}"
        for group in db["groups"]
        for axis in group["axes"]
    }


def report_gaps(db: dict) -> None:
    """実例が付いていない見出し語。次にどのキャラを入れるかの根拠になる。"""
    names = axis_names(db)
    empty: dict[str, list[str]] = defaultdict(list)
    thin: dict[str, list[str]] = defaultdict(list)
    for element in db["elements"]:
        count = len(element.get("characters") or [])
        if count == 0:
            empty[element["axis"]].append(element["name"])
        elif count == 1:
            thin[element["axis"]].append(element["name"])

    total = len(db["elements"])
    filled = total - sum(len(v) for v in empty.values())
    print(f"■ 実例のある見出し語: {filled} / {total}")
    if empty:
        print(f"\n  実例0（{sum(len(v) for v in empty.values())} 語）")
        for axis in sorted(empty):
            print(f"    {names.get(axis, axis)}: {'・'.join(sorted(empty[axis]))}")
    if thin:
        print(f"\n  実例1件だけ（{sum(len(v) for v in thin.values())} 語）")
        for axis in sorted(thin):
            print(f"    {names.get(axis, axis)}: {'・'.join(sorted(thin[axis]))}")


def report_axes(db: dict) -> None:
    """軸ごとの語数と実例の付き方。語を足すべき軸を見つける。"""
    names = axis_names(db)
    print("\n■ 軸ごとの状況（語数 / 実例のある語 / 延べ採用数）")
    per_axis: dict[str, list[dict]] = defaultdict(list)
    for element in db["elements"]:
        per_axis[element["axis"]].append(element)
    for axis in sorted(per_axis, key=lambda a: (names.get(a, a))):
        items = per_axis[axis]
        used = sum(1 for e in items if e.get("characters"))
        hits = sum(len(e.get("characters") or []) for e in items)
        flag = "  ←薄い" if used < len(items) / 2 else ""
        print(f"  {names.get(axis, axis):<18} {len(items):>3} 語 / {used:>3} 語に実例 / 延べ {hits:>4}{flag}")


def report_near_miss(suggestions: list[dict]) -> None:
    """閾値に届かなかったタグの実測値。閾値を勘で下げないための材料。"""
    print("\n■ 閾値に届かなかった対応（near_miss）")
    best: dict[tuple[str, str], dict] = {}
    counts: Counter = Counter()
    for entry in suggestions:
        for miss in entry.get("near_miss") or []:
            key = (miss["id"], miss.get("tag") or "")
            counts[key] += 1
            if key not in best or miss["frequency"] > best[key]["frequency"]:
                best[key] = {**miss, "name": entry.get("name", entry["id"])}
    if not best:
        print("  記録なし（取り込みを一度も実行していないか、全て閾値を超えている）")
        return
    print("  見出し語        タグ                       最高値 閾値  件数  最高値のキャラ")
    for key, miss in sorted(best.items(), key=lambda kv: -kv[1]["frequency"]):
        print(
            f"  {key[0]:<14} {key[1]:<26} {miss['frequency']:.2f}  {miss['threshold']:.2f}"
            f"  {counts[key]:>3}   {miss['name']}"
        )
    print("  ※ 最高値が閾値のすぐ下で件数が多いものは、閾値を下げる根拠になる。")
    print("     逆に単発で低いものは、そのキャラの絵柄の揺れなので触らない。")


def report_unmapped(suggestions: list[dict]) -> None:
    """対応表に無い高頻度タグと、資料レーンからの新語提案。"""
    tags: Counter = Counter()
    tag_best: dict[str, float] = {}
    proposals: Counter = Counter()
    for entry in suggestions:
        for row in entry.get("unmapped_danbooru") or []:
            tags[row["tag"]] += 1
            tag_best[row["tag"]] = max(tag_best.get(row["tag"], 0.0), row["frequency"])
        for row in entry.get("new_tag_proposals") or []:
            label = row.get("name") or row.get("tag") or ""
            if label:
                proposals[label] += 1

    print(f"\n■ 対応表に無い高頻度タグ（{len(tags)} 種）")
    for tag, count in tags.most_common(30):
        mark = "  ←複数作品" if count >= 2 else ""
        print(f"  {tag:<34} {count:>2} 件 / 最高 {tag_best[tag]:.2f}{mark}")
    if not tags:
        print("  なし")

    print(f"\n■ 資料レーンからの新語提案（{len(proposals)} 種）")
    for label, count in proposals.most_common(40):
        mark = "  ←複数作品" if count >= 2 else ""
        print(f"  {label:<28} {count:>2} 件{mark}")
    if not proposals:
        print("  なし")


def report_characters(db: dict) -> None:
    """キャラ側の穴。画像・レーン・要素数。"""
    characters = db["characters"]
    no_image = [c for c in characters if not (c.get("image") or {}).get("url")]
    no_gemini = [
        c
        for c in characters
        if "gemini" not in ((c.get("analysis") or {}).get("method") or "")
    ]
    thin = sorted(characters, key=lambda c: len(c.get("elements") or []))[:10]
    print(f"\n■ キャラクター {len(characters)} 名")
    print(f"  画像なし: {len(no_image)} 名" + (f" … {'・'.join(c['name'] for c in no_image[:12])}" if no_image else ""))
    print(f"  資料レーン未通過: {len(no_gemini)} 名" + (f" … {'・'.join(c['name'] for c in no_gemini[:12])}" if no_gemini else ""))
    print("  要素数の少ない順:")
    for c in thin:
        print(f"    {len(c.get('elements') or []):>2} 要素  {c['name']}（{c['work']}）")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    db = load_db()
    suggestions = load_suggestions()
    if which in ("all", "gaps"):
        report_gaps(db)
    if which in ("all", "axes"):
        report_axes(db)
    if which in ("all", "near"):
        report_near_miss(suggestions)
    if which in ("all", "unmapped"):
        report_unmapped(suggestions)
    if which in ("all", "chars"):
        report_characters(db)


if __name__ == "__main__":
    main()
