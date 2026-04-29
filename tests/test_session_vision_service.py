import time
import unittest
from io import BytesIO
from threading import Event

from PIL import Image

from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_vision_service import SessionVisionService


class FakeExtractor:
    def __init__(self, text: str):
        self.text = text
        self.calls = []

    def extract_text(self, image):
        self.calls.append(image.size)
        return self.text


class FakeTranscriptWriter:
    def __init__(self):
        self.records = []

    def next_chunk_id(self, session_id: str) -> int:
        return 10

    def append_transcript_record(self, record):
        self.records.append(dict(record))
        return len(self.records)


class FakeRagIndexer:
    def __init__(self):
        self.records = []

    def append_record(self, session, record):
        self.records.append((session, dict(record)))


class BlockingExtractor:
    def __init__(self):
        self.started = Event()
        self.release = Event()

    def extract_text(self, image):
        self.started.set()
        self.release.wait(timeout=2.0)
        return "慢速视觉结果"


class SessionVisionServiceTests(unittest.TestCase):
    def test_process_frame_indexes_ppt_and_blackboard_regions(self) -> None:
        writer = FakeTranscriptWriter()
        indexer = FakeRagIndexer()
        service = SessionVisionService(
            ocr_extractor=FakeExtractor("PPT标题\n知识点A"),
            vlm_extractor=FakeExtractor("黑板公式 y = kx + b"),
            transcript_writer=writer,
            rag_indexer=indexer,
        )

        response = service.process_frame(
            session=self._session(),
            image_bytes=self._image_bytes(),
            regions={
                "ppt": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0},
                "blackboard": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0},
            },
            timestamp_ms=1234,
            captured_at_ms=5000,
        )

        self.assertEqual(response["record_count"], 2)
        self.assertEqual([item["status"] for item in response["results"]], ["indexed", "indexed"])
        self.assertEqual([record["chunk_id"] for record in writer.records], [10, 11])
        self.assertEqual(writer.records[0]["source_type"], "video")
        self.assertEqual(writer.records[0]["metadata"]["region"], "ppt")
        self.assertEqual(writer.records[0]["created_at"], 5)
        self.assertEqual(writer.records[0]["metadata"]["frame_captured_at_ms"], 5000)
        self.assertIn("PPT标题", writer.records[0]["clean_text"])
        self.assertEqual(writer.records[1]["metadata"]["region"], "blackboard")
        self.assertIn("黑板公式", writer.records[1]["clean_text"])
        self.assertEqual(len(indexer.records), 2)

    def test_duplicate_region_text_is_skipped(self) -> None:
        writer = FakeTranscriptWriter()
        service = SessionVisionService(
            ocr_extractor=FakeExtractor("重复PPT"),
            vlm_extractor=FakeExtractor(""),
            transcript_writer=writer,
            rag_indexer=FakeRagIndexer(),
        )
        session = self._session()
        regions = {"ppt": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}}

        first = service.process_frame(session=session, image_bytes=self._image_bytes(), regions=regions)
        second = service.process_frame(session=session, image_bytes=self._image_bytes(), regions=regions)

        self.assertEqual(first["results"][0]["status"], "indexed")
        self.assertEqual(second["results"][0]["status"], "duplicate")
        self.assertEqual(len(writer.records), 1)

    def test_busy_frame_is_skipped_without_waiting(self) -> None:
        extractor = BlockingExtractor()
        service = SessionVisionService(
            ocr_extractor=extractor,
            vlm_extractor=FakeExtractor(""),
            transcript_writer=FakeTranscriptWriter(),
            rag_indexer=FakeRagIndexer(),
        )
        session = self._session()
        regions = {"ppt": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}}

        import threading

        worker = threading.Thread(
            target=lambda: service.process_frame(
                session=session,
                image_bytes=self._image_bytes(),
                regions=regions,
            )
        )
        worker.start()
        self.assertTrue(extractor.started.wait(timeout=1.0))

        busy = service.process_frame(
            session=session,
            image_bytes=self._image_bytes(),
            regions=regions,
        )

        extractor.release.set()
        worker.join(timeout=2.0)
        self.assertTrue(busy["busy"])
        self.assertEqual(busy["results"][0]["status"], "busy")

    @staticmethod
    def _session() -> RealtimeSession:
        now = int(time.time())
        return RealtimeSession(
            session_id="session-vision",
            course_id="course-a",
            lesson_id="lesson-a",
            subject="vision lesson",
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    def _image_bytes() -> bytes:
        image = Image.new("RGB", (640, 360), color=(240, 240, 240))
        buffer = BytesIO()
        image.save(buffer, format="JPEG")
        return buffer.getvalue()


if __name__ == "__main__":
    unittest.main()
