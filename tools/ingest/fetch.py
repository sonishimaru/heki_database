#!/usr/bin/env python3
"""公開の検索可能なリソースからキャラクターの素材を取得し、work/sources/ に保存する。

取得はここで終わり。判定は後段（merge.py / facts.py / classify.py）が行う。
標準ライブラリのみで動く。

  # AniList: キャラクター検索（プロフィール文＋公式画像）
  python3 tools/ingest/fetch.py anilist "Anya Forger" --download-image

  # Danbooru: キャラクタータグの関連タグ集計（外見の群衆合意）
  python3 tools/ingest/fetch.py danbooru anya_(spy_x_family)

  # 任意ページ: アニメ公式サイトのキャラページ、pixiv百科事典など（1ページ単位）
  python3 tools/ingest/fetch.py page "https://dic.pixiv.net/a/記事名"

マナー:
- 1 ページ・1 クエリ単位で取得し、巡回（クロール）はしない。
- 取得物は work/（gitignore 済み）にのみ置き、リポジトリへは再配布しない。
  データベースに入るのは抽出した「事実」と出典 URL だけ。
- 連続取得するときは間隔を空ける（既定で 1 秒スリープ）。
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SOURCES = Path("work/sources")
UA = "heki-database/1.0 (personal research; single-page fetch)"

ANILIST_QUERY = """
query ($search: String) {
  Character(search: $search) {
    id
    name { full native }
    image { large }
    description
    dateOfBirth { year month day }
    age
    gender
    media(perPage: 5, sort: POPULARITY_DESC) {
      nodes { title { romaji native } startDate { year } type }
    }
    siteUrl
  }
}
"""


def http(url: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
    headers = {"User-Agent": UA}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as err:
        raise SystemExit(f"HTTP {err.code}: {url}\n{err.read().decode('utf-8', 'replace')[:300]}")
    except urllib.error.URLError as err:
        raise SystemExit(f"接続できません: {url}（{err.reason}）ネットワーク制限のある環境では手元のマシンで実行してください。")


def save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"→ {path}")


def cmd_anilist(args) -> int:
    payload = json.dumps({"query": ANILIST_QUERY, "variables": {"search": args.search}}).encode()
    raw = json.loads(http("https://graphql.anilist.co", payload, "application/json"))
    character = (raw.get("data") or {}).get("Character")
    if not character:
        raise SystemExit(f"AniList にキャラクターが見つかりません: {args.search}")

    slug = common.slugify(character["name"]["full"] or args.search)
    out_path = Path(args.out) if args.out else SOURCES / f"anilist_{slug}.json"
    out = {
        "source": "anilist",
        "url": character.get("siteUrl"),
        "fetched_at": time.strftime("%Y-%m-%d"),
        "name": character["name"],
        "age": character.get("age"),
        "gender": character.get("gender"),
        "birthday": character.get("dateOfBirth"),
        "description": character.get("description"),
        "media": [
            {"title": n["title"], "year": (n.get("startDate") or {}).get("year"), "type": n.get("type")}
            for n in (character.get("media") or {}).get("nodes", [])
        ],
        "image": (character.get("image") or {}).get("large"),
    }
    save(out_path, json.dumps(out, ensure_ascii=False, indent=2))

    if args.download_image and out["image"]:
        time.sleep(args.sleep)
        image_bytes = http(out["image"])
        ext = Path(urllib.parse.urlparse(out["image"]).path).suffix or ".jpg"
        image_path = Path("work/art") / f"anilist_{slug}{ext}"
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(image_bytes)
        print(f"→ {image_path}（tagger.py にかける公式画像）")
    return 0


def cmd_danbooru(args) -> int:
    tag = args.tag.strip()
    # キャラクタータグと同時に付く一般タグの頻度 = そのキャラの外見の群衆合意。
    # solo（一人絵）に限定しないと、同じ絵に写る別キャラの髪色などが混入する。
    query = tag if args.no_solo else f"{tag} solo"
    url = (
        "https://danbooru.donmai.us/related_tag.json?"
        + urllib.parse.urlencode({"query": query, "category": "General", "limit": args.limit})
    )
    raw = json.loads(http(url))
    related = []
    for row in raw.get("related_tags", []):
        info = row.get("tag") or {}
        related.append(
            {
                "name": info.get("name"),
                "post_count": info.get("post_count"),
                "frequency": round(float(row.get("frequency") or 0.0), 4),
            }
        )
    if not related:
        raise SystemExit(f"関連タグが取れません。タグ名を確認してください: {tag}")

    time.sleep(args.sleep)
    wiki_url = f"https://danbooru.donmai.us/wiki_pages/{urllib.parse.quote(tag)}.json"
    wiki = {}
    try:
        wiki_raw = json.loads(http(wiki_url))
        wiki = {"other_names": wiki_raw.get("other_names", []), "body": wiki_raw.get("body", "")[:2000]}
    except SystemExit:
        pass  # wiki が無いタグもある

    out = {
        "source": "danbooru",
        "tag": tag,
        "url": f"https://danbooru.donmai.us/posts?tags={urllib.parse.quote(tag)}",
        "fetched_at": time.strftime("%Y-%m-%d"),
        "wiki": wiki,
        "related_tags": related,
    }
    slug = common.slugify(tag)
    out_path = Path(args.out) if args.out else SOURCES / f"danbooru_{slug}.json"
    save(out_path, json.dumps(out, ensure_ascii=False, indent=2))
    top = ", ".join(f"{r['name']} {r['frequency']:.0%}" for r in related[:8])
    print(f"  上位: {top}")
    print("  → merge.py に --danbooru で渡すと外見の見出し語に翻訳される")
    return 0


TAG_STRIP_RE = re.compile(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")


def iri_to_uri(url: str) -> str:
    """日本語などの非 ASCII を含む URL をパーセントエンコードする。"""
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii") if parts.netloc else parts.netloc,
            urllib.parse.quote(parts.path, safe="/%"),
            urllib.parse.quote(parts.query, safe="=&%"),
            urllib.parse.quote(parts.fragment, safe="%"),
        )
    )


def cmd_page(args) -> int:
    raw = http(iri_to_uri(args.url)).decode("utf-8", "replace")
    text = TAG_STRIP_RE.sub(" ", raw)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", text, flags=re.I)
    text = TAG_RE.sub(" ", text)
    text = html_mod.unescape(text)
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines()]
    body = "\n".join(line for line in lines if line)

    slug = common.slugify(urllib.parse.urlparse(args.url).path) or "page"
    out_path = Path(args.out) if args.out else SOURCES / f"page_{slug}.txt"
    header = f"# source: {args.url}\n# fetched: {time.strftime('%Y-%m-%d')}\n\n"
    save(out_path, header + body)
    print(f"  {len(body)} 文字。facts.py --pages に渡して事実を抽出する")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sleep", type=float, default=1.0, help="連続リクエストの間隔（秒）")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("anilist", help="AniList でキャラクターを検索する")
    p.add_argument("search", help="キャラクター名（ローマ字が確実）")
    p.add_argument("--download-image", action="store_true", help="公式画像も保存する（tagger.py 用）")
    p.add_argument("--out", help="保存先を指定する")
    p.set_defaults(func=cmd_anilist)

    p = sub.add_parser("danbooru", help="Danbooru の関連タグ集計（外見の群衆合意）")
    p.add_argument("tag", help="キャラクタータグ（例: anya_(spy_x_family)）")
    p.add_argument("--limit", type=int, default=80)
    p.add_argument("--no-solo", action="store_true", help="solo（一人絵）への限定を外す")
    p.add_argument("--out", help="保存先を指定する")
    p.set_defaults(func=cmd_danbooru)

    p = sub.add_parser("page", help="任意の 1 ページを取得してテキスト化する")
    p.add_argument("url")
    p.add_argument("--out", help="保存先を指定する")
    p.set_defaults(func=cmd_page)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
