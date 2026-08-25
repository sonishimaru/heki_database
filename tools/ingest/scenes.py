#!/usr/bin/env python3
"""PySceneDetect の AdaptiveDetector で動画をカット割りし、各カットの代表フレームを書き出す。

  pip install scenedetect[opencv]
  python3 tools/ingest/scenes.py video.mp4 --out work/frames --per-cut 3

代表フレームは各カットの前半・中盤・後半から等間隔で抜く。
同じ人物を複数カットで見ることが、後段の比重判定（継続して出る特徴＝骨格）の根拠になる。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument("--out", default="work/frames", help="フレームの出力先")
    parser.add_argument("--per-cut", type=int, default=3, help="1 カットあたりの代表フレーム数")
    parser.add_argument("--min-scene-len", type=int, default=15, help="この長さ未満のカットは結合する（フレーム数）")
    parser.add_argument("--adaptive-threshold", type=float, default=3.0)
    parser.add_argument("--start", help="開始位置 (例 00:01:30)")
    parser.add_argument("--end", help="終了位置")
    args = parser.parse_args()

    try:
        from scenedetect import AdaptiveDetector, SceneManager, open_video
        from scenedetect.scene_manager import save_images
    except ImportError:
        raise SystemExit("scenedetect が入っていません: pip install 'scenedetect[opencv]'")

    video = open_video(args.video)
    manager = SceneManager()
    manager.add_detector(
        AdaptiveDetector(
            adaptive_threshold=args.adaptive_threshold,
            min_scene_len=args.min_scene_len,
        )
    )
    if args.start:
        video.seek(args.start)
    manager.detect_scenes(video, end_time=args.end, show_progress=True)
    scenes = manager.get_scene_list()
    if not scenes:
        raise SystemExit("カットが検出できませんでした。--adaptive-threshold を下げてください。")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    images = save_images(
        scene_list=scenes,
        video=video,
        num_images=args.per_cut,
        output_dir=str(out),
        image_name_template="cut-$SCENE_NUMBER-$IMAGE_NUMBER",
        show_progress=True,
    )

    index = {
        "video": args.video,
        "cuts": len(scenes),
        "frames": sum(len(v) for v in images.values()),
        "scenes": [
            {
                "cut": i + 1,
                "start": start.get_timecode(),
                "end": end.get_timecode(),
                "seconds": round(end.get_seconds() - start.get_seconds(), 2),
                "images": [str(out / name) for name in images.get(i, [])],
            }
            for i, (start, end) in enumerate(scenes)
        ],
    }
    index_path = out / "cuts.json"
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{index['cuts']} カット / {index['frames']} フレーム → {index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
