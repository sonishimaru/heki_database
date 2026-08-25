#!/usr/bin/env python3
"""観察記録を横断して、一人のキャラクターを語彙へ分類する。画像は見ない。

observe.py が溜めたシーン観察（と、あれば WD-Tagger の集計）をテキストで渡し、
外見以外の軸の見出し語へ写像する。分類の根拠は必ず観察記録のシーン番号で示させるので、
「どのシーンにも根拠がない判定」は構造的に書けない。
複数シーンで繰り返し観察された挙動だけが core になる。

  export GEMINI_API_KEY=...
  python3 tools/ingest/classify.py --observations work/observations.json \
      --character アーニャ --out work/classify.json

  # API を叩けない環境
  python3 tools/ingest/classify.py --observations work/observations.json \
      --character アーニャ --prompt-only > prompt.txt
  python3 tools/ingest/classify.py --from-json response.json --character アーニャ

出力は merge.py の --vision 入力としてそのまま使える。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DEFAULT_MODEL = os.environ.get("GEMINI_CLASSIFY_MODEL", "gemini-2.5-pro")

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "space_time": {"type": "string"},
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "weight": {"type": "string", "enum": ["core", "sub", "spice"]},
                    "confidence": {"type": "string", "enum": ["high", "mid", "low"]},
                    "scenes": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "weight", "confidence", "scenes", "evidence"],
            },
        },
        "new_tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "axis": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["name", "axis", "reason"],
            },
        },
        "uncertain": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "elements"],
}

PROMPT = """あなたはキャラクターを構成要素へ分解する辞典の編集者です。
渡されるのは、映像から機械的に起こした**シーンごとの観察記録**（JSON）です。
このうち「{character}」について、下の語彙から当てはまる見出し語を選んでください。

## 判定の規則

- 根拠にできるのは観察記録に書かれていることだけ。作品知識で補完しない。
  観察記録から読めないが作品上ほぼ確実なことは、選んだ上で confidence を low にする。
- **scenes には根拠となったシーン番号を必ず列挙する。** 根拠シーンを挙げられない判定は書かない。
- weight は登場の仕方で決める:
  - core  … 複数のシーンにまたがって繰り返し観察される（その人物の骨格）
  - sub   … 明確に観察されるが、場面が限られる
  - spice … 一度だけだが強く印象づけられている
- 外見（髪・目・顔・体・服装・小物）はここでは判定しない。別工程の担当。
- 語彙にない概念は new_tags に回す。判断がつかないものは uncertain に書く。
- 迷ったら選ばない。漏れより誤りを避ける。

## summary の書き方

その人物を一文で。外見の説明ではなく、構造（何と何が同居しているか）を書く。

## 語彙

{vocabulary}

## 観察記録

{observations}
{tags_block}"""

TAGS_BLOCK = """
## 外見タグの集計（参考情報。判定対象ではない）

{tags}
"""


def observations_for_prompt(payload: dict) -> str:
    """観察記録から、プロンプトに不要なフィールドを落として詰める。"""
    scenes = []
    for scene in payload["scenes"]:
        slim = {k: v for k, v in scene.items() if k not in ("images", "tagger_frames")}
        scenes.append(slim)
    return json.dumps(scenes, ensure_ascii=False, indent=1)


def tags_summary(tags_path: Path) -> str:
    payload = json.loads(tags_path.read_text(encoding="utf-8"))
    from collections import Counter

    best: Counter = Counter()
    for frame in payload["frames"]:
        for tag, score in frame["tags"].items():
            best[tag] = max(best[tag], score)
    top = ", ".join(f"{t} {s:.2f}" for t, s in best.most_common(40))
    return top


def validate(result: dict, db: dict) -> dict:
    by_id = {e["id"]: e for e in db["elements"]}
    kept, dropped, out_of_scope, no_scene = [], [], [], []
    for item in result.get("elements", []):
        element = by_id.get(item.get("id"))
        if element is None:
            dropped.append(str(item.get("id")))
            continue
        if element["group"] in common.VISUAL_GROUPS:
            out_of_scope.append(item["id"])
            continue
        if not item.get("scenes"):
            no_scene.append(item["id"])
            continue
        scenes = "・".join(item["scenes"][:4])
        item["evidence"] = f"scene {scenes}: {item.get('evidence', '')}".strip()
        kept.append(item)
    result["elements"] = kept
    result["_dropped"] = dropped
    result["_out_of_scope"] = out_of_scope
    result["_no_scene"] = no_scene
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, help="observe.py の出力")
    parser.add_argument("--character", required=True, help="観察記録内での人物名")
    parser.add_argument("--tags", type=Path, help="tagger.py の出力（参考情報として渡す）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-only", action="store_true")
    parser.add_argument("--from-json", type=Path)
    parser.add_argument("--out", default="work/classify.json")
    args = parser.parse_args()

    db = common.load_db()
    non_visual = {g["id"] for g in db["groups"]} - common.VISUAL_GROUPS

    if args.from_json:
        result = json.loads(args.from_json.read_text(encoding="utf-8"))
        model = f"{args.model}（手動実行）"
    else:
        if not args.observations:
            raise SystemExit("--observations が必要です（--from-json を使う場合を除く）。")
        payload = json.loads(args.observations.read_text(encoding="utf-8"))
        prompt = PROMPT.format(
            character=args.character,
            vocabulary=common.vocabulary_block(db, non_visual),
            observations=observations_for_prompt(payload),
            tags_block=TAGS_BLOCK.format(tags=tags_summary(args.tags)) if args.tags else "",
        )
        if args.prompt_only:
            print(prompt)
            return 0
        result = common.call_gemini(args.model, [{"text": prompt}], SCHEMA, common.gemini_api_key())
        model = args.model

    result = validate(result, db)
    result["_meta"] = {"character": args.character, "model": model}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"採用 {len(result['elements'])} 要素 → {out}")
    for key, label in (
        ("_dropped", "語彙にない id を破棄"),
        ("_out_of_scope", "外見軸なので破棄（WD-Tagger の担当）"),
        ("_no_scene", "根拠シーンがないので破棄"),
    ):
        if result[key]:
            print(f"  {label}: {', '.join(result[key])}")
    for tag in result.get("new_tags", []):
        print(f"  新語の提案: {tag['name']}（{tag.get('axis', '?')}）… {tag.get('reason', '')}")
    for item in result.get("uncertain", []):
        print(f"  保留: {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
