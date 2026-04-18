import time
import unittest
from unittest.mock import patch

from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.realtime_speech_service import RealtimeSpeechService


class FakeSender:
    def __init__(self):
        self.calls = []

    def __call__(self, event_type: str, text: str, *, is_final: bool) -> None:
        self.calls.append((event_type, text, is_final))


class RealtimeSpeechServiceTests(unittest.TestCase):
    def test_handle_final_transcript_persists_and_enqueues_rag_record(self) -> None:
        service = RealtimeSpeechService()
        sender = FakeSender()
        session = RealtimeSession(
            session_id="session-final",
            course_id="math-course",
            lesson_id="math-course-lesson-1",
            subject="math",
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        persisted_record = {
            "session_id": "session-final",
            "storage_id": "20260418_math_session-final",
            "course_id": "math-course",
            "lesson_id": "math-course-lesson-1",
            "chunk_id": 1,
            "subject": "math",
            "source_type": "realtime",
            "text": "final text",
            "clean_text": "final text",
            "created_at": 123,
        }

        with (
            patch("web.backend.app.services.realtime_speech_service.session_manager.get_session", return_value=session),
            patch(
                "web.backend.app.services.realtime_speech_service.transcript_service.append_realtime_transcript",
                return_value=persisted_record,
            ) as append_mock,
            patch(
                "web.backend.app.services.realtime_speech_service.realtime_rag_indexer.append_record"
            ) as enqueue_mock,
        ):
            service._handle_final_transcript("session-final", sender, "final text")

        self.assertEqual(sender.calls, [("final_transcript", "final text", True)])
        append_mock.assert_called_once_with(session, "final text")
        enqueue_mock.assert_called_once_with(session, persisted_record)

    def test_shutdown_session_flushes_rag_tail(self) -> None:
        service = RealtimeSpeechService()

        class FakePipeline:
            def __init__(self) -> None:
                self.stopped = False

            def stop(self) -> None:
                self.stopped = True

        pipeline = FakePipeline()
        session = RealtimeSession(
            session_id="session-stop",
            course_id="math-course",
            lesson_id="math-course-lesson-1",
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )

        with (
            patch("web.backend.app.services.realtime_speech_service.realtime_rag_indexer.flush_session") as flush_mock,
            patch("web.backend.app.services.realtime_speech_service.transcript_service.release_session") as release_mock,
            patch(
                "web.backend.app.services.realtime_speech_service.session_manager.mark_disconnected",
                return_value=session,
            ),
            patch(
                "web.backend.app.services.realtime_speech_service.session_manager.next_event_seq",
                return_value=1,
            ),
        ):
            payload = self._run_async(service.shutdown_session("session-stop", pipeline))

        self.assertTrue(pipeline.stopped)
        flush_mock.assert_called_once_with("session-stop")
        release_mock.assert_called_once_with("session-stop")
        self.assertEqual(payload["type"], "session_stopped")

    @staticmethod
    def _run_async(awaitable):
        import asyncio

        return asyncio.run(awaitable)


if __name__ == "__main__":
    unittest.main()
