#!/usr/bin/env python3
"""WD-Tagger の外見タグと Gemini Vision の読みを統合し、characters.yaml の断片を出力する。

  python3 tools/ingest/merge.py --tags work/tags.json --vision work/classify.json \
      --name 名前 --work 作品 --kana かな [--append]

比重は「継続して出ている特徴ほど骨格に近い」という前提で決める。
全カットに出続ける髪型は core、一カットだけの小物は spice になる。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

CHARACTERS = common.ROOT / "data" / "characters.yaml"
AUTO_CHARACTERS = common.ROOT / "data" / "characters_auto.yaml"
SUGGESTIONS = common.ROOT / "data" / "suggestions.yaml"
AUTO_HEADER = """# 機械が生成・更新するキャラクター（自動取り込みの下書き）
#
# このファイルは tools/ingest/auto.py が全体を書き直す。手で編集しないこと。
# レビューして採用するときは、そのエントリを data/characters.yaml へ移して磨く。
# 同じ id が characters.yaml にある場合、そちらが優先され、このファイル側は無視される。
"""



def from_tags(tags_path: Path) -> tuple[list[dict], int]:
    """フレームごとのタグを見出し語へ翻訳する。"""
    payload = json.loads(tags_path.read_text(encoding="utf-8"))
    frames = payload["frames"]
    if not frames:
        return [], 0

    mapping = yaml.safe_load(common.WD_MAP.read_text(encoding="utf-8"))
    default_threshold = mapping.get("defaults", {}).get("threshold", 0.35)

    results = []
    for element_id, spec in mapping["elements"].items():
        threshold = spec.get("threshold", default_threshold)
        hits, best_score, best_tag = 0, 0.0, None
        for frame in frames:
            frame_best = 0.0
            frame_tag = None
            for tag in spec["tags"]:
                score = frame["tags"].get(tag, 0.0)
                if score > frame_best:
                    frame_best, frame_tag = score, tag
            if frame_best >= threshold:
                hits += 1
                if frame_best > best_score:
                    best_score, best_tag = frame_best, frame_tag
        if not hits:
            continue
        coverage = hits / len(frames)
        results.append(
            {
                "id": element_id,
                "weight": common.decide_weight(coverage, best_score),
                "confidence": common.confidence_of(best_score),
                "source": "wd-tagger",
                "note": f"{best_tag} {best_score:.2f} / {hits}・{len(frames)}枚",
                "_coverage": round(coverage, 2),
            }
        )
    return results, len(frames)


# 見出し語の候補にならない汎用タグ（構図・ポーズ・背景・画面上の記号など）
GENERIC_TAGS = {
    "solo", "1girl", "1boy", "2girls", "2boys", "multiple_girls", "multiple_boys",
    "looking_at_viewer", "looking_back", "looking_to_the_side", "smile", "grin",
    "open_mouth", "closed_mouth", "parted_lips", "blush", "teeth", "upper_teeth_only",
    "simple_background", "white_background", "grey_background", "gradient_background",
    "upper_body", "full_body", "cowboy_shot", "portrait", "close-up", "standing",
    "sitting", "holding", "arm_up", "arms_up", "hand_up", "hands_up", "long_sleeves",
    "short_sleeves", "sleeveless", "bare_shoulders", "collared_shirt", "shirt",
    "white_shirt", "black_shirt", "skirt", "black_skirt", "pleated_skirt", "dress",
    "jacket", "pants", "shorts", "thighhighs", "pantyhose", "socks", "shoes", "boots",
    "bangs", "sidelocks", "hair_ornament", "hairclip", "hairband", "ribbon",
    "hair_ribbon", "bow", "hair_bow", "neck_ribbon", "bowtie", "necktie", "jewelry",
    "earrings", "one_eye_closed", "day", "outdoors", "indoors", "sky", "cloud",
    "blurry", "blurry_background", "depth_of_field", "official_alternate_costume",
    "alternate_costume", "cosplay", "chibi", "heart", "sweat", "speech_bubble",
    "signature", "artist_name", "watermark", "twitter_username", "virtual_youtuber",
    "medium_breasts", "cleavage", "navel", "midriff", "floating_hair",
    "breasts", "male_focus", "parted_bangs", "x_hair_ornament", "detached_sleeves",
    "capelet", "white_capelet", "black_necktie", "ringed_eyes", "forked_eyebrows",
    "roswaal_mansion_maid_uniform", "demon_slayer_uniform",
    "nude", "safety_pin", "forehead", "sash", "wide_sleeves", "sweater_vest",
    "black_dress", "bamboo", "symbol-shaped_pupils", "cross-shaped_pupils",
    "slit_pupils", "tokiwadai_school_uniform", "summer_uniform",
    "pink_ribbon", "red_ribbon", "blue_ribbon",
    "ascot", "blue_sailor_collar", "black_thighhighs", "white_thighhighs",
    "paradis_military_uniform", "purple_ribbon", "white_dress", "hat",
    "flower", "hair_flower", "white_flower", "blood", "rei_no_himo",
    "clothing_cutout", "cleavage_cutout", "pencil_dress", "bodysuit",
    "white_bodysuit", "plugsuit_(evangelion)", "mecha_pilot_suit",
    # 作品固有の制服・装備
    "azumanga_daioh's_school_uniform", "kita_high_school_uniform",
    "icho_private_high_school_uniform", "kurumi-gaoka_high_school_uniform",
    "sailor_senshi_uniform", "checkered_haori", "three-dimensional_maneuver_gear",
    "hairpods", "winter_uniform",
    # 汎用の服飾
    "cardigan", "suit", "blue_jacket", "blue_skirt", "plaid_clothes", "plaid_skirt",
    "puffy_sleeves", "white_ascot", "swimsuit", "bikini",
    # 装飾小物（hair_ornament / jewelry と同類）
    "circlet", "crescent", "crescent_earrings", "red_choker", "gem", "green_gem",
    "brooch", "triangular_headpiece", "white_hairband", "hair_intakes",
    # 作品固有（制服・装備・固有名）
    "super_saiyan", "saiyan_armor", "dragonslayer_(sword)", "flak_jacket",
    "konohagakure_shinobi_uniform", "jujutsu_tech_uniform", "dougi",
    "shuuchiin_academy_school_uniform", "kamiyama_high_school_uniform_(hyouka)",
    "naoetsu_high_school_uniform", "sobu_high_school_uniform",
    "sakuragaoka_high_school_uniform", "interface_headset_(evangelion)",
    "print_haori", "red_haori", "kikkoumon", "hair_tubes", "kishimen_hair",
    # 汎用の服飾・装飾
    "necklace", "red_bow", "black_bow", "hat_bow", "red_bowtie", "red_necktie",
    "black_jacket", "red_skirt", "belt", "black_belt", "buttons", "pocket",
    "breast_pocket", "object_in_pocket", "pen_in_pocket", "beads", "wrist_cuffs",
    "detached_collar", "high_collar", "ribbon_trim", "tooth_necklace",
    "formal_clothes", "black_pantyhose", "black_shorts", "apron",
    "leotard", "black_leotard", "strapless_leotard", "strapless", "red_bodysuit",
    "playboy_bunny", "animal_print", "tiger_print", "fake_animal_ears",
    "transparent_background", "cat",
}


def from_danbooru(path: Path) -> list[dict]:
    """Danbooru の関連タグ頻度（群衆合意）を見出し語へ翻訳する。

    frequency は「そのキャラのタグが付いた投稿のうち、このタグも付いている割合」なので、
    そのまま出現率として扱える。数千枚の人力タグの合意であり、少数フレームの機械タグより強い。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    freq = {row["name"]: row["frequency"] for row in payload["related_tags"] if row.get("name")}
    mapping = yaml.safe_load(common.WD_MAP.read_text(encoding="utf-8"))
    default_threshold = mapping.get("defaults", {}).get("threshold", 0.35)

    mapped_tags = {tag for spec in mapping["elements"].values() for tag in spec["tags"]}
    results = []
    for element_id, spec in mapping["elements"].items():
        threshold = spec.get("threshold", default_threshold)
        best_tag, best_freq = None, 0.0
        for tag in spec["tags"]:
            value = freq.get(tag, 0.0)
            if value > best_freq:
                best_tag, best_freq = tag, value
        if best_freq < threshold:
            continue
        results.append(
            {
                "id": element_id,
                "weight": common.decide_weight(best_freq, best_freq),
                "confidence": common.confidence_of(best_freq),
                "source": "danbooru",
                "note": f"danbooru {best_tag} {best_freq:.0%}",
                "_coverage": round(best_freq, 2),
            }
        )
    # 対応表に無い高頻度タグ = 語彙の穴の候補。suggestions として蓄積する
    unmapped = [
        {"tag": name, "frequency": value}
        for name, value in sorted(freq.items(), key=lambda kv: -kv[1])
        if value >= 0.35 and name not in mapped_tags and name not in GENERIC_TAGS
    ][:10]
    return results, unmapped


