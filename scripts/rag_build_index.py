from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.rag.runtime import build_rag_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build LlamaIndex + Qdrant index from transcript JSONL files.")
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Transcript file or directory. Defaults to config.settings.RAG_TRANSCRIPT_ROOT.",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show embedding progress when building the index.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection if it already exists or its dimension does not match.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = build_rag_runtime()
    try:
        summary = runtime.indexing_service.index_path(
            path=args.path,
            embed_model=runtime.embed_model,
            show_progress=args.show_progress,
            recreate_if_mismatch=args.recreate,
        )
        payload = {
            "record_count": summary.record_count,
            "chunk_count": summary.chunk_count,
            "document_count": summary.document_count,
            "session_count": summary.session_count,
            "session_ids": list(summary.session_ids),
            "qdrant_collection": runtime.config.qdrant_collection,
            "qdrant_prefer_local": runtime.config.qdrant_prefer_local,
            "qdrant_local_path": str(runtime.config.qdrant_local_path),
            "transcript_root": str(args.path or runtime.config.transcript_root),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        runtime.index_store.close()


if __name__ == "__main__":
    main()
