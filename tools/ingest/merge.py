#!/usr/bin/env python3
"""WD-Tagger の外見タグと Gemini Vision の読みを統合し、characters.yaml の断片を出力する。

  python3 tools/ingest/merge.py --tags work/tags.json --vision work/classify.json \
      --name 名前 --work 作品 --kana かな [--append]

比重は「継続して出ている特徴ほど骨格に近い」という前提で決める。
全カットに出続ける髪型は core、一カットだけの小物は spice になる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

CHARACTERS = common.ROOT / "data" / "characters.yaml"


def from_tags(tags_path: Path) -> tuple[list[dict], int]:
    """フレームごとのタグを見出し語へ翻訳する。"""
    payload = json.loads(tags_path.read_text(encoding="utf-8"))
    frames = payload["frames"]
    if not frames:
        return [], 0

    mapping = yaml.safe_load(common.WD_MAP.read_text(encoding="utf-8"))
    default_threshold = mapping.get("defaults", {}).get("threshold", 0.35)

    results = []
    for element_id, spec in mapping["elements"].items():
        threshold = spec.get("threshold", default_threshold)
        hits, best_score, best_tag = 0, 0.0, None
        for frame in frames:
            frame_best = 0.0
            frame_tag = None
            for tag in spec["tags"]:
                score = frame["tags"].get(tag, 0.0)
                if score > frame_best:
                    frame_best, frame_tag = score, tag
            if frame_best >= threshold:
                hits += 1
                if frame_best > best_score:
                    best_score, best_tag = frame_best, frame_tag
        if not hits:
            continue
        coverage = hits / len(frames)
        results.append(
            {
                "id": element_id,
                "weight": common.decide_weight(coverage, best_score),
                "confidence": common.confidence_of(best_score),
                "source": "wd-tagger",
                "note": f"{best_tag} {best_score:.2f} / {hits}・{len(frames)}枚",
                "_coverage": round(coverage, 2),
            }
        )
    return results, len(frames)


def from_vision(vision_path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(vision_path.read_text(encoding="utf-8"))
    items = [
        {
            "id": item["id"],
            "weight": item["weight"],
            "confidence": item["confidence"],
            "source": "gemini",
            "note": item.get("evidence", ""),
        }
        for item in payload.get("elements", [])
    ]
    return items, payload


def merge(items: list[dict]) -> list[dict]:
    """同じ見出し語が両方から出たら、強いほうの比重を採用してメモを併記する。"""
    merged: dict[str, dict] = {}
    for item in items:
        current = merged.get(item["id"])
        if current is None:
            merged[item["id"]] = dict(item)
            continue
        if common.WEIGHT_ORDER[item["weight"]] < common.WEIGHT_ORDER[current["weight"]]:
            current["weight"] = item["weight"]
        notes = [n for n in (current.get("note"), item.get("note")) if n]
        current["note"] = " / ".join(dict.fromkeys(notes))
        current["source"] = "both"
    return list(merged.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", type=Path, help="tagger.py の出力")
    parser.add_argument("--vision", type=Path, help="classify.py の出力")
    parser.add_argument("--name", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--kana", default="")
    parser.add_argument("--year", type=int)
    parser.add_argument("--author", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--id", dest="char_id")
    parser.add_argument("--cuts", type=int, help="カット数（scenes.py の cuts.json から）")
    parser.add_argument("--date", default="", help="分析日")
    parser.add_argument("--min-confidence", choices=["low", "mid", "high"], default="low")
    parser.add_argument("--append", action="store_true", help="data/characters.yaml に追記する")
    args = parser.parse_args()

    if not args.tags and not args.vision:
        raise SystemExit("--tags か --vision のどちらかは必要です。")

    db = common.load_db()
    known = {e["id"] for e in db["elements"]}

    items: list[dict] = []
    frames = 0
    vision_payload: dict = {}
    if args.tags:
        tag_items, frames = from_tags(args.tags)
        items += tag_items
    if args.vision:
        vision_items, vision_payload = from_vision(args.vision)
        items += vision_items

    unknown = sorted({i["id"] for i in items if i["id"] not in known})
    items = [i for i in items if i["id"] in known]

    order = {"low": 0, "mid": 1, "high": 2}
    dropped_low = [i for i in items if order[i["confidence"]] < order[args.min_confidence]]
    items = [i for i in items if order[i["confidence"]] >= order[args.min_confidence]]

    merged = merge(items)
    if not merged:
        raise SystemExit("採用できる要素がありませんでした。閾値を下げるか、フレームを見直してください。")

    methods = sorted({i["source"] for i in merged})
    entry = {
        "id": args.char_id or common.slugify(args.name),
        "name": args.name,
        "kana": args.kana or args.name,
        "work": args.work,
        "year": args.year,
        "author": args.author,
        "summary": args.summary or vision_payload.get("summary", "") or "（要記入）",
        "analysis": {
            "method": "+".join(methods),
            "model": (vision_payload.get("_meta") or {}).get("model", ""),
            "frames": frames or None,
            "cuts": args.cuts,
            "date": args.date,
        },
        "elements": [
            {"id": i["id"], "weight": i["weight"], "note": i["note"]} for i in merged
        ],
        "patterns": [],
    }

    text = common.emit_character_yaml(entry)
    if args.append:
        with CHARACTERS.open("a", encoding="utf-8") as fh:
            fh.write("\n" + text)
        print(f"data/characters.yaml に追記しました（{len(merged)} 要素）")
    else:
        print(text)

    print(f"\n# 内訳: " + ", ".join(f"{k} {sum(1 for i in merged if i['weight'] == k)}" for k in ("core", "sub", "spice")), file=sys.stderr)
    if unknown:
        print(f"# 語彙にない id を破棄: {', '.join(unknown)}", file=sys.stderr)
    if dropped_low:
        print(f"# 確度が足りず除外: {', '.join(i['id'] for i in dropped_low)}", file=sys.stderr)
    if vision_payload.get("space_time"):
        print(f"# 空間・時間: {vision_payload['space_time']}", file=sys.stderr)
    for tag in vision_payload.get("new_tags", []):
        print(f"# 新語の提案: {tag['name']}（{tag.get('axis','?')}）… {tag.get('reason','')}", file=sys.stderr)
    print("# patterns は自動では決めない。性癖の成立は人が判断すること。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
