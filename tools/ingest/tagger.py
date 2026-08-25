#!/usr/bin/env python3
"""WD-Tagger（Danbooru 語彙のアニメ画像タガー）でフレームにタグを付ける。

  pip install onnxruntime huggingface_hub pillow numpy pandas
  python3 tools/ingest/tagger.py work/frames/*.jpg --out work/tags.json

出力はフレームごとのタグとスコア。見出し語への翻訳は merge.py が wd_map.yaml を使って行う。
GPU があるなら onnxruntime-gpu を入れると速い。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_REPO = "SmilingWolf/wd-swinv2-tagger-v3"


def load_model(repo: str):
    from huggingface_hub import hf_hub_download
    import onnxruntime as ort
    import pandas as pd

    model_path = hf_hub_download(repo, "model.onnx")
    tags_path = hf_hub_download(repo, "selected_tags.csv")
    session = ort.InferenceSession(model_path, providers=ort.get_available_providers())
    tags = pd.read_csv(tags_path)
    names = tags["name"].tolist()
    categories = tags["category"].tolist()
    general = [i for i, c in enumerate(categories) if c == 0]
    character = [i for i, c in enumerate(categories) if c == 4]
    return session, names, general, character


def preprocess(path: str, size: int):
    import numpy as np
    from PIL import Image

    image = Image.open(path).convert("RGBA")
    canvas = Image.new("RGBA", image.size, (255, 255, 255))
    canvas.alpha_composite(image)
    image = canvas.convert("RGB")

    side = max(image.size)
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(image, ((side - image.width) // 2, (side - image.height) // 2))
    if side != size:
        square = square.resize((size, size), Image.BICUBIC)

    array = np.asarray(square, dtype=np.float32)
    array = array[:, :, ::-1]  # WD-Tagger は BGR 入力
    return np.expand_dims(array, axis=0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="Hugging Face のモデル repo")
    parser.add_argument("--out", default="work/tags.json")
    parser.add_argument("--threshold", type=float, default=0.25, help="この値未満のタグは記録しない")
    args = parser.parse_args()

    try:
        import numpy as np  # noqa: F401
    except ImportError:
        raise SystemExit("依存が足りません: pip install onnxruntime huggingface_hub pillow numpy pandas")

    session, names, general_idx, character_idx = load_model(args.repo)
    _, size, _, _ = session.get_inputs()[0].shape
    if not isinstance(size, int):
        size = 448
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name

    frames = []
    for path in args.images:
        scores = session.run([output_name], {input_name: preprocess(path, size)})[0][0]
        frames.append(
            {
                "file": str(Path(path)),
                "tags": {
                    names[i]: round(float(scores[i]), 4)
                    for i in general_idx
                    if scores[i] >= args.threshold
                },
                "character_guess": {
                    names[i]: round(float(scores[i]), 4)
                    for i in character_idx
                    if scores[i] >= 0.5
                },
            }
        )
        print(f"{path}: {len(frames[-1]['tags'])} タグ")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"repo": args.repo, "threshold": args.threshold, "frames": frames}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"{len(frames)} フレーム → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
