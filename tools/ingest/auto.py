#!/usr/bin/env python3
"""data/queue.yaml を読み、公開リソースからの取得〜分類〜統合を無人で実行する。

GitHub Actions（.github/workflows/ingest.yml）から定期的に呼ばれる想定。
結果は data/characters_auto.yaml へ upsert される（手書きの characters.yaml には触れない）。

  python3 tools/ingest/auto.py                 # 新規＋期限切れを最大 --limit 件処理
  python3 tools/ingest/auto.py --dry-run       # 何が処理対象かだけ表示
  python3 tools/ingest/auto.py --only <id>     # 特定のキャラだけ強制実行

GEMINI_API_KEY が無い場合は資料の抽出と分類を飛ばし、Danbooru 合意による外見だけを更新する。
処理は 1 件ずつ独立しており、途中で失敗しても他の件は続行する。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ROOT = common.ROOT
QUEUE = ROOT / "data" / "queue.yaml"
AUTO_CHARACTERS = ROOT / "data" / "characters_auto.yaml"
INGEST = Path(__file__).resolve().parent


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, cwd=ROOT, **kwargs)


def load_auto_dates() -> dict[str, str]:
    if not AUTO_CHARACTERS.exists():
        return {}
    entries = yaml.safe_load(AUTO_CHARACTERS.read_text(encoding="utf-8")) or []
    return {e["id"]: (e.get("analysis") or {}).get("date", "") for e in entries}


def select_targets(queue: list[dict], auto_dates: dict[str, str], max_age_days: int, only: str | None) -> list[dict]:
    today = time.strftime("%Y-%m-%d")
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - max_age_days * 86400))
    targets = []
    for entry in queue:
        cid = entry.get("id") or common.slugify(entry.get("name", ""))
        entry["id"] = cid
        if only:
            if cid == only:
                targets.append(entry)
            continue
        last = auto_dates.get(cid)
        if last is None:
            entry["_reason"] = "新規"
            targets.append(entry)
        elif not last or last < cutoff:
            entry["_reason"] = f"期限切れ（前回 {last or '不明'}）"
            targets.append(entry)
    return targets


def process(entry: dict, api_key: str | None, sleep: float) -> None:
    cid = entry["id"]
    workdir = ROOT / "work" / "auto" / cid
    workdir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    danbooru_file = None
    if entry.get("danbooru"):
        danbooru_file = workdir / "danbooru.json"
        run([python, INGEST / "fetch.py", "--sleep", sleep, "danbooru", entry["danbooru"], "--out", danbooru_file])
        time.sleep(sleep)

    pages: list[Path] = []
    if entry.get("anilist"):
        path = workdir / "anilist.json"
        run([python, INGEST / "fetch.py", "--sleep", sleep, "anilist", entry["anilist"], "--out", path])
        pages.append(path)
        time.sleep(sleep)
    for index, url in enumerate(entry.get("pages") or []):
        path = workdir / f"page_{index}.txt"
        run([python, INGEST / "fetch.py", "--sleep", sleep, "page", url, "--out", path])
        pages.append(path)
        time.sleep(sleep)

    classify_file = None
    if api_key and pages:
        facts_file = workdir / "facts.yaml"
        run([python, INGEST / "facts.py", "--character", entry["name"], "--pages", *pages, "--out", facts_file])
        classify_file = workdir / "classify.json"
        run(
            [python, INGEST / "classify.py", "--character", entry["name"], "--facts", facts_file, "--out", classify_file]
        )
    elif pages and not api_key:
        print("  GEMINI_API_KEY が無いため資料の抽出と分類を飛ばします（外見のみ更新）")

    if not danbooru_file and not classify_file:
        raise RuntimeError("この件で使える証拠がありません（danbooru も分類結果も無い）")

    merge_cmd = [
        python, INGEST / "merge.py",
        "--name", entry["name"],
        "--kana", entry.get("kana", entry["name"]),
        "--work", entry.get("work", ""),
        "--id", cid,
        "--date", time.strftime("%Y-%m-%d"),
        "--write-auto",
    ]
    if entry.get("year"):
        merge_cmd += ["--year", str(entry["year"])]
    if entry.get("author"):
        merge_cmd += ["--author", entry["author"]]
    if danbooru_file:
        merge_cmd += ["--danbooru", danbooru_file]
    if classify_file:
        merge_cmd += ["--vision", classify_file]
    run(merge_cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="1 回の実行で処理する最大件数")
    parser.add_argument("--max-age-days", type=int, default=30, help="この日数より古いエントリを再取得する")
    parser.add_argument("--only", help="このキャラ id だけ強制実行する")
    parser.add_argument("--sleep", type=float, default=2.0, help="リクエスト間隔（秒）")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not QUEUE.exists():
        print("data/queue.yaml がありません。処理対象なし。")
        return 0
    queue = (yaml.safe_load(QUEUE.read_text(encoding="utf-8")) or {}).get("characters") or []
    if not queue:
        print("キューが空です。data/queue.yaml にキャラクターを足してください。")
        return 0

    targets = select_targets(queue, load_auto_dates(), args.max_age_days, args.only)
    if not targets:
        print("処理対象がありません（全件が期限内）。")
        return 0
    targets = targets[: args.limit]

    print(f"処理対象 {len(targets)} 件:")
    for entry in targets:
        print(f"  - {entry['id']}: {entry.get('name')}（{entry.get('_reason', '指定')}）")
    if args.dry_run:
        return 0

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    failed = []
    for entry in targets:
        print(f"\n=== {entry['id']} ===")
        try:
            process(entry, api_key, args.sleep)
        except (subprocess.CalledProcessError, RuntimeError, SystemExit) as err:
            print(f"  失敗: {err}")
            failed.append(entry["id"])

    print(f"\n完了 {len(targets) - len(failed)} / {len(targets)} 件" + (f"（失敗: {', '.join(failed)}）" if failed else ""))
    if len(failed) == len(targets):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
