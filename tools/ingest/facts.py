#!/usr/bin/env python3
"""取得済みの公開資料（fetch.py の出力）から、facts.yaml の下書きを作る。

pixiv百科事典・公式サイト・AniList のプロフィール文などを渡し、
「出典に書かれている事実」だけを facts の形式に写させる。解釈や推測は書かせない。
各項目に出典を付けさせるので、後から人が原文と突き合わせて確認できる。

**下書きである。** 確認せずに classify へ流さないこと。

  export GEMINI_API_KEY=...
  python3 tools/ingest/facts.py --character アーニャ \
      --pages work/sources/page_*.txt work/sources/anilist_*.json \
      --out work/facts.yaml

  # API を叩けない環境
  python3 tools/ingest/facts.py --character アーニャ --pages ... --prompt-only > prompt.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

MODEL_CANDIDATES = common.models_for(common.FLASH_MODELS, "GEMINI_FACTS_MODEL")
DEFAULT_MODEL = MODEL_CANDIDATES[0]

SCHEMA = {
    "type": "object",
    "properties": {
        "character": {"type": "string"},
        "work": {"type": "string"},
        "profile": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                "required": ["fact", "source"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                "required": ["fact", "source"],
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                "required": ["fact", "source"],
            },
        },
        "speech_style": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"fact": {"type": "string"}, "source": {"type": "string"}},
                "required": ["fact", "source"],
            },
        },
        "conflicts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["character", "work", "profile", "relations", "events"],
}

PROMPT = """あなたは資料整理係です。渡されるのは「{character}」について取得した公開資料のテキストです。
資料に**書かれている事実**だけを抜き出し、次の分類で整理してください。

- profile: 公式に明記されている設定（年齢・種族・立場・所属・肩書き）
- relations: 誰とどういう間柄か
- events: 作中で起きた出来事（時系列で。ネタバレ可）
- speech_style: 一人称・口調・語尾について資料が明記していること

## 守ること

- 資料にない情報を書かない。あなたの作品知識で補完しない。
- 解釈・分析・印象（「ツンデレである」「健気」など）は書かない。行動と設定の事実だけ。
- 各項目の source には、どの資料から取ったかを短く書く（資料の冒頭に # source: URL がある）。
- 複数の資料で矛盾する記述があれば、どちらも書かずに conflicts に記録する。
- ファンの俗説と公式設定が区別できない記述は、事実として採らずに conflicts へ。

## 資料

{pages}
"""


def load_page(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        text = json.dumps(json.loads(text), ensure_ascii=False, indent=1)
    limit = 15000
    if len(text) > limit:
        text = text[:limit] + "\n（以下略）"
    return f"### 資料: {path.name}\n\n{text}"


def to_yaml(result: dict) -> str:
    lines = [
        "# facts.yaml（facts.py による下書き。確認してから classify に渡すこと）",
        f"character: {common.yaml_quote(result['character'])}",
        f"work: {common.yaml_quote(result['work'])}",
    ]
    for key in ("profile", "relations", "events", "speech_style"):
        rows = result.get(key) or []
        lines.append(f"{key}:")
        if not rows:
            lines[-1] += " []"
            continue
        for row in rows:
            lines.append(f"  - {common.yaml_quote(row['fact'])}  # 出典: {row['source']}")
    conflicts = result.get("conflicts") or []
    lines.append("notes:")
    if conflicts:
        for item in conflicts:
            lines.append(f"  - {common.yaml_quote('要確認（資料間で矛盾）: ' + item)}")
    else:
        lines[-1] += " []"
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--pages", nargs="+", type=Path, required=True, help="fetch.py が保存した資料ファイル")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--prompt-only", action="store_true")
    parser.add_argument("--from-json", type=Path)
    parser.add_argument("--out", default="work/facts.yaml")
    args = parser.parse_args()

    if args.from_json:
        result = json.loads(args.from_json.read_text(encoding="utf-8"))
    else:
        prompt = PROMPT.format(
            character=args.character,
            pages="\n\n".join(load_page(p) for p in args.pages),
        )
        if args.prompt_only:
            print(prompt)
            return 0
        candidates = [args.model] if args.model != DEFAULT_MODEL else MODEL_CANDIDATES
        _, result = common.call_gemini_fallback(candidates, [{"text": prompt}], SCHEMA, common.gemini_api_key())

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_yaml(result), encoding="utf-8")
    counts = {k: len(result.get(k) or []) for k in ("profile", "relations", "events", "speech_style")}
    print(f"下書き → {out}（" + " / ".join(f"{k} {v}" for k, v in counts.items()) + "）")
    if result.get("conflicts"):
        print("  矛盾あり。notes を確認してください。")
    print("  内容を確認・修正してから classify.py --facts に渡すこと。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
