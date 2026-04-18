import unittest
from types import SimpleNamespace

from src.core.knowledge.document_models import KnowledgeAnswer, SearchResult
from src.core.knowledge.query_filters import MetadataFilterSpec
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_rag_query_service import QueryScope, SessionRagQueryService


class FakeQueryService:
    def __init__(self, response: KnowledgeAnswer):
        self.response = response
        self.calls = []

    def query(self, query_text: str, **kwargs) -> KnowledgeAnswer:
        self.calls.append((query_text, dict(kwargs)))
        return self.response


class SessionRagQueryServiceTests(unittest.TestCase):
    def test_infer_scope_matches_rule_based_phrases(self) -> None:
        service = SessionRagQueryService(runtime_factory=lambda: None, session_getter=lambda _: None)

        self.assertEqual(service.infer_scope("刚才老师怎么定义极限"), QueryScope.CURRENT_LESSON)
        self.assertEqual(service.infer_scope("之前有没有讲过极限定义"), QueryScope.COURSE_HISTORY)
        self.assertEqual(service.infer_scope("这门课里哪里还提过极限"), QueryScope.COURSE_ALL)
        self.assertEqual(service.infer_scope("别的课有没有讲过极限"), QueryScope.GLOBAL)

    def test_build_scope_filters_translates_query_scope(self) -> None:
        service = SessionRagQueryService(runtime_factory=lambda: None, session_getter=lambda _: None)
        session = self._session()

        current = service.build_scope_filters(session, QueryScope.CURRENT_LESSON)
        history = service.build_scope_filters(session, QueryScope.COURSE_HISTORY)
        course_all = service.build_scope_filters(session, QueryScope.COURSE_ALL)

        self.assertIsInstance(current, MetadataFilterSpec)
        self.assertEqual([(clause.key, clause.value, clause.operator) for clause in current.clauses], [
            ("lesson_id", "math-course-lesson-1", "eq"),
        ])
        self.assertEqual([(clause.key, clause.value, clause.operator) for clause in history.clauses], [
            ("course_id", "math-course", "eq"),
            ("lesson_id", "math-course-lesson-1", "ne"),
        ])
        self.assertEqual([(clause.key, clause.value, clause.operator) for clause in course_all.clauses], [
            ("course_id", "math-course", "eq"),
        ])
        self.assertIsNone(service.build_scope_filters(session, QueryScope.GLOBAL))
        with self.assertRaisesRegex(ValueError, "must be resolved"):
            service.build_scope_filters(session, QueryScope.AUTO)

    def test_query_session_uses_scope_filters_and_default_top_k(self) -> None:
        fake_answer = KnowledgeAnswer(
            query="what is a limit",
            answer=None,
            results=[SearchResult(doc_id="doc-1", content="limit definition")],
            metadata={"mode": "retrieval"},
        )
        fake_query_service = FakeQueryService(fake_answer)
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=7),
            embed_model=object(),
            llm=object(),
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        answer = service.query_session(
            session_id="session-a",
            query_text=" what is a limit ",
            scope=QueryScope.CURRENT_LESSON,
        )

        self.assertEqual(fake_query_service.calls[0][0], " what is a limit ")
        self.assertEqual(fake_query_service.calls[0][1]["top_k"], 7)
        self.assertIs(fake_query_service.calls[0][1]["embed_model"], runtime.embed_model)
        self.assertIsNone(fake_query_service.calls[0][1]["llm"])
        filters = fake_query_service.calls[0][1]["filters"]
        self.assertIsInstance(filters, MetadataFilterSpec)
        self.assertEqual(answer.metadata["scope"], "current_lesson")
        self.assertEqual(answer.metadata["course_id"], "math-course")
        self.assertEqual(answer.metadata["lesson_id"], "math-course-lesson-1")
        self.assertEqual(answer.metadata["requested_scope"], "current_lesson")
        self.assertEqual(answer.metadata["scope_source"], "explicit")

    def test_query_session_resolves_auto_scope_via_rules(self) -> None:
        fake_answer = KnowledgeAnswer(
            query="之前有没有讲过极限定义",
            answer=None,
            results=[SearchResult(doc_id="doc-2", content="history result")],
        )
        fake_query_service = FakeQueryService(fake_answer)
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=4),
            embed_model=object(),
            llm=object(),
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="之前有没有讲过极限定义",
            scope=QueryScope.AUTO,
        )

        filters = fake_query_service.calls[0][1]["filters"]
        self.assertIsInstance(filters, MetadataFilterSpec)
        self.assertEqual([(clause.key, clause.value, clause.operator) for clause in filters.clauses], [
            ("course_id", "math-course", "eq"),
            ("lesson_id", "math-course-lesson-1", "ne"),
        ])
        self.assertEqual(answer.metadata["requested_scope"], "auto")
        self.assertEqual(answer.metadata["scope"], "course_history")
        self.assertEqual(answer.metadata["scope_source"], "rule")

    def test_query_session_rejects_llm_mode_when_runtime_has_no_llm(self) -> None:
        fake_answer = KnowledgeAnswer(query="q", answer=None, results=[])
        fake_query_service = FakeQueryService(fake_answer)
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=None,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        with self.assertRaisesRegex(ValueError, "LLM is not enabled"):
            service.query_session(
                session_id="session-a",
                query_text="question",
                scope=QueryScope.CURRENT_LESSON,
                with_llm=True,
            )

    @staticmethod
    def _session() -> RealtimeSession:
        return RealtimeSession(
            session_id="session-a",
            course_id="math-course",
            lesson_id="math-course-lesson-1",
            subject="math",
            created_at=100,
            updated_at=100,
        )


if __name__ == "__main__":
    unittest.main()
