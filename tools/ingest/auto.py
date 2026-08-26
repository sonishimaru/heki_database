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


def load_auto_meta() -> dict[str, dict]:
    if not AUTO_CHARACTERS.exists():
        return {}
    entries = yaml.safe_load(AUTO_CHARACTERS.read_text(encoding="utf-8")) or []
    return {
        e["id"]: {**(e.get("analysis") or {}), "_has_image": bool((e.get("image") or {}).get("url"))}
        for e in entries
    }


def select_targets(
    queue: list[dict],
    auto_meta: dict[str, dict],
    max_age_days: int,
    only: str | None,
    backfill_gemini: bool,
    refresh_all: bool = False,
) -> list[dict]:
    cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - max_age_days * 86400))
    fresh, stale, lane_gap = [], [], []
    for entry in queue:
        cid = entry.get("id") or common.slugify(entry.get("name", ""))
        entry["id"] = cid
        if only:
            if cid == only:
                fresh.append(entry)
            continue
        meta = auto_meta.get(cid)
        if meta is None:
            entry["_reason"] = "新規"
            fresh.append(entry)
            continue
        if refresh_all:
            # 見出し語を足した後など、期限に関係なく全件へ新しい語彙を当て直す
            entry["_reason"] = "全件再取得"
            stale.append(entry)
            continue
        last = meta.get("date", "")
        if not last or last < cutoff:
            entry["_reason"] = f"期限切れ（前回 {last or '不明'}）"
            stale.append(entry)
            continue
        # クォータ切れ等で資料レーンだけ落ちた件は、期限を待たずに埋め直す。
        # （取得できない件を毎日引き当て続けないよう、条件はレーンの欠落だけにしている。
        #   見出し語を足した後の当て直しは --refresh-all を使う）
        wants_gemini = bool(entry.get("anilist") or entry.get("pages"))
        if backfill_gemini and wants_gemini and "gemini" not in (meta.get("method") or ""):
            entry["_reason"] = f"資料レーン未取得（前回 {last}）"
            lane_gap.append(entry)
    return fresh + stale + lane_gap


def process(entry: dict, api_key: str | None, sleep: float) -> None:
    cid = entry["id"]
    workdir = ROOT / "work" / "auto" / cid
    workdir.mkdir(parents=True, exist_ok=True)
    python = sys.executable

    def try_fetch(cmd: list, out_path: Path, label: str) -> bool:
        """ソース単位の取得。失敗しても他のソースで続行する。"""
        try:
            run(cmd)
            time.sleep(sleep)
            return out_path.exists()
        except subprocess.CalledProcessError:
            print(f"  取得失敗（続行）: {label}")
            return False

    danbooru_file = None
    if entry.get("danbooru"):
        path = workdir / "danbooru.json"
        if try_fetch([python, INGEST / "fetch.py", "--sleep", sleep, "danbooru", entry["danbooru"], "--out", path], path, f"danbooru {entry['danbooru']}"):
            danbooru_file = path

    pages: list[Path] = []
    anilist_file = None
    if entry.get("anilist"):
        path = workdir / "anilist.json"
        if try_fetch([python, INGEST / "fetch.py", "--sleep", sleep, "anilist", entry["anilist"], "--out", path], path, f"anilist {entry['anilist']}"):
            pages.append(path)
            anilist_file = path
    for index, url in enumerate(entry.get("pages") or []):
        path = workdir / f"page_{index}.txt"
        if try_fetch([python, INGEST / "fetch.py", "--sleep", sleep, "page", url, "--out", path], path, url):
            pages.append(path)

    classify_file = None
    if api_key and pages:
        try:
            facts_file = workdir / "facts.yaml"
            run([python, INGEST / "facts.py", "--character", entry["name"], "--pages", *pages, "--out", facts_file])
            classify_file = workdir / "classify.json"
            run([python, INGEST / "classify.py", "--character", entry["name"], "--facts", facts_file, "--out", classify_file])
        except subprocess.CalledProcessError:
            # クォータ切れ等。前回の分類結果はレーン引き継ぎで残るので、外見だけ更新して続行する
            print("  資料レーン失敗（続行）: 今回は外見のみ更新")
            classify_file = None
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
    if anilist_file:
        merge_cmd += ["--anilist", anilist_file]
    run(merge_cmd)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="1 回の実行で処理する最大件数")
    parser.add_argument("--max-age-days", type=int, default=30, help="この日数より古いエントリを再取得する")
    parser.add_argument("--only", help="このキャラ id だけ強制実行する")
    parser.add_argument("--refresh-all", action="store_true", help="期限に関係なく全件を取り直す（見出し語を足した後に使う）")
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

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    targets = select_targets(
        queue, load_auto_meta(), args.max_age_days, args.only,
        backfill_gemini=bool(api_key), refresh_all=args.refresh_all,
    )
    if not targets:
        print("処理対象がありません（全件が期限内）。")
        return 0
    targets = targets[: args.limit]

    print(f"処理対象 {len(targets)} 件:")
    for entry in targets:
        print(f"  - {entry['id']}: {entry.get('name')}（{entry.get('_reason', '指定')}）")
    if args.dry_run:
        return 0
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
