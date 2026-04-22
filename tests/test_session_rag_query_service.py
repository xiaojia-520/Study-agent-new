import unittest
from types import SimpleNamespace

from src.core.knowledge.document_models import SearchResult
from src.core.knowledge.query_filters import MetadataFilterSpec
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.chat_memory_service import ChatMemoryTurn
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


class FakeChatMemoryService:
    def __init__(self, turns: list[ChatMemoryTurn] | None = None) -> None:
        self.turns = list(turns or [])
        self.appended = []
        self.lesson_calls = []

    def list_recent_turns(self, session_id: str, *, limit: int = 6):
        return self.turns[-limit:]

    def list_recent_lesson_turns(self, *, course_id: str, lesson_id: str, limit: int = 6):
        self.lesson_calls.append({"course_id": course_id, "lesson_id": lesson_id, "limit": limit})
        return self.turns[-limit:]

    def append_turn(self, *, session, user_text: str, assistant_text: str | None, answer_metadata=None) -> None:
        self.appended.append(
            {
                "session_id": session.session_id,
                "user_text": user_text,
                "assistant_text": assistant_text,
                "answer_metadata": dict(answer_metadata or {}),
            }
        )
        self.turns.append(ChatMemoryTurn(user=user_text, assistant=assistant_text, created_at=999))


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

    def test_query_session_includes_recent_transcripts_in_llm_prompt(self) -> None:
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
                )
            ]
        )
        fake_llm = FakeLLM("A limit is the value a function approaches near a point [1].")
        transcript_items = [
            self._transcript_item(chunk_id=1, text="Old warmup transcript."),
            self._transcript_item(chunk_id=2, text="Recent context one."),
            self._transcript_item(chunk_id=3, text="Recent context two."),
            self._transcript_item(chunk_id=4, text="Recent context three."),
        ]
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=fake_llm,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: transcript_items,
            recent_transcript_limit=3,
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="What is a limit?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        prompt = fake_llm.prompts[0]
        self.assertEqual(answer.metadata["recent_transcript_count"], 3)
        self.assertIn("Recent transcript context:", prompt)
        self.assertNotIn("Old warmup transcript.", prompt)
        self.assertIn("R1. Recent context one.", prompt)
        self.assertIn("R2. Recent context two.", prompt)
        self.assertIn("R3. Recent context three.", prompt)

    def test_query_session_can_use_recent_transcripts_when_retrieval_has_no_results(self) -> None:
        fake_query_service = FakeQueryService([])
        fake_llm = FakeLLM("Based on the recent transcript, limits were introduced as approach values.")
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=fake_llm,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: [
                self._transcript_item(chunk_id=1, text="Limits were introduced as approach values.")
            ],
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="What did we just introduce?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        self.assertEqual(answer.answer, "Based on the recent transcript, limits were introduced as approach values.")
        self.assertEqual(answer.metadata["answer_strategy"], "llm_synthesized")
        self.assertEqual(answer.metadata["citation_count"], 0)
        self.assertEqual(answer.metadata["recent_transcript_count"], 1)
        self.assertIn("[no context retrieved]", fake_llm.prompts[0])
        self.assertIn("R1. Limits were introduced as approach values.", fake_llm.prompts[0])

    def test_query_session_uses_conversation_memory_for_follow_up(self) -> None:
        fake_query_service = FakeQueryService(
            [
                SearchResult(
                    doc_id="doc-1",
                    content="A limit describes approach behavior; a derivative describes instantaneous rate.",
                    score=0.91,
                    session_id="session-a",
                    subject="math",
                    source_type="realtime",
                    metadata={"course_id": "math-course", "lesson_id": "math-course-lesson-1"},
                )
            ]
        )
        fake_llm = FakeLLM("The derivative is about instantaneous rate, while the limit is about approach [1].")
        fake_memory = FakeChatMemoryService(
            [
                ChatMemoryTurn(
                    user="What is a limit?",
                    assistant="A limit describes the value a function approaches.",
                    created_at=100,
                )
            ]
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=fake_llm,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
            memory_service=fake_memory,
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="How is that different from a derivative?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        search_query = fake_query_service.calls[0][0]
        prompt = fake_llm.prompts[0]
        self.assertIn("Previous question: What is a limit?", search_query)
        self.assertIn("Previous answer: A limit describes the value a function approaches.", search_query)
        self.assertIn("Current question:\nHow is that different from a derivative?", search_query)
        self.assertIn("Conversation history:", prompt)
        self.assertIn("User: What is a limit?", prompt)
        self.assertIn("Assistant: A limit describes the value a function approaches.", prompt)
        self.assertEqual(
            fake_memory.lesson_calls[0],
            {"course_id": "math-course", "lesson_id": "math-course-lesson-1", "limit": 6},
        )
        self.assertEqual(answer.metadata["memory_turn_count"], 1)
        self.assertEqual(answer.metadata["memory_scope"], "lesson")
        self.assertEqual(answer.metadata["answer_prompt_version"], "cited-answer-v3")
        self.assertEqual(fake_memory.appended[0]["user_text"], "How is that different from a derivative?")
        self.assertEqual(
            fake_memory.appended[0]["assistant_text"],
            "The derivative is about instantaneous rate, while the limit is about approach [1].",
        )

    def test_query_session_can_answer_from_conversation_memory_without_retrieval(self) -> None:
        fake_query_service = FakeQueryService([])
        fake_llm = FakeLLM("It refers to the limit we discussed in the previous turn.")
        fake_memory = FakeChatMemoryService(
            [
                ChatMemoryTurn(
                    user="What is a limit?",
                    assistant="A limit describes the value a function approaches.",
                    created_at=100,
                )
            ]
        )
        runtime = SimpleNamespace(
            config=SimpleNamespace(top_k=5),
            embed_model=object(),
            llm=fake_llm,
            query_service=fake_query_service,
        )
        service = SessionRagQueryService(
            runtime_factory=lambda: runtime,
            session_getter=lambda _: self._session(),
            transcript_loader=lambda session, session_id: [],
            memory_service=fake_memory,
        )

        answer = service.query_session(
            session_id="session-a",
            query_text="What does that refer to?",
            scope=QueryScope.CURRENT_LESSON,
            with_llm=True,
        )

        self.assertEqual(answer.answer, "It refers to the limit we discussed in the previous turn.")
        self.assertEqual(answer.metadata["answer_strategy"], "llm_synthesized")
        self.assertEqual(answer.metadata["citation_count"], 0)
        self.assertEqual(answer.metadata["recent_transcript_count"], 0)
        self.assertEqual(answer.metadata["memory_turn_count"], 1)
        self.assertIn("[no context retrieved]", fake_llm.prompts[0])
        self.assertIn("User: What is a limit?", fake_llm.prompts[0])

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

    @staticmethod
    def _transcript_item(*, chunk_id: int, text: str) -> dict[str, object]:
        return {
            "session_id": "session-a",
            "storage_id": "session-a-store",
            "course_id": "math-course",
            "lesson_id": "math-course-lesson-1",
            "chunk_id": chunk_id,
            "subject": "math",
            "source_type": "realtime",
            "source_file": None,
            "start_ms": None,
            "end_ms": None,
            "text": text,
            "clean_text": text,
            "created_at": 100 + chunk_id,
        }


if __name__ == "__main__":
    unittest.main()
