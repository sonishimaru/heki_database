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
import datetime
import json
import os
import re
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


# 「common.GeminiHTTPError: 残高が…」のような、traceback の締めくくりの行
EXCEPTION_LINE = re.compile(r"^(?:\w+\.)*\w*(?:Error|Exception|Exit|Warning)\s*:\s*(.+)$")


def stderr_of(err: subprocess.CalledProcessError) -> str:
    raw = err.stderr or ""
    return raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw


def reason_of(err: subprocess.CalledProcessError) -> str:
    """子プロセスの stderr から、人が読む一行を取り出す。

    レーンが落ちたとき「各件のログを見てください」とだけ出していたが、
    肝心の理由は 40 行の traceback に埋もれていて、実際には誰も辿れなかった。
    要約に載せられる長さまで削って返す。
    """
    text = stderr_of(err)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "理由不明"
    if "Traceback (most recent call last):" not in text:
        # SystemExit の文言はそのまま出るので、一行目が理由そのもの
        return lines[0][:160]
    # traceback なら末尾の例外行。ここは要約であって、全文は note_lane_failure が出す
    for line in reversed(lines):
        matched = EXCEPTION_LINE.match(line)
        if matched:
            return matched.group(1)[:160]
    return lines[-1][:160]


def note_lane_failure(lane: str, err: subprocess.CalledProcessError, tally: dict) -> str:
    """落ちた理由を一行で出し、最初の一件だけ要約用に控える。"""
    why = reason_of(err)
    tally.setdefault(f"{lane}_理由", why)
    if "Traceback" in stderr_of(err):
        # 想定外の落ち方。一行では足りないので末尾も出す
        for line in stderr_of(err).splitlines()[-8:]:
            if line.strip():
                print(f"    | {line.rstrip()[:200]}")
    return why


RUN_SUMMARY = ROOT / "data" / "last_run.yaml"


def write_run_summary(targets: list[dict], failed: list[str], tally: dict) -> None:
    """この回の結果を1ファイルに残す。

    どの件が落ちたかは要約の一行にしか出ず、Actions のログは 450 行あって
    その一行を探すだけで毎回 API を叩くことになっていた。リポジトリに
    置いておけば、日次の確認は git pull だけで済む。
    """
    summary = {
        "date": datetime.date.today().isoformat(),
        "対象": len(targets),
        "完了": len(targets) - len(failed),
        "失敗": failed,
        "レーン": {
            lane: f"{tally[lane]} / {tally[f'{lane}_試行']}"
            for lane in ("資料", "識別") if tally[f"{lane}_試行"]
        },
        "レーンの理由": {
            lane: tally[f"{lane}_理由"]
            for lane in ("資料", "識別") if tally.get(f"{lane}_理由")
        },
    }
    header = ("# 直近の取り込みの結果（auto.py が毎回書き直す）。\n"
              "# 日次の確認でここを読めば、どの件が落ちたか Actions のログを\n"
              "# 掘らずに分かる。tools/report.py run で整形して表示できる。\n\n")
    RUN_SUMMARY.write_text(
        header + yaml.safe_dump(summary, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


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


def process(entry: dict, api_key: str | None, sleep: float, tally: dict) -> None:
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
        tally["資料_試行"] += 1
        try:
            facts_file = workdir / "facts.yaml"
            run([python, INGEST / "facts.py", "--character", entry["name"], "--pages", *pages, "--out", facts_file], stderr=subprocess.PIPE, text=True)
            classify_file = workdir / "classify.json"
            run([python, INGEST / "classify.py", "--character", entry["name"], "--facts", facts_file, "--out", classify_file], stderr=subprocess.PIPE, text=True)
            tally["資料"] += 1
        except subprocess.CalledProcessError as err:
            # クォータ切れ等。前回の分類結果はレーン引き継ぎで残るので、外見だけ更新して続行する
            why = note_lane_failure("資料", err, tally)
            print(f"  資料レーン失敗（続行）: {why} / 今回は外見のみ更新")
            classify_file = None
    elif pages and not api_key:
        print("  GEMINI_API_KEY が無いため資料の抽出と分類を飛ばします（外見のみ更新）")

    # 識別レーン。資料も画像も要らない（モデルの作品知識だけで走る）ので、
    # 資料が取れなかったキャラでも効く。糸目・関西弁のような、
    # どの証拠レーンにも出てこない識別子はここからしか入らない。
    trait_file = None
    if api_key:
        tally["識別_試行"] += 1
        try:
            path = workdir / "trait.json"
            run([python, INGEST / "trait.py", "--character", entry["name"],
                 "--work", entry.get("work", ""), "--out", path],
                stderr=subprocess.PIPE, text=True)
            trait_file = path
            tally["識別"] += 1
        except subprocess.CalledProcessError as err:
            why = note_lane_failure("識別", err, tally)
            print(f"  識別レーン失敗（続行）: {why}")

    if not danbooru_file and not classify_file and not trait_file:
        raise RuntimeError("この件で使える証拠がありません（danbooru も分類結果も識別結果も無い）")

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
    if trait_file:
        merge_cmd += ["--traits", trait_file]
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
    tally = {"資料": 0, "資料_試行": 0, "識別": 0, "識別_試行": 0}
    for entry in targets:
        print(f"\n=== {entry['id']} ===")
        try:
            process(entry, api_key, args.sleep, tally)
        except (subprocess.CalledProcessError, RuntimeError, SystemExit) as err:
            print(f"  失敗: {err}")
            failed.append(entry["id"])

    print(f"\n完了 {len(targets) - len(failed)} / {len(targets)} 件" + (f"（失敗: {', '.join(failed)}）" if failed else ""))
    for lane in ("資料", "識別"):
        tried = tally[f"{lane}_試行"]
        if tried:
            print(f"  {lane}レーン: {tally[lane]} / {tried} 件")
    write_run_summary(targets, failed, tally)
    if len(failed) == len(targets):
        return 1

    # レーンが一件も通らないのは、そのキャラの事情ではなく設定の問題
    # （モデル名が古い等）。12 巡目にこれで両レーンが黙って落ちたまま
    # ワークフローが success を返し続けていたので、失敗として扱う。
    dead = [
        lane for lane in ("資料", "識別")
        if tally[f"{lane}_試行"] >= 3 and tally[lane] == 0
    ]
    if dead:
        print(f"\n{'・'.join(dead)}レーンが全件で失敗しました。"
              "個別の事情ではなく設定の問題です（多いのは残高切れとモデル名の世代交代）。")
        for lane in dead:
            if tally.get(f"{lane}_理由"):
                print(f"  {lane}レーンの理由: {tally[f'{lane}_理由']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
