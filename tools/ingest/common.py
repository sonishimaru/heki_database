"""取り込みパイプライン共通処理。

  動画 → scenes.py（カット割り）→ tagger.py（WD-Tagger で外見タグ）
                              → vision.py（Gemini Vision で演技・時空間・非外見軸）
                              → merge.py（統合して characters.yaml の断片を出力）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "docs" / "data" / "db.json"
WD_MAP = Path(__file__).resolve().parent / "wd_map.yaml"

# 外見の軸。WD-Tagger が担当する範囲。
VISUAL_GROUPS = {"appearance"}

WEIGHT_ORDER = {"core": 0, "sub": 1, "spice": 2}


def load_db() -> dict:
    if not DB.exists():
        raise SystemExit("docs/data/db.json がありません。先に python3 tools/build.py を実行してください。")
    return json.loads(DB.read_text(encoding="utf-8"))


def vocabulary(db: dict, groups: set[str] | None = None) -> list[dict]:
    """見出し語の一覧。groups を指定するとその大分類だけに絞る。"""
    return [
        e
        for e in db["elements"]
        if groups is None or e["group"] in groups
    ]


def vocabulary_block(db: dict, groups: set[str] | None = None) -> str:
    """モデルに渡す語彙表。id と名前と一行定義だけを、軸ごとにまとめる。"""
    lines: list[str] = []
    current = None
    for e in sorted(vocabulary(db, groups), key=lambda x: (x["axis"], x["id"])):
        if e["axis"] != current:
            current = e["axis"]
            lines.append(f"\n[{e['group_name']} / {e['axis_name']}]")
        alias = f"（別名: {'・'.join(e['aliases'])}）" if e["aliases"] else ""
        lines.append(f"  {e['id']} = {e['name']}{alias} … {e['summary']}")
    return "\n".join(lines).strip()


def decide_weight(coverage: float, score: float) -> str:
    """カット全体での出現率と最大スコアから比重を決める。

    継続して映っている特徴ほどその人物の骨格に近い、という前提を置いている。
    """
    if coverage >= 0.6 and score >= 0.6:
        return "core"
    if coverage >= 0.25 or score >= 0.85:
        return "sub"
    return "spice"


def confidence_of(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "mid"
    return "low"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "character"


def yaml_quote(value: str) -> str:
    """YAML のフロー内に置ける形へ。記号を含む場合だけ引用する。"""
    text = str(value).replace("\n", " ").strip()
    if not text:
        return "''"
    if re.search(r"[:\{\}\[\],&\*#\?\|\-<>=!%@`'\"]", text):
        return "'" + text.replace("'", "''") + "'"
    return text


def emit_character_yaml(entry: dict) -> str:
    """characters.yaml にそのまま貼れる形へ整形する。"""
    out = [f"- id: {entry['id']}"]
    for key in ("name", "kana", "work"):
        out.append(f"  {key}: {yaml_quote(entry[key])}")
    if entry.get("year"):
        out.append(f"  year: {entry['year']}")
    if entry.get("author"):
        out.append(f"  author: {yaml_quote(entry['author'])}")
    out.append(f"  summary: {yaml_quote(entry['summary'])}")

    analysis = entry.get("analysis") or {}
    if analysis:
        out.append("  analysis:")
        for key in ("method", "model", "frames", "cuts", "date"):
            if analysis.get(key) not in (None, ""):
                out.append(f"    {key}: {yaml_quote(analysis[key])}")

    out.append("  elements:")
    for item in sorted(entry["elements"], key=lambda x: (WEIGHT_ORDER[x["weight"]], x["id"])):
        note = f", note: {yaml_quote(item['note'])}" if item.get("note") else ""
        out.append(f"    - {{id: {item['id']}, weight: {item['weight']}{note}}}")

    patterns = entry.get("patterns") or []
    out.append(f"  patterns: [{', '.join(patterns)}]")
    return "\n".join(out) + "\n"
