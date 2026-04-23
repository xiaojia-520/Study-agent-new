from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.application.video.subtitle_service import VideoSubtitleService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert an audio/video file to SRT subtitles with FunASR.")
    parser.add_argument("input", type=Path, help="Input audio/video file path.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("tmp_wav"),
        help="Directory for extracted wav and default SRT output.",
    )
    parser.add_argument("--srt", type=Path, default=None, help="Optional explicit SRT output path.")
    parser.add_argument("--max-chars", type=int, default=22, help="Maximum characters per subtitle segment.")
    parser.add_argument(
        "--max-duration-ms",
        type=int,
        default=5000,
        help="Maximum duration per subtitle segment.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = VideoSubtitleService()
    result = service.file_to_srt(
        args.input,
        output_dir=args.output_dir,
        srt_path=args.srt,
        max_chars=args.max_chars,
        max_duration_ms=args.max_duration_ms,
    )
    print(f"SRT: {result.srt_path}")
    print(f"WAV: {result.wav_path}")
    print(f"Segments: {len(result.segments)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
