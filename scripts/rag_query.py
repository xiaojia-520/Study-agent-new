from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.rag_runtime import build_rag_runtime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query the transcript RAG index.")
    parser.add_argument("query", type=str, help="Question to search or answer.")
    parser.add_argument("--top-k", type=int, default=None, help="Override config.settings.RAG_TOP_K.")
    parser.add_argument(
        "--reindex-path",
        type=Path,
        default=None,
        help="Optional transcript file or directory to index before querying.",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show embedding progress when rebuilding the index before query.",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Use configured LLM to synthesize an answer. Otherwise retrieval-only mode is used.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection while reindexing if needed.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runtime = build_rag_runtime()
    try:
        if args.reindex_path is not None:
            runtime.indexing_service.index_path(
                path=args.reindex_path,
                embed_model=runtime.embed_model,
                show_progress=args.show_progress,
                recreate_if_mismatch=args.recreate,
            )

        top_k = args.top_k or runtime.config.top_k
        if args.with_llm:
            if runtime.llm is None:
                raise ValueError("LLM is not enabled. Set RAG_ENABLE_LLM=true and provide provider settings.")
            answer = runtime.query_service.query(
                args.query,
                top_k=top_k,
                embed_model=runtime.embed_model,
                llm=runtime.llm,
            )
            payload = {
                "query": answer.query,
                "answer": answer.answer,
                "results": [asdict(result) for result in answer.results],
                "metadata": answer.metadata,
            }
        else:
            results = runtime.query_service.search(
                args.query,
                top_k=top_k,
                embed_model=runtime.embed_model,
            )
            payload = {
                "query": args.query,
                "results": [asdict(result) for result in results],
            }

        print(json.dumps(payload, ensure_ascii=False, indent=2))
    finally:
        runtime.index_store.close()


if __name__ == "__main__":
    main()
