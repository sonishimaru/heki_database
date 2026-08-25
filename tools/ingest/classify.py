#!/usr/bin/env python3
"""各レーンの証拠を集約し、一人のキャラクターを語彙へ分類する。画像は見ない。

収集レーン（映像の観察・台詞の統計・資料の事実）が作った証拠ファイルをテキストで渡し、
外見以外の軸の見出し語へ写像する。判定の根拠は必ず「どのレーンのどこ」で示させるので、
どの証拠にも基づかない判定は構造的に書けない。

  export GEMINI_API_KEY=...
  python3 tools/ingest/classify.py --character アーニャ \
      --facts work/facts.yaml \
      --observations work/observations.json \
      --speech work/speech.json \
      --out work/classify.json

三つの入力はどれも任意（最低一つ）。有名キャラなら --facts だけでも下書きが出る。
映像の観察は仕草・演技の精度を上げたいときに足す。

  # API を叩けない環境
  python3 tools/ingest/classify.py --character アーニャ --facts work/facts.yaml --prompt-only > prompt.txt
  python3 tools/ingest/classify.py --character アーニャ --from-json response.json

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
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "weight": {"type": "string", "enum": ["core", "sub", "spice"]},
                    "confidence": {"type": "string", "enum": ["high", "mid", "low"]},
                    "sources": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "weight", "confidence", "sources", "evidence"],
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
「{character}」について、下に並ぶ**証拠資料**だけを根拠に、語彙から当てはまる見出し語を選んでください。

## 判定の規則

- 根拠にできるのは証拠資料に書かれていることだけ。あなたの作品知識で補完しない。
  証拠にないが作品上ほぼ確実なことは、選んだ上で confidence を low にする。
- **sources には根拠を必ず列挙する**（例: "観察 scene 3", "台詞統計", "資料"）。
  根拠を挙げられない判定は書かない。
- weight は証拠の現れ方で決める:
  - core  … 複数の場面・複数のレーンにまたがって繰り返し現れる（その人物の骨格）
  - sub   … 明確に現れるが、場面やレーンが限られる
  - spice … 一度きりだが強く印象づけられている
- 外見（髪・目・顔・体・服装・小物）はここでは判定しない。静止画レーンの担当。
- 語彙にない概念は new_tags に回す。判断がつかないものは uncertain に書く。
- 迷ったら選ばない。漏れより誤りを避ける。

## summary の書き方

その人物を一文で。外見の説明ではなく、構造（何と何が同居しているか）を書く。

## 語彙

{vocabulary}

{evidence}"""


def observations_block(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    scenes = []
    for scene in payload["scenes"]:
        slim = {k: v for k, v in scene.items() if k not in ("images", "tagger_frames")}
        scenes.append(slim)
    return (
        "## 証拠: 映像の観察記録（シーンごとの機械的な記録。sources では \"観察 scene N\" と呼ぶ）\n\n"
        + json.dumps(scenes, ensure_ascii=False, indent=1)
    )


def speech_block(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return (
        "## 証拠: 台詞の統計（決定的な集計。sources では \"台詞統計\" と呼ぶ）\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=1)
    )


def facts_block(path: Path) -> str:
    return (
        "## 証拠: 資料による事実（公式プロフィール・設定・本編の出来事を人が書き出したもの。sources では \"資料\" と呼ぶ）\n\n"
        + path.read_text(encoding="utf-8").strip()
    )


def validate(result: dict, db: dict) -> dict:
    by_id = {e["id"]: e for e in db["elements"]}
    kept, dropped, out_of_scope, no_source = [], [], [], []
    for item in result.get("elements", []):
        element = by_id.get(item.get("id"))
        if element is None:
            dropped.append(str(item.get("id")))
            continue
        if element["group"] in common.VISUAL_GROUPS:
            out_of_scope.append(item["id"])
            continue
        if not item.get("sources"):
            no_source.append(item["id"])
            continue
        sources = "・".join(item["sources"][:4])
        item["evidence"] = f"{sources}: {item.get('evidence', '')}".strip()
        kept.append(item)
    result["elements"] = kept
    result["_dropped"] = dropped
    result["_out_of_scope"] = out_of_scope
    result["_no_source"] = no_source
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--observations", type=Path, help="observe.py の出力（映像レーン）")
    parser.add_argument("--speech", type=Path, help="speech.py の出力（台詞レーン）")
    parser.add_argument("--facts", type=Path, help="資料レーンの facts ファイル（YAML またはテキスト）")
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
        blocks = []
        if args.facts:
            blocks.append(facts_block(args.facts))
        if args.observations:
            blocks.append(observations_block(args.observations))
        if args.speech:
            blocks.append(speech_block(args.speech))
        if not blocks:
            raise SystemExit("--facts / --observations / --speech のいずれかは必要です（--from-json を使う場合を除く）。")

        prompt = PROMPT.format(
            character=args.character,
            vocabulary=common.vocabulary_block(db, non_visual),
            evidence="\n\n".join(blocks),
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
        ("_out_of_scope", "外見軸なので破棄（静止画レーンの担当）"),
        ("_no_source", "根拠がないので破棄"),
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
