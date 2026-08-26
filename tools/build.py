#!/usr/bin/env python3
"""data/ の YAML を検証し、閲覧サイト用の docs/data/db.json を生成する。

  python3 tools/build.py           # 検証してビルド
  python3 tools/build.py --check   # 検証のみ（CI 用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data" / "db.json"

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
WEIGHTS = ("core", "sub", "spice")
ANALYSIS_KEYS = ("method", "model", "frames", "cuts", "date")
FORMULA_KEYS = ("subject", "delta", "trigger", "condition", "observer")


class Problems:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, where: str, msg: str) -> None:
        self.items.append(f"{where}: {msg}")

    def __bool__(self) -> bool:
        return bool(self.items)


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


CONFLICT_RE = re.compile(r"^(<{7}|={7}|>{7})(\s|$)", re.MULTILINE)


def check_data_files(problems: Problems) -> None:
    """data/ 配下の YAML が壊れていないか先に見る。

    マージのコンフリクトマーカーが残ったまま入ると、後段のツールが
    読めずに落ちる（実際に suggestions.yaml で取り込みが半分失敗した）。
    検証対象に入っていないファイルも含めて、ここで全部見る。
    """
    for path in sorted(DATA.rglob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        where = str(path.relative_to(ROOT))
        if CONFLICT_RE.search(text):
            problems.add(where, "マージのコンフリクトマーカーが残っています")
            continue
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as err:
            problems.add(where, f"YAML として読めません: {err.__class__.__name__}")


def require(problems: Problems, where: str, obj: dict, keys: tuple[str, ...]) -> None:
    for key in keys:
        value = obj.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            problems.add(where, f"必須項目 '{key}' がありません")


def load_axes(problems: Problems) -> tuple[list[dict], dict[str, dict]]:
    raw = load_yaml(DATA / "axes.yaml")
    groups = raw.get("groups") or []
    index: dict[str, dict] = {}
    for group in groups:
        where = f"axes.yaml/{group.get('id')}"
        require(problems, where, group, ("id", "name", "summary"))
        if not ID_RE.match(str(group.get("id", ""))):
            problems.add(where, "group id は小文字ケバブケースにしてください")
        for axis in group.get("axes") or []:
            axis_id = f"{group['id']}.{axis.get('id')}"
            require(problems, f"axes.yaml/{axis_id}", axis, ("id", "name", "summary"))
            if axis_id in index:
                problems.add("axes.yaml", f"軸 id の重複: {axis_id}")
            index[axis_id] = {
                "id": axis_id,
                "name": axis["name"],
                "summary": axis.get("summary", ""),
                "group": group["id"],
                "group_name": group["name"],
            }
    return groups, index


def load_elements(problems: Problems, axis_index: dict[str, dict]) -> dict[str, dict]:
    elements: dict[str, dict] = {}
    for path in sorted((DATA / "elements").glob("*.yaml")):
        entries = load_yaml(path) or []
        if not isinstance(entries, list):
            problems.add(path.name, "トップレベルはリストである必要があります")
            continue
        for entry in entries:
            eid = entry.get("id")
            where = f"{path.name}/{eid}"
            require(problems, where, entry, ("id", "name", "kana", "axis", "summary", "effect"))
            if eid and not ID_RE.match(str(eid)):
                problems.add(where, "id は小文字ケバブケースにしてください")
            if eid in elements:
                problems.add(where, f"element id の重複: {eid}")
            axis = entry.get("axis")
            if axis and axis not in axis_index:
                problems.add(where, f"未知の軸: {axis}")
            entry.setdefault("aliases", [])
            entry.setdefault("tags", [])
            entry.setdefault("pairs_with", [])
            entry.setdefault("contrasts_with", [])
            entry.setdefault("description", "")
            entry["_source"] = path.name
            if eid:
                elements[eid] = entry
    return elements


def load_patterns(problems: Problems, elements: dict, axis_index: dict) -> dict[str, dict]:
    patterns: dict[str, dict] = {}
    entries = load_yaml(DATA / "patterns.yaml") or []
    for entry in entries:
        pid = entry.get("id")
        where = f"patterns.yaml/{pid}"
        require(problems, where, entry, ("id", "name", "kana", "summary", "core_axis", "breaks_when"))
        if pid and not ID_RE.match(str(pid)):
            problems.add(where, "id は小文字ケバブケースにしてください")
        if pid in patterns:
            problems.add(where, f"pattern id の重複: {pid}")
        if entry.get("core_axis") and entry["core_axis"] not in axis_index:
            problems.add(where, f"未知の core_axis: {entry['core_axis']}")
        formula = entry.get("formula") or {}
        for key in FORMULA_KEYS:
            if not formula.get(key):
                problems.add(where, f"formula.{key} がありません")
        for key in ("requires", "intensifiers"):
            entry.setdefault(key, [])
            for ref in entry[key]:
                if ref not in elements:
                    problems.add(where, f"{key} の未知の要素: {ref}")
        entry.setdefault("aliases", [])
        entry.setdefault("tags", [])
        entry.setdefault("related", [])
        if pid:
            patterns[pid] = entry
    for pid, entry in patterns.items():
        for ref in entry["related"]:
            if ref not in patterns:
                problems.add(f"patterns.yaml/{pid}", f"related の未知のパターン: {ref}")
    return patterns


def load_characters(problems: Problems, elements: dict, patterns: dict) -> dict[str, dict]:
    characters: dict[str, dict] = {}
    files = [DATA / "characters.yaml"]
    if (DATA / "characters_auto.yaml").exists():
        files.append(DATA / "characters_auto.yaml")
    for path in files:
        is_auto = path.name == "characters_auto.yaml"
        for entry in load_yaml(path) or []:
            cid = entry.get("id")
            if is_auto and cid in characters:
                continue  # 手書き（レビュー済み）が優先
            entry["_auto"] = is_auto
            where = f"{path.name}/{cid}"
            require(problems, where, entry, ("id", "name", "kana", "work", "summary"))
            if cid and not ID_RE.match(str(cid)):
                problems.add(where, "id は小文字ケバブケースにしてください")
            if cid in characters:
                problems.add(where, f"character id の重複: {cid}")
            seen = set()
            for item in entry.get("elements") or []:
                ref = item.get("id")
                if ref not in elements:
                    problems.add(where, f"未知の要素: {ref}")
                    continue
                if ref in seen:
                    problems.add(where, f"要素の重複: {ref}")
                seen.add(ref)
                weight = item.get("weight", "sub")
                if weight not in WEIGHTS:
                    problems.add(where, f"weight は {WEIGHTS} のいずれか: {weight}")
            if not seen:
                problems.add(where, "要素が 1 つも登録されていません")
            analysis = entry.get("analysis")
            if analysis is not None:
                if not isinstance(analysis, dict):
                    problems.add(where, "analysis はマッピングで指定してください")
                else:
                    for key in analysis:
                        if key not in ANALYSIS_KEYS:
                            problems.add(where, f"analysis の未知の項目: {key}")
            entry.setdefault("patterns", [])
            for ref in entry["patterns"]:
                if ref not in patterns:
                    problems.add(where, f"未知のパターン: {ref}")
            if cid:
                characters[cid] = entry
    return characters


def check_cross_refs(problems: Problems, elements: dict) -> None:
    for eid, entry in elements.items():
        where = f"{entry['_source']}/{eid}"
        for key in ("pairs_with", "contrasts_with"):
            for ref in entry[key]:
                if ref == eid:
                    problems.add(where, f"{key} に自分自身が含まれています")
                elif ref not in elements:
                    problems.add(where, f"{key} の未知の要素: {ref}")


def build(elements: dict, patterns: dict, characters: dict, groups: list, axis_index: dict) -> dict:
    used_by_characters = defaultdict(list)
    for cid, char in characters.items():
        for item in char.get("elements") or []:
            used_by_characters[item["id"]].append({"id": cid, "weight": item.get("weight", "sub")})

    used_by_patterns = defaultdict(list)
    for pid, pat in patterns.items():
        for ref in pat["requires"]:
            used_by_patterns[ref].append({"id": pid, "role": "requires"})
        for ref in pat["intensifiers"]:
            used_by_patterns[ref].append({"id": pid, "role": "intensifiers"})

    pattern_characters = defaultdict(list)
    for cid, char in characters.items():
        for pid in char["patterns"]:
            pattern_characters[pid].append(cid)

    out_elements = []
    for eid, entry in sorted(elements.items()):
        axis = axis_index[entry["axis"]]
        out_elements.append(
            {
                "id": eid,
                "name": entry["name"],
                "kana": entry["kana"],
                "aliases": entry["aliases"],
                "axis": entry["axis"],
                "axis_name": axis["name"],
                "group": axis["group"],
                "group_name": axis["group_name"],
                "summary": entry["summary"],
                "description": (entry.get("description") or "").strip(),
                "effect": entry["effect"],
                "pairs_with": entry["pairs_with"],
                "contrasts_with": entry["contrasts_with"],
                "tags": entry["tags"],
                "characters": used_by_characters.get(eid, []),
                "patterns": used_by_patterns.get(eid, []),
            }
        )

    out_patterns = []
    for pid, entry in sorted(patterns.items()):
        axis = axis_index[entry["core_axis"]]
        out_patterns.append(
            {
                "id": pid,
                "name": entry["name"],
                "kana": entry["kana"],
                "aliases": entry["aliases"],
                "core_axis": entry["core_axis"],
                "core_axis_name": axis["name"],
                "group": axis["group"],
                "group_name": axis["group_name"],
                "summary": entry["summary"],
                "formula": {key: entry["formula"][key] for key in FORMULA_KEYS},
                "requires": entry["requires"],
                "intensifiers": entry["intensifiers"],
                "breaks_when": entry["breaks_when"],
                "related": entry["related"],
                "tags": entry["tags"],
                "characters": pattern_characters.get(pid, []),
            }
        )

    out_characters = []
    for cid, entry in sorted(characters.items()):
        items = entry.get("elements") or []
        composition = Counter()
        for item in items:
            composition[elements[item["id"]]["axis"].split(".")[0]] += 1
        total = sum(composition.values()) or 1
        out_characters.append(
            {
                "id": cid,
                "name": entry["name"],
                "kana": entry["kana"],
                "work": entry["work"],
                "year": entry.get("year"),
                "author": entry.get("author", ""),
                "summary": entry["summary"],
                "image": entry.get("image") or {},
                "analysis": entry.get("analysis") or {},
                "curated": not entry.get("_auto", False),
                "elements": [
                    {
                        "id": item["id"],
                        "weight": item.get("weight", "sub"),
                        "note": item.get("note", ""),
                        "src": item.get("src", ""),
                    }
                    for item in items
                ],
                "patterns": entry["patterns"],
                "composition": [
                    {"group": gid, "count": count, "ratio": round(count / total, 4)}
                    for gid, count in sorted(composition.items(), key=lambda kv: -kv[1])
                ],
            }
        )

    axis_counts = Counter(entry["axis"] for entry in elements.values())
    out_groups = []
    for group in groups:
        out_groups.append(
            {
                "id": group["id"],
                "name": group["name"],
                "summary": group.get("summary", ""),
                "axes": [
                    {
                        "id": f"{group['id']}.{axis['id']}",
                        "name": axis["name"],
                        "summary": axis.get("summary", ""),
                        "count": axis_counts.get(f"{group['id']}.{axis['id']}", 0),
                    }
                    for axis in group.get("axes") or []
                ],
            }
        )

    all_tags = Counter()
    for entry in elements.values():
        all_tags.update(entry["tags"])
    for entry in patterns.values():
        all_tags.update(entry["tags"])

    queue = []
    queue_path = DATA / "queue.yaml"
    if queue_path.exists():
        for q in (load_yaml(queue_path) or {}).get("characters") or []:
            queue.append(
                {
                    "id": q.get("id") or "",
                    "name": q.get("name", ""),
                    "work": q.get("work", ""),
                    "lanes": [k for k in ("danbooru", "anilist", "pages") if q.get(k)],
                }
            )

    return {
        "groups": out_groups,
        "queue": queue,
        "elements": out_elements,
        "patterns": out_patterns,
        "characters": out_characters,
        "tags": [{"name": name, "count": count} for name, count in all_tags.most_common()],
        "stats": {
            "characters": len(out_characters),
            "elements": len(out_elements),
            "patterns": len(out_patterns),
            "axes": len(axis_index),
        },
    }


README = ROOT / "README.md"
COUNT_RE = re.compile(r"^現在の収録数: \*\*.*\*\*$", re.MULTILINE)


def update_readme_counts(stats: dict) -> None:
    """README の収録数を実データに合わせる。手で直すと必ず古くなるため。"""
    if not README.exists():
        return
    text = README.read_text(encoding="utf-8")
    line = (
        f"現在の収録数: **{stats['characters']} 名 / {stats['elements']} 要素 / "
        f"{stats['patterns']} 性癖 / {stats['axes']} 軸**"
    )
    updated = COUNT_RE.sub(lambda _: line, text, count=1)
    if updated != text:
        README.write_text(updated, encoding="utf-8")
        print(f"README の収録数を更新: {line}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="検証のみ行い書き出さない")
    args = parser.parse_args()

    problems = Problems()
    check_data_files(problems)
    groups, axis_index = load_axes(problems)
    elements = load_elements(problems, axis_index)
    check_cross_refs(problems, elements)
    patterns = load_patterns(problems, elements, axis_index)
    characters = load_characters(problems, elements, patterns)

    if problems:
        print(f"検証エラー {len(problems.items)} 件:", file=sys.stderr)
        for item in problems.items:
            print(f"  - {item}", file=sys.stderr)
        return 1

    db = build(elements, patterns, characters, groups, axis_index)
    stats = db["stats"]
    print(
        "検証 OK: "
        f"{stats['characters']}名 / {stats['elements']}要素 / "
        f"{stats['patterns']}性癖 / {stats['axes']}軸"
    )

    if args.check:
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(db, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"書き出し: {OUT.relative_to(ROOT)} ({OUT.stat().st_size:,} bytes)")
    update_readme_counts(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
