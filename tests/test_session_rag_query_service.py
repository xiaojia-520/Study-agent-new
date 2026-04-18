import unittest
from types import SimpleNamespace

from src.core.knowledge.document_models import SearchResult
from src.core.knowledge.query_filters import MetadataFilterSpec
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_rag_query_service import QueryScope, SessionRagQueryService


class FakeQueryService:
    def __init__(self, results: list[SearchResult]):
        self.results = results
        self.calls = []

    def search(self, query_text: str, **kwargs):
        self.calls.append((query_text, dict(kwargs)))
        return list(self.results)


class FakeLLM:
    def __init__(self, text: str):
        self.text = text
        self.prompts = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.text)


class FailingLLM:
    def complete(self, prompt: str):
        raise RuntimeError("upstream llm timeout")


class SessionRagQueryServiceTests(unittest.TestCase):
    def test_infer_scope_matches_rule_based_phrases(self) -> None:
        service = SessionRagQueryService(runtime_factory=lambda: None, session_getter=lambda _: None)

        self.assertEqual(service.infer_scope("just now what did the teacher define"), QueryScope.CURRENT_LESSON)
        self.assertEqual(service.infer_scope("have we covered limits before"), QueryScope.COURSE_HISTORY)
        self.assertEqual(service.infer_scope("throughout the course where was this mentioned"), QueryScope.COURSE_ALL)
        self.assertEqual(service.infer_scope("search the global knowledge base"), QueryScope.GLOBAL)

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

    def test_query_session_retrieval_only_returns_citations(self) -> None:
        fake_query_service = FakeQueryService(
            [
                SearchResult(
                    doc_id="doc-1",
                    content="Limit means the value a function approaches.",
                    score=0.91,
                    session_id="session-a",
                    subject="math",
                    source_type="realtime",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-1"},
                )
            ]
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=7),
            embed_model=object(),
            llm=None,
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

        self.assertEqual(fake_query_service.calls[0][0], "what is a limit")
        self.assertEqual(fake_query_service.calls[0][1]["top_k"], 7)
        self.assertIs(fake_query_service.calls[0][1]["embed_model"], runtime.embed_model)
        filters = fake_query_service.calls[0][1]["filters"]
        self.assertIsInstance(filters, MetadataFilterSpec)
        self.assertIsNone(answer.answer)
        self.assertEqual(answer.metadata["answer_strategy"], "retrieval_only")
        self.assertEqual(answer.metadata["scope"], "current_lesson")
        self.assertEqual(answer.metadata["course_id"], "math-course")
        self.assertEqual(answer.metadata["lesson_id"], "math-course-lesson-1")
        self.assertEqual(answer.metadata["requested_scope"], "current_lesson")
        self.assertEqual(answer.metadata["scope_source"], "explicit")
        self.assertEqual(answer.metadata["citation_count"], 1)
        self.assertEqual(len(answer.citations), 1)
        self.assertEqual(answer.citations[0].index, 1)
        self.assertEqual(answer.citations[0].doc_id, "doc-1")

    def test_query_session_resolves_auto_scope_via_rules(self) -> None:
        fake_query_service = FakeQueryService(
            [
                SearchResult(
                    doc_id="doc-2",
                    content="This was covered in a previous lesson.",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-0"},
                )
            ]
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=4),
            embed_model=object(),
            llm=None,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="have we covered limits before",
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

    def test_query_session_uses_custom_prompt_for_llm_answer(self) -> None:
        fake_query_service = FakeQueryService(
            [
                SearchResult(
                    doc_id="doc-1",
                    content="A limit describes the value a function approaches near a point.",
                    score=0.95,
                    session_id="session-a",
                    subject="math",
                    source_type="realtime",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-1"},
                ),
                SearchResult(
                    doc_id="doc-2",
                    content="Teachers often introduce notation together with the definition.",
                    score=0.82,
                    session_id="session-a",
                    subject="math",
                    source_type="realtime",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-1"},
                ),
            ]
        )
        fake_llm = FakeLLM("A limit is the value a function approaches near a point [1].")
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=fake_llm,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="What is a limit?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        self.assertEqual(answer.answer, "A limit is the value a function approaches near a point [1].")
        self.assertEqual(answer.metadata["answer_strategy"], "llm_synthesized")
        self.assertTrue(answer.metadata["llm_used"])
        self.assertFalse(answer.metadata["llm_fallback"])
        self.assertEqual(len(answer.citations), 2)
        self.assertIn("Question: What is a limit?", fake_llm.prompts[0])
        self.assertIn("[1] doc_id=doc-1", fake_llm.prompts[0])
        self.assertIn("[2] doc_id=doc-2", fake_llm.prompts[0])

    def test_query_session_falls_back_when_llm_synthesis_fails(self) -> None:
        fake_query_service = FakeQueryService(
            [
                SearchResult(
                    doc_id="doc-1",
                    content="The transcript mentions limits in the current lesson.",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-1"},
                )
            ]
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=FailingLLM(),
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="What did the lesson say about limits?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        self.assertIsNone(answer.answer)
        self.assertEqual(answer.metadata["answer_strategy"], "retrieval_fallback")
        self.assertTrue(answer.metadata["llm_fallback"])
        self.assertFalse(answer.metadata["llm_used"])
        self.assertEqual(answer.metadata["llm_error"], "upstream llm timeout")
        self.assertEqual(len(answer.results), 1)
        self.assertEqual(len(answer.citations), 1)

    def test_query_session_rejects_llm_mode_when_runtime_has_no_llm(self) -> None:
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=None,
            query_service=FakeQueryService([]),
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