def image_from_anilist(path: Path) -> dict:
    """AniList の取得結果から参照用の画像リンクを取り出す。

    画像そのものはリポジトリに置かない。保持するのは URL と出典ページだけで、
    サイト側はクレジットと出典リンクを添えて参照表示する。
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    url = payload.get("image")
    if not url:
        return {}
    return {"url": url, "page": payload.get("url") or "", "credit": "AniList"}


def from_vision(vision_path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(vision_path.read_text(encoding="utf-8"))
    items = [
        {
            "id": item["id"],
            "weight": item["weight"],
            "confidence": item["confidence"],
            "source": "gemini",
            "note": item.get("evidence", ""),
        }
        for item in payload.get("elements", [])
    ]
    return items, payload


def merge(items: list[dict]) -> list[dict]:
    """同じ見出し語が両方から出たら、強いほうの比重を採用してメモを併記する。"""
    merged: dict[str, dict] = {}
    for item in items:
        current = merged.get(item["id"])
        if current is None:
            merged[item["id"]] = dict(item)
            continue
        if common.WEIGHT_ORDER[item["weight"]] < common.WEIGHT_ORDER[current["weight"]]:
            current["weight"] = item["weight"]
        notes = [n for n in (current.get("note"), item.get("note")) if n]
        current["note"] = " / ".join(dict.fromkeys(notes))
        current["source"] = "both"
    return list(merged.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tags", type=Path, help="tagger.py の出力")
    parser.add_argument("--danbooru", type=Path, help="fetch.py danbooru の出力（外見の群衆合意）")
    parser.add_argument("--vision", type=Path, help="classify.py の出力")
    parser.add_argument("--anilist", type=Path, help="fetch.py anilist の出力（参照用の画像リンク）")
    parser.add_argument("--name", required=True)
    parser.add_argument("--work", required=True)
    parser.add_argument("--kana", default="")
    parser.add_argument("--year", type=int)
    parser.add_argument("--author", default="")
    parser.add_argument("--summary", default="")
    parser.add_argument("--id", dest="char_id")
    parser.add_argument("--cuts", type=int, help="カット数（scenes.py の cuts.json から）")
    parser.add_argument("--date", default="", help="分析日")
    parser.add_argument("--min-confidence", choices=["low", "mid", "high"], default="low")
    parser.add_argument("--append", action="store_true", help="data/characters.yaml に追記する")
    parser.add_argument("--write-auto", action="store_true", help="data/characters_auto.yaml へ upsert する（自動実行用）")
    args = parser.parse_args()

    if not args.tags and not args.vision and not args.danbooru:
        raise SystemExit("--tags / --danbooru / --vision のいずれかは必要です。")

    db = common.load_db()
    known = {e["id"] for e in db["elements"]}

    items: list[dict] = []
    frames = 0
    vision_payload: dict = {}
    unmapped: list[dict] = []
    if args.tags:
        tag_items, frames = from_tags(args.tags)
        items += tag_items
    if args.danbooru:
        danbooru_items, unmapped = from_danbooru(args.danbooru)
        items += danbooru_items
    if args.vision:
        vision_items, vision_payload = from_vision(args.vision)
        items += vision_items

    unknown = sorted({i["id"] for i in items if i["id"] not in known})
    items = [i for i in items if i["id"] in known]

    order = {"low": 0, "mid": 1, "high": 2}
    dropped_low = [i for i in items if order[i["confidence"]] < order[args.min_confidence]]
    items = [i for i in items if order[i["confidence"]] >= order[args.min_confidence]]

    merged = merge(items)
    if not merged:
        raise SystemExit("採用できる要素がありませんでした。閾値を下げるか、フレームを見直してください。")

    methods = sorted({i["source"] for i in merged})
    entry = {
        "id": args.char_id or common.slugify(args.name),
        "name": args.name,
        "kana": args.kana or args.name,
        "work": args.work,
        "year": args.year,
        "author": args.author,
        "summary": args.summary or vision_payload.get("summary", "") or "（要記入）",
        "analysis": {
            "method": "+".join(methods),
            "model": (vision_payload.get("_meta") or {}).get("model", ""),
            "frames": frames or None,
            "cuts": args.cuts,
            "date": args.date,
        },
        "elements": [
            {"id": i["id"], "weight": i["weight"], "note": i["note"]} for i in merged
        ],
        "patterns": [],
    }
    if args.anilist and args.anilist.exists():
        image = image_from_anilist(args.anilist)
        if image:
            entry["image"] = image

    if args.write_auto:
        # 今回動いたレーンの要素だけを置き換え、動かなかったレーンの前回結果は引き継ぐ。
        # （外見だけの再取得で、前回の分類結果や summary を消さないため）
        for element, item in zip(entry["elements"], merged):
            element["src"] = item["source"]
        existing = []
        if AUTO_CHARACTERS.exists():
            existing = yaml.safe_load(AUTO_CHARACTERS.read_text(encoding="utf-8")) or []
        previous = next((e for e in existing if e.get("id") == entry["id"]), None)
        if previous:
            new_lanes = {element["src"] for element in entry["elements"]}
            new_ids = {element["id"] for element in entry["elements"]}
            for old in previous.get("elements") or []:
                if old.get("src") and old["src"] not in new_lanes and old["id"] not in new_ids:
                    entry["elements"].append(old)
            if entry["summary"] in ("", "（要記入）"):
                entry["summary"] = previous.get("summary", entry["summary"])
            if not entry.get("image") and previous.get("image"):
                entry["image"] = previous["image"]
            entry["patterns"] = previous.get("patterns") or []
            lanes = sorted({element.get("src", "?") for element in entry["elements"]})
            entry["analysis"]["method"] = "+".join(lanes)
        entry["analysis"]["method"] = (entry["analysis"]["method"] or "") + "+auto"
        existing = [e for e in existing if e.get("id") != entry["id"]]
        existing.append(entry)
        existing.sort(key=lambda e: e["id"])
        AUTO_CHARACTERS.write_text(
            AUTO_HEADER + "\n" + "\n".join(common.emit_character_yaml(e) for e in existing),
            encoding="utf-8",
        )
        print(f"data/characters_auto.yaml を更新しました（{entry['id']} / {len(merged)} 要素）")

        # 語彙の穴を suggestions に蓄積（人がレビューして見出し語に昇格させる）
        new_tags = vision_payload.get("new_tags") or []
        if unmapped or new_tags:
            existing_s = []
            if SUGGESTIONS.exists():
                # 語彙の穴の蓄積は付帯的な出力なので、壊れていても本体は止めない
                try:
                    existing_s = yaml.safe_load(SUGGESTIONS.read_text(encoding="utf-8")) or []
                except yaml.YAMLError as err:
                    print(f"警告: {SUGGESTIONS} を読めないので作り直します（{err.__class__.__name__}）")
                    existing_s = []
            existing_s = [s for s in existing_s if s.get("id") != entry["id"]]
            existing_s.append(
                {
                    "id": entry["id"],
                    "name": entry["name"],
                    "date": (entry.get("analysis") or {}).get("date", ""),
                    "unmapped_danbooru": unmapped,
                    "new_tag_proposals": new_tags,
                }
            )
            existing_s.sort(key=lambda s: s["id"])
            header = (
                "# 語彙の穴の候補（自動蓄積。tools/ingest/merge.py --write-auto が更新する）\n"
                "#\n"
                "# unmapped_danbooru: 対応表に無かった高頻度タグ。見出し語に昇格させるなら\n"
                "#   data/elements/ に追加し、wd_map.yaml に対応を書く。\n"
                "# new_tag_proposals: classify が語彙に無いと判断した概念の提案。\n"
                "# 採用・却下は人が決める。処理済みのエントリは消してよい。\n\n"
            )
            SUGGESTIONS.write_text(header + yaml.safe_dump(existing_s, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(f"  語彙の穴の候補 → data/suggestions.yaml（未対応タグ {len(unmapped)} / 新語提案 {len(new_tags)}）")
        return 0

    text = common.emit_character_yaml(entry)
    if args.append:
        with CHARACTERS.open("a", encoding="utf-8") as fh:
            fh.write("\n" + text)
        print(f"data/characters.yaml に追記しました（{len(merged)} 要素）")
    else:
        print(text)

    print(f"\n# 内訳: " + ", ".join(f"{k} {sum(1 for i in merged if i['weight'] == k)}" for k in ("core", "sub", "spice")), file=sys.stderr)
    if unknown:
        print(f"# 語彙にない id を破棄: {', '.join(unknown)}", file=sys.stderr)
    if dropped_low:
        print(f"# 確度が足りず除外: {', '.join(i['id'] for i in dropped_low)}", file=sys.stderr)
    if vision_payload.get("space_time"):
        print(f"# 空間・時間: {vision_payload['space_time']}", file=sys.stderr)
    for tag in vision_payload.get("new_tags", []):
        print(f"# 新語の提案: {tag['name']}（{tag.get('axis','?')}）… {tag.get('reason','')}", file=sys.stderr)
    print("# patterns は自動では決めない。性癖の成立は人が判断すること。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
