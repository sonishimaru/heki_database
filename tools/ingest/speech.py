#!/usr/bin/env python3
"""台詞レーン: キャラクターの台詞から話し方の統計を取る。決定的な集計で、モデルは使わない。

一人称・語尾・敬語率のような「話し方」は、映像を眺めるより台詞の集計が最も確実に出る。
入力は 1 行 1 台詞のテキスト（字幕・スクリプト・書き起こしから、その人物の行だけを抜いたもの）。
.ass 字幕なら Style/Actor で、ゲームスクリプトなら話者名で抜ける。抜き方は素材に依存するので
このスクリプトは集計だけを担当する。

  python3 tools/ingest/speech.py lines.txt --out work/speech.json

出力は classify.py に --speech で渡す。
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

FIRST_PERSON = [
    "私", "わたし", "わたくし", "僕", "ぼく", "俺", "おれ", "オレ",
    "あたし", "うち", "ウチ", "自分", "吾輩", "我輩", "わし", "拙者", "妾", "小生",
]

POLITE_RE = re.compile(r"(です|ます|ました|ません|でしょう|でした|ございます|なさい|ください|おります)[ねよわのぞかなさ]{0,2}[。！？!?…♪〜ー]*$")
PUNCT_RE = re.compile(r"[。、！？!?…♪〜ー\s「」『』（）()]+$")

# ありふれた語尾。これに該当しない語尾が高頻度で出たとき「特徴的な語尾」の候補になる。
COMMON_ENDINGS = {
    "です", "ます", "した", "ない", "だよ", "だね", "よね", "うん", "のか", "から",
    "けど", "って", "だろ", "でしょ", "かな", "よな", "だが", "のだ", "んだ", "たい",
    "いい", "する", "だな", "ろう", "せん",
}


def analyze(lines: list[str]) -> dict:
    total = len(lines)
    first_person = Counter()
    endings = Counter()
    polite = 0
    exclaim = 0
    question = 0
    lengths = []

    for line in lines:
        lengths.append(len(line))
        if "！" in line or "!" in line:
            exclaim += 1
        if "？" in line or "?" in line:
            question += 1
        if POLITE_RE.search(line):
            polite += 1
        for pronoun in FIRST_PERSON:
            if pronoun in line:
                first_person[pronoun] += 1
        stripped = PUNCT_RE.sub("", line)
        if len(stripped) >= 2:
            endings[stripped[-2:]] += 1

    stats = {
        "lines": total,
        "polite_ratio": round(polite / total, 3),
        "exclaim_ratio": round(exclaim / total, 3),
        "question_ratio": round(question / total, 3),
        "avg_length": round(sum(lengths) / total, 1),
        "first_person": dict(first_person.most_common()),
        "top_endings": dict(endings.most_common(12)),
    }

    suggestions = []
    if stats["polite_ratio"] >= 0.6:
        suggestions.append(
            {
                "id": "keigo",
                "confidence": "high" if stats["polite_ratio"] >= 0.8 else "mid",
                "evidence": f"台詞の {stats['polite_ratio']:.0%} が敬語で終わる（{total}行中）",
            }
        )
    for ending, count in endings.most_common(5):
        ratio = count / total
        if ending not in COMMON_ENDINGS and ratio >= 0.15 and count >= 5:
            suggestions.append(
                {
                    "id": "gobi",
                    "confidence": "high" if ratio >= 0.3 else "mid",
                    "evidence": f"語尾「{ending}」が {ratio:.0%} の行に出現（{count}/{total}行）",
                }
            )
            break

    notes = []
    if first_person:
        top = first_person.most_common(1)[0]
        notes.append(f"一人称は「{top[0]}」が主（{top[1]}回）。ichininshou を立てるかは見た目・立場とのずれで判断する。")
    if len(first_person) >= 2:
        notes.append("一人称が複数観測されている。場面による切り替え（nimensei / neko-o-kaburu）の兆候の可能性。")

    return {"stats": stats, "suggestions": suggestions, "notes": notes}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("lines_file", type=Path, help="1 行 1 台詞のテキスト（# で始まる行は無視）")
    parser.add_argument("--out", default="work/speech.json")
    args = parser.parse_args()

    lines = [
        line.strip()
        for line in args.lines_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if len(lines) < 10:
        raise SystemExit(f"台詞が {len(lines)} 行しかありません。統計には最低でも数十行ほしいところです。")

    result = analyze(lines)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    stats = result["stats"]
    print(f"{stats['lines']} 行 → {out}")
    print(f"  敬語率 {stats['polite_ratio']:.0%} / 一人称 {list(stats['first_person'])[:3]} / 語尾上位 {list(stats['top_endings'])[:5]}")
    for s in result["suggestions"]:
        print(f"  候補: {s['id']} … {s['evidence']}")
    for n in result["notes"]:
        print(f"  メモ: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
