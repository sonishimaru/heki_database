#!/usr/bin/env python3
"""Gemini Vision でカットを読み、演技と空間・時間、そして外見以外の軸を埋める。

WD-Tagger が担当するのは静止画から確実に読める外見だけなので、
気質・関係・展開・構造といった「動きと文脈がないと分からない層」をここで拾う。
あわせて、静止画分析に回す価値のあるフレームを選ばせる。

  export GEMINI_API_KEY=...
  python3 tools/ingest/vision.py --name 名前 --work 作品 --images work/frames/cut-00*.jpg

API を叩けない環境では次の二段で同じことができる:

  python3 tools/ingest/vision.py --prompt-only > prompt.txt   # AI Studio に貼る
  python3 tools/ingest/vision.py --from-json response.json --name 名前 --work 作品
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "space_time": {"type": "string"},
        "acting": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frame": {"type": "string"}, "observation": {"type": "string"}},
                "required": ["frame", "observation"],
            },
        },
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "weight": {"type": "string", "enum": ["core", "sub", "spice"]},
                    "confidence": {"type": "string", "enum": ["high", "mid", "low"]},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "weight", "confidence", "evidence"],
            },
        },
        "recommended_frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"frame": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["frame", "reason"],
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
    "required": ["summary", "space_time", "acting", "elements", "recommended_frames"],
}

PROMPT = """あなたはキャラクターを構成要素へ分解する辞典の編集者です。
渡されるのは、ある作品から連続したカットを抜き出した静止画です。

## やること

1. **空間と時間**を押さえる。どこで、いつ、誰と誰が、どういう配置でいるか。
   カットの並び順から、時間が進んでいるのか同時刻なのかも判断する。
2. **演技**を読む。表情の変化、視線の向き、手の位置、姿勢、間の取り方。
   静止画の一枚一枚ではなく、カット間の差分として読むこと。
3. そこから、下の語彙のうち**当てはまる見出し語**を選ぶ。
4. 静止画のタグ付けに回す価値のあるフレームを選ぶ（recommended_frames）。
   人物が大きく写り、髪型・服装・小物がはっきり見えるものを優先する。

## 守ること

- **語彙にない id は書かない。** 該当する概念が語彙になければ new_tags に回す。
- **髪型・服装・小物・目の形といった外見は判定しない。** それは別の工程が担当する。
  ここで拾うのは、動きと文脈がないと分からない層（気質・関係・展開・構造）だけ。
- evidence には「どのフレームの何を見てそう判断したか」を一言で書く。
  絵から読めず、作品知識に頼った推論なら confidence を low にする。
- **漏れより誤りを避ける。** 迷ったら選ばない。判断がつかなかったものは uncertain に書く。
- weight は core（その人物の骨格）/ sub（補強）/ spice（一点だけ差さっている）。

## 語彙

{vocabulary}
"""

NOTES_BLOCK = """
## 補足情報（利用者が与えたもの）

{notes}
"""


def build_prompt(db: dict, notes: str | None) -> str:
    non_visual = {g["id"] for g in db["groups"]} - common.VISUAL_GROUPS
    prompt = PROMPT.format(vocabulary=common.vocabulary_block(db, non_visual))
    if notes:
        prompt += NOTES_BLOCK.format(notes=notes.strip())
    return prompt


def call_gemini(model: str, prompt: str, images: list[Path], api_key: str) -> dict:
    parts: list[dict] = [{"text": prompt}]
    for path in images:
        mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
            }
        )
        parts.append({"text": f"（上の画像のファイル名: {path.name}）"})

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
        },
    }
    request = urllib.request.Request(
        ENDPOINT.format(model=model) + f"?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as err:
        raise SystemExit(f"Gemini API エラー {err.code}: {err.read().decode('utf-8', 'replace')[:500]}")
    text = payload["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def validate(result: dict, db: dict) -> dict:
    """語彙にない id と、外見軸に踏み込んだ判定を落とす。"""
    by_id = {e["id"]: e for e in db["elements"]}
    kept, dropped, out_of_scope = [], [], []
    for item in result.get("elements", []):
        element = by_id.get(item.get("id"))
        if element is None:
            dropped.append(item.get("id"))
            continue
        if element["group"] in common.VISUAL_GROUPS:
            out_of_scope.append(item["id"])
            continue
        kept.append(item)
    result["elements"] = kept
    result["_dropped"] = dropped
    result["_out_of_scope"] = out_of_scope
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", nargs="*", default=[], type=Path)
    parser.add_argument("--name")
    parser.add_argument("--work")
    parser.add_argument("--kana", default="")
    parser.add_argument("--year", type=int)
    parser.add_argument("--author", default="")
    parser.add_argument("--notes", type=Path, help="あらすじや設定のメモ（任意）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-only", action="store_true", help="プロンプトだけ出力する")
    parser.add_argument("--from-json", type=Path, help="保存済みの応答 JSON を読み込む")
    parser.add_argument("--out", default="work/vision.json")
    args = parser.parse_args()

    db = common.load_db()
    notes = args.notes.read_text(encoding="utf-8") if args.notes else None
    prompt = build_prompt(db, notes)

    if args.prompt_only:
        print(prompt)
        return 0

    if args.from_json:
        result = json.loads(args.from_json.read_text(encoding="utf-8"))
    else:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise SystemExit("GEMINI_API_KEY が未設定です。--prompt-only で出したプロンプトを AI Studio に貼る方法もあります。")
        if not args.images:
            raise SystemExit("--images に解析するフレームを渡してください。")
        result = call_gemini(args.model, prompt, args.images, api_key)

    result = validate(result, db)
    result["_meta"] = {
        "name": args.name,
        "kana": args.kana,
        "work": args.work,
        "year": args.year,
        "author": args.author,
        "model": args.model if not args.from_json else f"{args.model}（手動実行）",
        "frames": len(args.images),
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"採用 {len(result['elements'])} 要素 → {out}")
    if result["_dropped"]:
        print(f"  語彙にない id を破棄: {', '.join(str(x) for x in result['_dropped'])}")
    if result["_out_of_scope"]:
        print(f"  外見軸なので破棄（WD-Tagger の担当）: {', '.join(result['_out_of_scope'])}")
    for tag in result.get("new_tags", []):
        print(f"  新語の提案: {tag['name']}（{tag.get('axis', '?')}）… {tag.get('reason', '')}")
    for frame in result.get("recommended_frames", []):
        print(f"  静止画分析おすすめ: {frame['frame']} … {frame['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
