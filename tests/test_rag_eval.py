import tempfile
import unittest
from pathlib import Path

from src.application.rag.eval import EvalCase, load_eval_cases, score_eval_case
from src.core.knowledge.document_models import AnswerCitation, KnowledgeAnswer, SearchResult
from web.backend.app.services.session_rag_query_service import QueryScope


class RagEvalTests(unittest.TestCase):
    def test_load_eval_cases_parses_jsonl(self) -> None:
        content = "\n".join(
            [
                '{"id":"case-1","query":"What is a session?","scope":"current_lesson","session_id":"demo","course_id":"web","lesson_id":"intro","require_citations":true}',
                '{"query":"What is HTTP?","scope":"global"}',
            ]
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "cases.jsonl"
            path.write_text(content, encoding="utf-8")
            cases = load_eval_cases(path)

        self.assertEqual(len(cases), 2)
        self.assertEqual(cases[0].case_id, "case-1")
        self.assertEqual(cases[0].scope, QueryScope.CURRENT_LESSON)
        self.assertTrue(cases[0].require_citations)
        self.assertEqual(cases[1].case_id, "case-2")
        self.assertEqual(cases[1].scope, QueryScope.GLOBAL)

    def test_score_eval_case_requires_answer_when_requested(self) -> None:
        case = EvalCase(
            case_id="cookie-session-link",
            query="How do cookies relate to sessions?",
            scope=QueryScope.CURRENT_LESSON,
            session_id="demo",
            course_id="web",
            lesson_id="intro",
            with_llm=True,
            expected_substrings=("cookie", "session"),
            require_answer=True,
            require_citations=True,
        )
        answer = KnowledgeAnswer(
            query=case.query,
            answer=None,
            results=[
                SearchResult(
                    doc_id="doc-1",
                    content="A cookie stores a session identifier in the browser.",
                )
            ],
            citations=[
                AnswerCitation(
                    index=1,
                    doc_id="doc-1",
                    snippet="A cookie stores a session identifier in the browser.",
                )
            ],
            metadata={"answer_strategy": "retrieval_fallback"},
        )

        result = score_eval_case(case, answer, with_llm=True, top_k=5)

        self.assertFalse(result.passed)
        self.assertIn("answer is required but missing", result.failure_reasons)
        self.assertEqual(result.answer_strategy, "retrieval_fallback")

    def test_score_eval_case_uses_answer_text_when_present(self) -> None:
        case = EvalCase(
            case_id="session-definition",
            query="What is a session?",
            scope=QueryScope.CURRENT_LESSON,
            session_id="demo",
            course_id="web",
            lesson_id="intro",
            expected_substrings=("server-side mechanism", "multiple requests"),
            require_answer=True,
            require_citations=True,
        )
        answer = KnowledgeAnswer(
            query=case.query,
            answer="A session is a server-side mechanism for tracking a user across multiple requests [1].",
            results=[
                SearchResult(
                    doc_id="doc-1",
                    content="A session is a server-side mechanism for tracking a user across multiple requests.",
                )
            ],
            citations=[
                AnswerCitation(
                    index=1,
                    doc_id="doc-1",
                    snippet="A session is a server-side mechanism for tracking a user across multiple requests.",
                )
            ],
            metadata={"answer_strategy": "llm_synthesized"},
        )

        result = score_eval_case(case, answer, with_llm=True, top_k=5)

        self.assertTrue(result.passed)
        self.assertEqual(result.answer_strategy, "llm_synthesized")
        self.assertEqual(result.citation_count, 1)


if __name__ == "__main__":
    unittest.main()
