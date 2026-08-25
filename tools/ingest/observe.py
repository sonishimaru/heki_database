#!/usr/bin/env python3
"""Gemini Vision でシーンを「観察」する。分類はしない。

シーンごとに 1 コールで、空間・時間・登場人物・演技を見たまま記述させる。
語彙の id はここでは一切出させない。数カットから性格や関係を id 判定させると
作品知識で補完した「それらしい嘘」が混ざるため、観察と分類を分離している。
分類は、全シーンの観察が溜まってから classify.py が横断して行う。

  export GEMINI_API_KEY=...
  python3 tools/ingest/observe.py --cuts work/frames/cuts.json \
      --cast "主人公=アーニャ, 父=ロイド" --out work/observations.json

  # シーンを絞る（例: 1〜10 と 15）
  python3 tools/ingest/observe.py --cuts work/frames/cuts.json --scenes 1-10,15 ...

観察は安い作業なので既定モデルは flash。判断力が要る classify 側が pro を使う。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

_ENV = os.environ.get("GEMINI_OBSERVE_MODEL")
MODEL_CANDIDATES = [_ENV] if _ENV else ["gemini-3.6-flash", "gemini-2.5-flash"]
DEFAULT_MODEL = MODEL_CANDIDATES[0]

SCHEMA = {
    "type": "object",
    "properties": {
        "location": {"type": "string"},
        "time_of_day": {"type": "string"},
        "continuity": {"type": "string"},
        "characters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "doing": {"type": "string"},
                    "expression": {"type": "string"},
                    "gaze": {"type": "string"},
                    "hands_posture": {"type": "string"},
                },
                "required": ["name", "doing"],
            },
        },
        "interaction": {"type": "string"},
        "acting_delta": {"type": "string"},
        "notable": {"type": "array", "items": {"type": "string"}},
        "tagger_frames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "frame": {"type": "string"},
                    "character": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["frame", "reason"],
            },
        },
    },
    "required": ["location", "time_of_day", "characters", "interaction", "acting_delta", "tagger_frames"],
}

PROMPT = """あなたは映像の観察記録係です。渡されるのは一つのシーンから抜いた連続する静止画です。

## やること（観察のみ。解釈や性格の判定はしない）

- location / time_of_day: どこで、いつ（昼夜・季節が分かる範囲で）。
- continuity: 前のシーンからの繋がりが画面から読めれば書く（同時刻か、時間経過か）。
- characters: 映っている人物ごとに、何をしているか・表情・視線の先・手と姿勢。
  名前が分からない人物は「男A」「少女B」のように一貫した仮名で呼ぶ。
- interaction: 人物同士の距離と向き。誰が誰に近づき、誰が目を逸らしたか。
- acting_delta: このシーン内でフレーム間に起きた変化。静止画一枚ではなく差分として書く。
- notable: 目を引いた細部（持ち物、癖、画面が強調しているもの）。
- tagger_frames: 人物が大きく写り、髪型・服装・小物が明瞭なフレームを人物ごとに選ぶ。

## 守ること

- 見えたものだけを書く。作品を知っていても、画面にない情報を混ぜない。
- 「〜という性格に見える」のような人格の判定はしない。行動と表情の記述に留める。
- 各フレームのファイル名は画像の直後に添えてある。それで参照する。
{cast_block}"""

CAST_BLOCK = """
## 人物名の対応（利用者指定）

{cast}
分かる場合はこの名前を使う。指定にない人物は仮名で呼ぶ。
"""


def parse_scenes(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    picked: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            picked.update(range(int(lo), int(hi) + 1))
        elif part:
            picked.add(int(part))
    return sorted(n for n in picked if 1 <= n <= total)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cuts", type=Path, required=True, help="scenes.py が出した cuts.json")
    parser.add_argument("--scenes", help="対象シーン（例: 1-10,15）。省略で全部")
    parser.add_argument("--cast", default="", help="人物名の対応（例: '主人公=アーニャ, 父=ロイド'）")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", default="work/observations.json")
    parser.add_argument("--prompt-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="出力済みのシーンを飛ばして続きから")
    args = parser.parse_args()

    cast_block = CAST_BLOCK.format(cast=args.cast) if args.cast else ""
    prompt = PROMPT.format(cast_block=cast_block)
    if args.prompt_only:
        print(prompt)
        return 0

    index = json.loads(args.cuts.read_text(encoding="utf-8"))
    targets = parse_scenes(args.scenes, index["cuts"])
    api_key = common.gemini_api_key()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    observations: dict[str, dict] = {}
    if args.resume and out.exists():
        observations = {o["scene"]: o for o in json.loads(out.read_text(encoding="utf-8"))["scenes"]}

    for scene in index["scenes"]:
        number = scene["cut"]
        if number not in targets:
            continue
        key = str(number)
        if key in observations:
            continue
        images = [Path(p) for p in scene["images"] if Path(p).exists()]
        if not images:
            print(f"scene {number}: フレームが見つからないので飛ばします")
            continue

        parts: list[dict] = [{"text": prompt}, {"text": f"\n[シーン {number} / {scene['start']}–{scene['end']}]"}]
        for image in images:
            parts.append(common.image_part(image))
            parts.append({"text": f"（上の画像のファイル名: {image.name}）"})

        candidates = [args.model] if args.model != DEFAULT_MODEL else MODEL_CANDIDATES
        _, result = common.call_gemini_fallback(candidates, parts, SCHEMA, api_key)
        result["scene"] = key
        result["start"] = scene["start"]
        result["images"] = [str(p) for p in images]
        observations[key] = result
        who = "・".join(c["name"] for c in result.get("characters", [])) or "（人物なし）"
        print(f"scene {number}: {result.get('location', '?')} / {who}")

        out.write_text(
            json.dumps(
                {"video": index.get("video"), "model": args.model, "scenes": sorted(observations.values(), key=lambda o: int(o["scene"]))},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"{len(observations)} シーン → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
