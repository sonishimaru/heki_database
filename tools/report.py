#!/usr/bin/env python3
"""語彙の穴の定期レビュー用レポート。

毎巡「実例0の語はどれか」「どの軸が薄いか」「閾値に届かなかったタグは何か」を
その場限りのワンライナーで数えていたので、同じ数え方を毎回できるようにまとめた。

  python3 tools/report.py            … 全部
  python3 tools/report.py gaps       … 実例0の見出し語だけ
  python3 tools/report.py near       … 閾値に届かなかったタグの実測値だけ
  python3 tools/report.py names      … 名前の読みと Danbooru タグの食い違い
  python3 tools/report.py identity   … 共有率の高い語ばかりの人物を洗い出す
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "docs" / "data" / "db.json"
SUGGESTIONS = ROOT / "data" / "suggestions.yaml"


def load_db() -> dict:
    if not DB.exists():
        raise SystemExit("docs/data/db.json がありません。先に python3 tools/build.py を実行してください。")
    return json.loads(DB.read_text(encoding="utf-8"))


def load_suggestions() -> list[dict]:
    if not SUGGESTIONS.exists():
        return []
    try:
        return yaml.safe_load(SUGGESTIONS.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as err:
        print(f"警告: {SUGGESTIONS} を読めません（{err.__class__.__name__}）")
        return []


def axis_names(db: dict) -> dict[str, str]:
    return {
        axis["id"]: f"{group['name']}/{axis['name']}"
        for group in db["groups"]
        for axis in group["axes"]
    }


def report_gaps(db: dict) -> None:
    """実例が付いていない見出し語。次にどのキャラを入れるかの根拠になる。"""
    names = axis_names(db)
    empty: dict[str, list[str]] = defaultdict(list)
    thin: dict[str, list[str]] = defaultdict(list)
    for element in db["elements"]:
        count = len(element.get("characters") or [])
        if count == 0:
            empty[element["axis"]].append(element["name"])
        elif count == 1:
            thin[element["axis"]].append(element["name"])

    total = len(db["elements"])
    filled = total - sum(len(v) for v in empty.values())
    print(f"■ 実例のある見出し語: {filled} / {total}")
    if empty:
        print(f"\n  実例0（{sum(len(v) for v in empty.values())} 語）")
        for axis in sorted(empty):
            print(f"    {names.get(axis, axis)}: {'・'.join(sorted(empty[axis]))}")
    if thin:
        print(f"\n  実例1件だけ（{sum(len(v) for v in thin.values())} 語）")
        for axis in sorted(thin):
            print(f"    {names.get(axis, axis)}: {'・'.join(sorted(thin[axis]))}")


def report_axes(db: dict) -> None:
    """軸ごとの語数と実例の付き方。語を足すべき軸を見つける。"""
    names = axis_names(db)
    print("\n■ 軸ごとの状況（語数 / 実例のある語 / 延べ採用数）")
    per_axis: dict[str, list[dict]] = defaultdict(list)
    for element in db["elements"]:
        per_axis[element["axis"]].append(element)
    for axis in sorted(per_axis, key=lambda a: (names.get(a, a))):
        items = per_axis[axis]
        used = sum(1 for e in items if e.get("characters"))
        hits = sum(len(e.get("characters") or []) for e in items)
        flag = "  ←薄い" if used < len(items) / 2 else ""
        print(f"  {names.get(axis, axis):<18} {len(items):>3} 語 / {used:>3} 語に実例 / 延べ {hits:>4}{flag}")


def report_near_miss(suggestions: list[dict]) -> None:
    """閾値に届かなかったタグの実測値。閾値を勘で下げないための材料。"""
    print("\n■ 閾値に届かなかった対応（near_miss）")
    best: dict[tuple[str, str], dict] = {}
    counts: Counter = Counter()
    for entry in suggestions:
        for miss in entry.get("near_miss") or []:
            key = (miss["id"], miss.get("tag") or "")
            counts[key] += 1
            if key not in best or miss["frequency"] > best[key]["frequency"]:
                best[key] = {**miss, "name": entry.get("name", entry["id"])}
    if not best:
        print("  記録なし（取り込みを一度も実行していないか、全て閾値を超えている）")
        return
    print("  見出し語        タグ                       最高値 閾値  件数  最高値のキャラ")
    for key, miss in sorted(best.items(), key=lambda kv: -kv[1]["frequency"]):
        print(
            f"  {key[0]:<14} {key[1]:<26} {miss['frequency']:.2f}  {miss['threshold']:.2f}"
            f"  {counts[key]:>3}   {miss['name']}"
        )
    print("  ※ 最高値が閾値のすぐ下で件数が多いものは、閾値を下げる根拠になる。")
    print("     逆に単発で低いものは、そのキャラの絵柄の揺れなので触らない。")


def works_by_id() -> dict[str, str]:
    """人物 id → 作品名。未対応タグが何作品から出ているかを数えるのに使う。"""
    payload = yaml.safe_load((ROOT / "data" / "queue.yaml").read_text(encoding="utf-8")) or {}
    entries = payload.get("characters") if isinstance(payload, dict) else payload
    return {e["id"]: e.get("work") or "?" for e in entries or []}


def report_unmapped(suggestions: list[dict]) -> None:
    """対応表に無い高頻度タグと、資料レーンからの新語提案。

    昇格の基準は「2 作品以上から独立に出ていること」なので、件数ではなく
    作品数で数える。件数で数えていたせいで、鉄拳の 2 人から出た
    v-shaped_eyebrows が「複数作品」と出て、1 作品しか裏が無いのに
    基準を満たしたように見えていた（8 種のうち実際に 2 作品だったのは 4 種）。
    """
    works = works_by_id()
    tag_works: dict[str, set[str]] = {}
    tag_count: Counter = Counter()
    tag_best: dict[str, float] = {}
    proposal_works: dict[str, set[str]] = {}
    for entry in suggestions:
        work = works.get(entry["id"], "?")
        for row in entry.get("unmapped_danbooru") or []:
            tag_works.setdefault(row["tag"], set()).add(work)
            tag_count[row["tag"]] += 1
            tag_best[row["tag"]] = max(tag_best.get(row["tag"], 0.0), row["frequency"])
        for row in entry.get("new_tag_proposals") or []:
            label = row.get("name") or row.get("tag") or ""
            if label:
                proposal_works.setdefault(label, set()).add(work)

    print(f"\n■ 対応表に無い高頻度タグ（{len(tag_works)} 種）")
    ranked = sorted(tag_works, key=lambda t: (-len(tag_works[t]), -tag_best[t]))
    for tag in ranked[:30]:
        nwork = len(tag_works[tag])
        mark = f"  ←{nwork} 作品" if nwork >= 2 else ""
        print(f"  {tag:<34} {tag_count[tag]:>2} 件 / 最高 {tag_best[tag]:.2f}{mark}")
    if not tag_works:
        print("  なし")

    print(f"\n■ 資料レーンからの新語提案（{len(proposal_works)} 種）")
    ranked = sorted(proposal_works, key=lambda l: -len(proposal_works[l]))
    for label in ranked[:40]:
        nwork = len(proposal_works[label])
        mark = f"  ←{nwork} 作品" if nwork >= 2 else ""
        print(f"  {label:<28} {nwork:>2} 作品{mark}")
    if not proposal_works:
        print("  なし")


def report_identity(db: dict) -> None:
    """識別力の点検。共有率の高い語ばかりで構成された人物を洗い出す。

    「短髪・黒髪・青い目」だけで出来ている項目は、誰のことも指していない。
    """
    total = len(db["characters"]) or 1
    share = {e["id"]: len(e.get("characters") or []) / total for e in db["elements"]}
    names = {e["id"]: e["name"] for e in db["elements"]}

    print("\n■ 識別力（要素の共有率の低さ。低い語ほどその人を指す）")
    scored = []
    for c in db["characters"]:
        items = c.get("elements") or []
        if not items:
            continue
        # その人物のいちばん珍しい語の共有率。これが高いほど「誰でもない」
        best = min(share.get(i["id"], 0.0) for i in items)
        scored.append((best, c, items))
    scored.sort(key=lambda row: row[0], reverse=True)
    print("  もっとも珍しい語でも共有率が高い＝誰のことも指していない人物:")
    for best, c, items in scored[:10]:
        worst = sorted(items, key=lambda i: share.get(i["id"], 0.0))[:4]
        print(f"    {best:>5.1%}  {c['name']}（{c['work']}）"
              f" … {'・'.join(names.get(i['id'], i['id']) for i in worst)}")

    lanes = Counter()
    for c in db["characters"]:
        for i in c.get("elements") or []:
            lanes[i.get("src") or "（手作業）"] += 1
    print("\n  レーン別の採用数: " + " / ".join(f"{k} {v}" for k, v in lanes.most_common()))


def report_characters(db: dict) -> None:
    """キャラ側の穴。画像・レーン・要素数。"""
    characters = db["characters"]
    no_image = [c for c in characters if not (c.get("image") or {}).get("url")]
    no_gemini = [
        c
        for c in characters
        if "gemini" not in ((c.get("analysis") or {}).get("method") or "")
    ]
    thin = sorted(characters, key=lambda c: len(c.get("elements") or []))[:10]
    print(f"\n■ キャラクター {len(characters)} 名")
    print(f"  画像なし: {len(no_image)} 名" + (f" … {'・'.join(c['name'] for c in no_image[:12])}" if no_image else ""))
    print(f"  資料レーン未通過: {len(no_gemini)} 名" + (f" … {'・'.join(c['name'] for c in no_gemini[:12])}" if no_gemini else ""))
    print("  要素数の少ない順:")
    for c in thin:
        print(f"    {len(c.get('elements') or []):>2} 要素  {c['name']}（{c['work']}）")


def report_run() -> None:
    """直近の取り込みの結果。auto.py が data/last_run.yaml に残したもの。"""
    path = ROOT / "data" / "last_run.yaml"
    if not path.exists():
        print("\n■ 直近の取り込み: まだ記録がありません")
        return
    run = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    print(f"\n■ 直近の取り込み（{run.get('date', '日付不明')}）")
    print(f"  完了 {run.get('完了', '?')} / {run.get('対象', '?')} 件")
    failed = run.get("失敗") or []
    print(f"  失敗 {len(failed)} 件" + (f": {', '.join(failed)}" if failed else ""))
    for name, why in (run.get("失敗の理由") or {}).items():
        print(f"    {name}: {why}")
    for lane, count in (run.get("レーン") or {}).items():
        print(f"  {lane}レーン: {count} 件")
    for lane, why in (run.get("レーンの理由") or {}).items():
        print(f"    {lane}の理由: {why}")
    for kind, count in (run.get("取得元") or {}).items():
        print(f"  {kind}: {count} 件")
    for kind, why in (run.get("取得元の理由") or {}).items():
        print(f"    {kind}の理由: {why}")


def report_ids() -> None:
    """id と Danbooru タグが噛み合っていない件を並べる。

    貼り付けで作っているせいで、id だけ前の行のものが残ることがある。
    それ自体は実害が無いが、名前の側がずれていたことが一度あった
    （橘めいという名前に鮎沢美咲のタグが付いていて、別人の外見を
    取り込んでいた）。検証で落とすには当たりが緩いので、一覧で出す。
    """
    payload = yaml.safe_load((ROOT / "data" / "queue.yaml").read_text(encoding="utf-8")) or {}
    entries = payload.get("characters") if isinstance(payload, dict) else payload
    odd = []
    for entry in entries or []:
        tag = (entry.get("danbooru") or "").split("_(")[0]
        if not tag:
            continue
        shared = set(re.split(r"[-_]", entry["id"])) & set(re.split(r"[-_]", tag))
        if not shared:
            odd.append(f"{entry['id']:24} {entry['name']}（{entry.get('work')}） → {entry['danbooru']}")
    print(f"\n■ id と Danbooru タグに共通の語が無い件: {len(odd)}")
    print("  別名・略称なら問題ない。名前のほうがずれていないかだけ見る。")
    for row in odd:
        print("   ", row)


# かなをローマ字に直すための表。名前の読みと Danbooru タグを照らすのに使う。
# 正確な翻字は目的ではない（それなら辞書が要る）。綴りが大きく違えば
# 別人だと分かる、という程度の粗さで足りる。
KANA_ROMAJI = [
    ("きゃ", "kya"), ("きゅ", "kyu"), ("きょ", "kyo"),
    ("しゃ", "sha"), ("しゅ", "shu"), ("しょ", "sho"),
    ("ちゃ", "cha"), ("ちゅ", "chu"), ("ちょ", "cho"),
    ("にゃ", "nya"), ("にゅ", "nyu"), ("にょ", "nyo"),
    ("ひゃ", "hya"), ("ひゅ", "hyu"), ("ひょ", "hyo"),
    ("みゃ", "mya"), ("みゅ", "myu"), ("みょ", "myo"),
    ("りゃ", "rya"), ("りゅ", "ryu"), ("りょ", "ryo"),
    ("ぎゃ", "gya"), ("ぎゅ", "gyu"), ("ぎょ", "gyo"),
    ("じゃ", "ja"), ("じゅ", "ju"), ("じょ", "jo"),
    ("びゃ", "bya"), ("びゅ", "byu"), ("びょ", "byo"),
    ("ぴゃ", "pya"), ("ぴゅ", "pyu"), ("ぴょ", "pyo"),
    ("っ", ""), ("ー", ""),
    ("あ", "a"), ("い", "i"), ("う", "u"), ("え", "e"), ("お", "o"),
    ("か", "ka"), ("き", "ki"), ("く", "ku"), ("け", "ke"), ("こ", "ko"),
    ("さ", "sa"), ("し", "shi"), ("す", "su"), ("せ", "se"), ("そ", "so"),
    ("た", "ta"), ("ち", "chi"), ("つ", "tsu"), ("て", "te"), ("と", "to"),
    ("な", "na"), ("に", "ni"), ("ぬ", "nu"), ("ね", "ne"), ("の", "no"),
    ("は", "ha"), ("ひ", "hi"), ("ふ", "fu"), ("へ", "he"), ("ほ", "ho"),
    ("ま", "ma"), ("み", "mi"), ("む", "mu"), ("め", "me"), ("も", "mo"),
    ("や", "ya"), ("ゆ", "yu"), ("よ", "yo"),
    ("ら", "ra"), ("り", "ri"), ("る", "ru"), ("れ", "re"), ("ろ", "ro"),
    ("わ", "wa"), ("を", "o"), ("ん", "n"),
    ("が", "ga"), ("ぎ", "gi"), ("ぐ", "gu"), ("げ", "ge"), ("ご", "go"),
    ("ざ", "za"), ("じ", "ji"), ("ず", "zu"), ("ぜ", "ze"), ("ぞ", "zo"),
    ("だ", "da"), ("ぢ", "ji"), ("づ", "zu"), ("で", "de"), ("ど", "do"),
    ("ば", "ba"), ("び", "bi"), ("ぶ", "bu"), ("べ", "be"), ("ぼ", "bo"),
    ("ぱ", "pa"), ("ぴ", "pi"), ("ぷ", "pu"), ("ぺ", "pe"), ("ぽ", "po"),
    ("ぁ", "a"), ("ぃ", "i"), ("ぅ", "u"), ("ぇ", "e"), ("ぉ", "o"),
    ("ゃ", "ya"), ("ゅ", "yu"), ("ょ", "yo"), ("ゔ", "bu"),
]

# 読みと綴りが噛み合わないが、どちらも正しい人物。中国語読み・訳名・
# 称号の付き方で、翻字では一致しようがないもの。見つけるたびに足す。
NAME_EXCEPTIONS = {
    "ganyu": "中国語読み",
    "zhongli": "中国語読み",
    "chun-li": "中国語読み",
    "android-18": "訳名（人造人間18号）",
    "red-blood-cell": "訳名（赤血球）",
    "white-blood-cell": "訳名（白血球）",
    "princess-peach": "姫が princess に移る",
    "march-7th": "訳名（三月なのか）",
    "silver-wolf": "訳名（銀狼）",
}

KATAKANA_ONLY = re.compile(r"^[ァ-ヶー・\s]+$")
HAS_JAPANESE = re.compile(r"[\u3040-\u309f\u4e00-\u9fff]")


def to_romaji(kana: str) -> str:
    for a, b in KANA_ROMAJI:
        kana = kana.replace(a, b)
    return re.sub(r"[^a-z]", "", kana)


def report_names() -> None:
    """キューの名前が Danbooru タグと噛み合っているか。

    人物名を手で書いているので、別人の名前を書いてタグだけ正しい、という
    取り違えが 6 件あった（橘めい・旗彦・日渡茜・鳴子の説明文・雨宮優子・
    詩音）。id をタグから機械的に作るようにしたぶん ids の検査では
    引っかからなくなったので、名前は読みの側から見る。

    カタカナだけの名前は外来語で、読みと綴りが一致しないのが普通なので
    対象から外す（これを入れると 98 件が誤検出になった）。
    """
    payload = yaml.safe_load((ROOT / "data" / "queue.yaml").read_text(encoding="utf-8")) or {}
    entries = payload.get("characters") if isinstance(payload, dict) else payload
    odd, known, skipped = [], [], 0
    for entry in entries or []:
        name = entry.get("name") or ""
        if KATAKANA_ONLY.match(name) or not HAS_JAPANESE.search(name):
            skipped += 1
            continue
        tag = (entry.get("danbooru") or "").split("_(")[0]
        flat = re.sub(r"[^a-z0-9]", "", tag.lower())
        reading = to_romaji(entry.get("kana") or "")
        if not flat or not reading:
            continue
        # 長音や撥音の揺れを吸収するため、4 文字続けて一致する箇所があるかで見る。
        overlap = any(reading[i:i + 4] in flat for i in range(max(1, len(reading) - 3))) or any(
            flat[i:i + 4] in reading for i in range(max(1, len(flat) - 3))
        )
        if overlap:
            continue
        row = f"{entry['id']:24} {name}（{entry.get('work')}） かな={entry.get('kana')} tag={entry.get('danbooru')}"
        if entry["id"] in NAME_EXCEPTIONS:
            known.append(f"{row}  ← {NAME_EXCEPTIONS[entry['id']]}")
        else:
            odd.append(row)
    print(f"\n■ 名前の読みと Danbooru タグが噛み合わない件: {len(odd)}")
    print(f"  対象外（カタカナ名）{skipped} 件／既知の例外 {len(known)} 件")
    for row in odd:
        print("   ", row)
    if odd:
        print("  どちらが正しいか確かめる。訳名や別読みなら NAME_EXCEPTIONS に足す。")


def report_conflicts(db: dict) -> None:
    """同じ軸の中で両立しない語を同時に持っている人物。

    1 軸 1 ファセットという前提の上では、同じ軸の二つの値が両方立つのは
    どちらかが間違っている。別の軸をまたぐ対比（毒舌 × 敬語のような）は
    緊張であって矛盾ではないので、ここでは数えない。
    """
    elements = {e["id"]: e for e in db["elements"]}
    pairs = {
        tuple(sorted((e["id"], other)))
        for e in db["elements"]
        for other in e.get("contrasts_with") or []
        if other in elements and elements[other]["axis"] == e["axis"]
    }
    hits: dict[tuple[str, str], list[str]] = {}
    for character in db["characters"]:
        own = {item["id"] for item in character.get("elements") or []}
        for a, b in pairs:
            if a in own and b in own:
                key = (elements[a]["name"], elements[b]["name"])
                hits.setdefault(key, []).append(f"{character['name']}（{character.get('work')}）")
    total = sum(len(v) for v in hits.values())
    print(f"\n■ 同じ軸の中で両立しない語を同時に持つ件: {total}")
    for (a, b), who in sorted(hits.items(), key=lambda kv: -len(kv[1])):
        print(f"  {a} × {b}  {len(who)} 名")
        for name in who[:6]:
            print(f"      {name}")


def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    db = load_db()
    suggestions = load_suggestions()
    if which in ("all", "run"):
        report_run()
    if which in ("all", "ids"):
        report_ids()
    if which in ("all", "names"):
        report_names()
    if which in ("all", "conflicts"):
        report_conflicts(db)
    if which in ("all", "gaps"):
        report_gaps(db)
    if which in ("all", "axes"):
        report_axes(db)
    if which in ("all", "near"):
        report_near_miss(suggestions)
    if which in ("all", "unmapped"):
        report_unmapped(suggestions)
    if which in ("all", "identity"):
        report_identity(db)
    if which in ("all", "chars"):
        report_characters(db)


if __name__ == "__main__":
    main()
