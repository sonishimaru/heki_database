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

# 画像・タグ集計だけで判定する軸（classify はここへ踏み込めない）。
# 体格・種族・記号職・痕・目の形は appearance 配下だが、公式プロフィールや百科にも
# 明記されるため資料レーン（classify）からも判定を許す。
# 痕を開けたのは、義肢・包帯・目隠しが Danbooru のタグ付与率で閾値に届かず、
# かつ資料レーンからも触れないため、どちらのレーンからも埋まらなかったから。
# 目の形も同じ理由。294 名分の実測（near_miss）で、tsurime は最高 0.20 が 1 件、
# tareme と jitome は 0.15 にすら一度も届かなかった。髪色が 240 件当たるのに
# 目つきが延べ 2 件しか当たらないのは、Danbooru が目つきをそもそも付けないから。
# 閾値を下げても届かないので、レーンを開けるほうを選んだ。
VISUAL_AXES = {
    "appearance.hairstyle",
    "appearance.haircolor",
    "appearance.eyecolor",
    "appearance.face",
    "appearance.parts",
    "appearance.costume",
    "appearance.item",
}
VISUAL_GROUPS = {"appearance"}  # 後方互換（ダッシュボードの表示用）

WEIGHT_ORDER = {"core": 0, "sub": 1, "spice": 2}


def load_db() -> dict:
    if not DB.exists():
        raise SystemExit("docs/data/db.json がありません。先に python3 tools/build.py を実行してください。")
    return json.loads(DB.read_text(encoding="utf-8"))


def vocabulary(db: dict, groups: set[str] | None = None, exclude_axes: set[str] | None = None) -> list[dict]:
    """見出し語の一覧。groups で大分類を絞り、exclude_axes で軸を除外する。"""
    return [
        e
        for e in db["elements"]
        if (groups is None or e["group"] in groups)
        and (exclude_axes is None or e["axis"] not in exclude_axes)
    ]


def vocabulary_block(db: dict, groups: set[str] | None = None, exclude_axes: set[str] | None = None) -> str:
    """モデルに渡す語彙表。id と名前と一行定義だけを、軸ごとにまとめる。"""
    lines: list[str] = []
    current = None
    for e in sorted(vocabulary(db, groups, exclude_axes), key=lambda x: (x["axis"], x["id"])):
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

    image = entry.get("image") or {}
    if image.get("url"):
        out.append("  image:")
        for key in ("url", "page", "credit"):
            if image.get(key):
                out.append(f"    {key}: {yaml_quote(image[key])}")

    analysis = entry.get("analysis") or {}
    if analysis:
        out.append("  analysis:")
        for key in ("method", "model", "frames", "cuts", "date"):
            if analysis.get(key) not in (None, ""):
                out.append(f"    {key}: {yaml_quote(analysis[key])}")

    out.append("  elements:")
    for item in sorted(entry["elements"], key=lambda x: (WEIGHT_ORDER[x["weight"]], x["id"])):
        note = f", note: {yaml_quote(item['note'])}" if item.get("note") else ""
        src = f", src: {item['src']}" if item.get("src") else ""
        out.append(f"    - {{id: {item['id']}, weight: {item['weight']}{note}{src}}}")

    patterns = entry.get("patterns") or []
    out.append(f"  patterns: [{', '.join(patterns)}]")
    return "\n".join(out) + "\n"


# --- Gemini API ---

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def gemini_api_key() -> str:
    import os

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY が未設定です。--prompt-only で出したプロンプトを AI Studio に貼り、"
            "応答を --from-json で読み込む方法もあります。"
        )
    return key


class GeminiEmptyResponse(RuntimeError):
    """候補が返らなかった（安全フィルタ等）。モデルを変えても直らないので即座に諦める。"""


class GeminiHTTPError(RuntimeError):
    def __init__(self, code: int, detail: str):
        super().__init__(f"Gemini API エラー {code}: {detail}")
        self.code = code


def call_gemini(model: str, parts: list[dict], schema: dict, api_key: str, temperature: float = 0.2) -> dict:
    """generateContent を叩き、構造化 JSON を返す。"""
    import urllib.error
    import urllib.request

    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": temperature,
            "response_mime_type": "application/json",
            "response_schema": schema,
        },
    }
    request = urllib.request.Request(
        GEMINI_ENDPOINT.format(model=model) + f"?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.loads(response.read())
    except urllib.error.HTTPError as err:
        raise GeminiHTTPError(err.code, err.read().decode("utf-8", "replace")[:500])
    candidates = payload.get("candidates") or []
    if not candidates:
        # 安全フィルタでブロックされた場合など。理由を出して呼び出し元に投げる
        reason = (payload.get("promptFeedback") or {}).get("blockReason") or "理由不明"
        raise GeminiEmptyResponse(f"{model} が候補を返しませんでした（{reason}）")
    parts_out = (candidates[0].get("content") or {}).get("parts") or []
    if not parts_out:
        reason = candidates[0].get("finishReason") or "理由不明"
        raise GeminiEmptyResponse(f"{model} の応答が空でした（{reason}）")
    return json.loads(parts_out[0]["text"])


def call_gemini_fallback(models: list[str], parts, schema, api_key: str, temperature: float = 0.2):
    """モデル候補を順に試す。キーの世代によって使えるモデル名が違うため（404 は次候補へ）。

    成功したモデル名と結果のタプルを返す。
    """
    last = None
    for model in models:
        try:
            return model, call_gemini(model, parts, schema, api_key, temperature)
        except GeminiEmptyResponse as err:
            # モデルを変えても同じ結果になるので、traceback を出さずに諦める
            raise SystemExit(str(err))
        except GeminiHTTPError as err:
            last = err
            if err.code in (404, 429):
                reason = "利用不可" if err.code == 404 else "クォータ超過"
                print(f"  モデル {model} は{reason}（{err.code}）。次の候補を試します。")
                continue
            raise
    raise SystemExit(f"利用できるモデルがありません: {', '.join(models)}\n{last}")


def image_part(path) -> dict:
    import base64
    import mimetypes
    from pathlib import Path as _Path

    path = _Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return {
        "inline_data": {
            "mime_type": mime,
            "data": base64.b64encode(path.read_bytes()).decode("ascii"),
        }
    }
