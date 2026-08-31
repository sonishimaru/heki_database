#!/usr/bin/env python3
"""識別レーン。「オタクがそのキャラを指すときに挙げる特徴」をモデルの作品知識から引く。

他の三レーン（静止画・映像・台詞）と classify は、外部の証拠に書かれたことしか
採らない。誤りを防ぐには正しい設計だが、そのぶん取りこぼす種類の特徴がある。

  市丸ギン → 糸目・関西弁
  この二つは Danbooru のタグ付与率では閾値に届かず（closed_eyes は瞬きと
  区別されない）、AniList の英語あらすじにも書かれない。どちらのレーンからも
  永久に出てこないが、読者がその人物を思い出すときに真っ先に挙げるものだ。

そこでこのレーンだけは、モデル自身の作品知識を根拠にすることを許す。
代わりに三つの縛りを置く:

  1. 「広く共有された認識か」を自己申告させる（有名な特徴だけを採る）
  2. 根拠をファンの言い回しで書かせる（説明できないものは書けない）
  3. src を knowledge にして、他レーンの判定と混ぜない（後から一括で外せる）

  export GEMINI_API_KEY=...
  python3 tools/ingest/trait.py --character 市丸ギン --work BLEACH --out work/trait.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

_ENV = os.environ.get("GEMINI_TRAIT_MODEL")
MODEL_CANDIDATES = [_ENV] if _ENV else ["gemini-3.6-pro", "gemini-3.6-flash", "gemini-2.5-pro"]
DEFAULT_MODEL = MODEL_CANDIDATES[0]

SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "weight": {"type": "string", "enum": ["core", "sub", "spice"]},
                    "recognition": {"type": "string", "enum": ["famous", "known", "minor"]},
                    "evidence": {"type": "string"},
                },
                "required": ["id", "weight", "recognition", "evidence"],
            },
        },
        "new_tags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "axis": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["name", "axis", "reason"],
            },
        },
    },
    "required": ["elements"],
}

PROMPT = """あなたは日本のオタク文化に詳しい編集者です。
{character}（{work}）を、下の語彙で「識別」してください。

## 何を書くか

説明ではなく識別です。そのキャラを知っている人が、名前を伏せて特徴を挙げるときに
真っ先に言うものだけを書いてください。

  例: {example}

## 縛り

- **他の誰とでも共有される特徴は書かない。** 髪色・髪型・体格のような、
  その作品の外でも大量に該当する語は、よほどその人の代名詞になっていない限り外す。
- recognition は、その特徴がどれだけ広く共有された認識かで決める:
  - famous … そのキャラの代名詞。ファンなら誰でも挙げる
  - known  … 知っていれば挙がる。作品を追った人には自明
  - minor  … 一部の場面でしか出ない
- weight はその人物の中での比重:
  - core  … これが無ければ別人になる
  - sub   … 確実にその人のものだが、核ではない
  - spice … 効いてはいるが一点だけ
- **evidence には根拠をファンの言い回しで一行書く。** 何が根拠か書けないものは
  書かないでください。「〜だと思われる」のような推測は書かない。
- 3〜8 個。多く挙げるより、外さないほうが大事です。
- 語彙に無い概念は new_tags に回す。作品固有の設定名は入れない
  （「死神代行」「呪術師」のような、その作品でしか通じない語は不可）。

## 語彙

{vocabulary}
"""

# 静止画レーンが確実に当てる見た目は、こちらでは判定しない。髪型は延べ 400 件、
# 服装は 113 件当たっていて、モデルの記憶を足しても雑音が増えるだけだから。
#
# 顔だけは外す。10 語で延べ 20 件しか当たっておらず（髪型の 1/20）、Danbooru が
# 作り笑い・無表情・八重歯をほとんど付けないため。ファンがその人を思い出すときには
# 真っ先に挙がる種類の特徴なので、当たらない軸をタグレーンに任せ続ける理由がない。
# 目の形と痕は 11 巡目で VISUAL_AXES から外したので、ここでも自動的に対象になる。
EXCLUDED_AXES = common.VISUAL_AXES - {"appearance.face"}

# 手本。対象そのものを手本に出すと答えを写すだけになるので、その場合は別の例に替える。
EXAMPLES = [
    ("市丸ギン", "市丸ギン なら「糸目」「関西弁」。「短髪」「白髪」ではありません。\n"
                 "      短髪は 100 人以上が該当するので、誰のことも指しません。"),
    ("野比のび太", "野比のび太 なら「メガネ」「ダメ人間」。「黒髪」「小学生」ではありません。\n"
                   "      黒髪は該当者が多すぎて、誰のことも指しません。"),
]


def example_for(character: str) -> str:
    for name, text in EXAMPLES:
        if name != character:
            return text
    return EXAMPLES[0][1]


def validate(result: dict, db: dict) -> dict:
    """語彙に無い id、担当外の軸、根拠なしを落とす。"""
    by_id = {e["id"]: e for e in db["elements"]}
    kept, dropped, out_of_scope, weak = [], [], [], []
    for item in result.get("elements", []):
        element = by_id.get(item.get("id"))
        if element is None:
            dropped.append(str(item.get("id")))
            continue
        if element["axis"] in EXCLUDED_AXES:
            out_of_scope.append(item["id"])
            continue
        if not (item.get("evidence") or "").strip():
            weak.append(item["id"])
            continue
        if item.get("recognition") == "minor":
            # 一部の場面でしか出ないものは識別子ではない
            weak.append(item["id"])
            continue
        item["evidence"] = f"通説: {item['evidence']}".strip()
        item["confidence"] = "high" if item.get("recognition") == "famous" else "mid"
        kept.append(item)
    result["elements"] = kept
    result["_dropped"] = dropped
    result["_out_of_scope"] = out_of_scope
    result["_weak"] = weak
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--work", default="")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-only", action="store_true")
    parser.add_argument("--from-json", type=Path)
    parser.add_argument("--out", default="work/trait.json")
    args = parser.parse_args()

    db = common.load_db()

    if args.from_json:
        result = json.loads(args.from_json.read_text(encoding="utf-8"))
        model = f"{args.model}（手動実行）"
    else:
        prompt = PROMPT.format(
            character=args.character,
            work=args.work or "作品不明",
            example=example_for(args.character),
            vocabulary=common.vocabulary_block(db, exclude_axes=EXCLUDED_AXES),
        )
        if args.prompt_only:
            print(prompt)
            return 0
        candidates = [args.model] if args.model != DEFAULT_MODEL else MODEL_CANDIDATES
        model, result = common.call_gemini_fallback(
            candidates, [{"text": prompt}], SCHEMA, common.gemini_api_key(), temperature=0.1
        )

    result = validate(result, db)
    result["_meta"] = {"character": args.character, "work": args.work, "model": model}

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"識別 {len(result['elements'])} 要素 → {out}")
    for key, label in (
        ("_dropped", "語彙にない id を破棄"),
        ("_out_of_scope", "静止画レーンの担当なので破棄"),
        ("_weak", "根拠が無いか minor なので破棄"),
    ):
        if result[key]:
            print(f"  {label}: {', '.join(result[key])}")
    for tag in result.get("new_tags", []):
        print(f"  新語の提案: {tag['name']}（{tag.get('axis', '?')}）… {tag.get('reason', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
