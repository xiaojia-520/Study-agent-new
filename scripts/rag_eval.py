from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.rag_eval import build_session_registry, evaluate_cases, load_eval_cases
from src.application.rag_runtime import build_rag_runtime
from web.backend.app.services.session_rag_query_service import SessionRagQueryService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a minimal evaluation set against the transcript RAG pipeline.")
    parser.add_argument(
        "--cases",
        type=Path,
        required=True,
        help="JSONL file containing evaluation cases.",
    )
    parser.add_argument(
        "--reindex-path",
        type=Path,
        default=None,
        help="Optional transcript file or directory to index before evaluation.",
    )
    parser.add_argument(
        "--show-progress",
        action="store_true",
        help="Show embedding progress when rebuilding the index before evaluation.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Recreate the collection while reindexing if needed.",
    )
    parser.add_argument(
        "--with-llm",
        action="store_true",
        help="Use LLM by default for cases that do not set with_llm explicitly.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=None,
        help="Default top_k for cases that do not set top_k explicitly.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to save the JSON report.",
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

        cases = load_eval_cases(args.cases)
        session_registry = build_session_registry(cases)
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            runtime_closer=lambda: None,
            session_getter=session_registry.get,
        )
        results = evaluate_cases(
            cases,
            service=service,
            default_with_llm=args.with_llm,
            default_top_k=args.top_k,
        )

        passed_count = sum(1 for result in results if result.passed)
        payload = {
            "summary": {
                "case_count": len(results),
                "passed_count": passed_count,
                "failed_count": len(results) - passed_count,
                "pass_rate": round((passed_count / len(results)) if results else 0.0, 4),
                "with_llm_default": args.with_llm,
                "top_k_default": args.top_k,
                "qdrant_collection": runtime.config.qdrant_collection,
                "qdrant_prefer_local": runtime.config.qdrant_prefer_local,
                "qdrant_local_path": str(runtime.config.qdrant_local_path),
                "reindex_path": str(args.reindex_path) if args.reindex_path is not None else None,
                "cases_path": str(args.cases),
            },
            "results": [result.to_dict() for result in results],
        }

        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text)
    finally:
        runtime.index_store.close()


if __name__ == "__main__":
    main()
