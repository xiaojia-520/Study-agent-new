import time
import unittest
from unittest.mock import patch

import numpy as np

from src.domain.session import RealtimeSession
from src.application.live_classroom.realtime_speech_service import RealtimeSpeechService
from src.application.speech.asr_gateway import AsrSessionHandle


class FakeSender:
    def __init__(self):
        self.calls = []

    def __call__(self, event_type: str, text: str, *, is_final: bool) -> None:
        self.calls.append((event_type, text, is_final))


class RealtimeSpeechServiceTests(unittest.TestCase):
    def test_process_audio_message_delegates_audio_to_asr_gateway(self) -> None:
        class FakeGateway:
            def __init__(self) -> None:
                self.calls = []

            def push_audio(self, handle, audio_bytes: bytes) -> None:
                self.calls.append((handle, audio_bytes))

            def close(self) -> None:
                pass

        gateway = FakeGateway()
        service = RealtimeSpeechService(asr_gateway=gateway)
        handle = AsrSessionHandle(session_id="session-audio")
        audio_bytes = np.array([0.25, -0.5], dtype=np.float32).tobytes()

        with (
            patch("src.application.live_classroom.realtime_speech_service.session_manager.mark_running"),
            patch("src.application.live_classroom.realtime_speech_service.session_manager.next_event_seq", return_value=7),
        ):
            last_metrics_at, metrics_payload = self._run_async(
                service.process_audio_message(
                    session_id="session-audio",
                    audio_bytes=audio_bytes,
                    pipeline=handle,
                    last_metrics_at=0.0,
                )
            )

        self.assertGreater(last_metrics_at, 0.0)
        self.assertIsNotNone(metrics_payload)
        self.assertEqual(metrics_payload["type"], "audio_metrics")
        self.assertEqual(gateway.calls, [(handle, audio_bytes)])

    def test_get_asr_status_delegates_to_gateway(self) -> None:
        class FakeGateway:
            def status(self) -> dict[str, object]:
                return {"backend": "fake", "healthy": True}

            def close(self) -> None:
                pass

        service = RealtimeSpeechService(asr_gateway=FakeGateway())

        payload = self._run_async(service.get_asr_status())

        self.assertEqual(payload["backend"], "fake")
        self.assertTrue(payload["healthy"])

    def test_handle_final_transcript_delegates_to_knowledge_ingestion(self) -> None:
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
            patch("src.application.live_classroom.realtime_speech_service.session_manager.get_session", return_value=session),
            patch(
                "src.application.live_classroom.realtime_speech_service.knowledge_ingestion_service.append_realtime_transcript",
                return_value=persisted_record,
            ) as append_mock,
        ):
            service._handle_final_transcript("session-final", sender, "final text")

        self.assertEqual(sender.calls, [("final_transcript", "final text", True)])
        append_mock.assert_called_once_with(session, "final text")

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
            patch("src.application.live_classroom.realtime_speech_service.knowledge_ingestion_service.flush_session") as flush_mock,
            patch("src.application.live_classroom.realtime_speech_service.knowledge_ingestion_service.release_session") as release_mock,
            patch(
                "src.application.live_classroom.realtime_speech_service.session_manager.mark_disconnected",
                return_value=session,
            ),
            patch(
                "src.application.live_classroom.realtime_speech_service.session_manager.next_event_seq",
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
