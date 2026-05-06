import time
import unittest
from io import BytesIO
from threading import Event

from PIL import Image

from src.domain.session import RealtimeSession
from web.backend.app.services.session_vision_service import LocalPaddleOcrExtractor, SessionVisionService


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
        return "slow vision result"


class EmptyJsonResult:
    def json(self):
        raise RuntimeError(
            "[json.exception.parse_error.101] parse error at line 1, column 1: "
            "attempting to parse an empty input; check that your input string or stream contains the expected JSON"
        )

    def to_dict(self):
        return {"rec_texts": ["PPT title", "Key points"]}


class PredictFailsEngine:
    def predict(self, array):
        raise RuntimeError(
            "[json.exception.parse_error.101] parse error at line 1, column 1: "
            "attempting to parse an empty input; check that your input string or stream contains the expected JSON"
        )

    def ocr(self, array, cls=False):
        return [{"rec_texts": ["fallback result"]}]


class PredictEmptyOnlyEngine:
    def predict(self, array):
        raise RuntimeError(
            "[json.exception.parse_error.101] parse error at line 1, column 1: "
            "attempting to parse an empty input; check that your input string or stream contains the expected JSON"
        )

    def ocr(self, array, cls=False):
        raise RuntimeError(
            "[json.exception.parse_error.101] parse error at line 1, column 1: "
            "attempting to parse an empty input; check that your input string or stream contains the expected JSON"
        )


class SessionVisionServiceTests(unittest.TestCase):
    def test_process_frame_indexes_ppt_and_blackboard_regions(self) -> None:
        writer = FakeTranscriptWriter()
        indexer = FakeRagIndexer()
        refine_calls = []
        service = SessionVisionService(
            ocr_extractor=FakeExtractor("PPT title\nknowledge point"),
            vlm_extractor=FakeExtractor("blackboard formula y = kx + b"),
            transcript_writer=writer,
            rag_indexer=indexer,
            refine_scheduler=lambda session_id: refine_calls.append(session_id),
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
        self.assertIn("PPT title", writer.records[0]["clean_text"])
        self.assertEqual(writer.records[1]["metadata"]["region"], "blackboard")
        self.assertIn("blackboard formula", writer.records[1]["clean_text"])
        self.assertEqual(len(indexer.records), 2)
        self.assertEqual(refine_calls, ["session-vision"])

    def test_duplicate_region_text_is_skipped(self) -> None:
        writer = FakeTranscriptWriter()
        refine_calls = []
        service = SessionVisionService(
            ocr_extractor=FakeExtractor("duplicate PPT"),
            vlm_extractor=FakeExtractor(""),
            transcript_writer=writer,
            rag_indexer=FakeRagIndexer(),
            refine_scheduler=lambda session_id: refine_calls.append(session_id),
        )
        session = self._session()
        regions = {"ppt": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}}

        first = service.process_frame(session=session, image_bytes=self._image_bytes(), regions=regions)
        second = service.process_frame(session=session, image_bytes=self._image_bytes(), regions=regions)

        self.assertEqual(first["results"][0]["status"], "indexed")
        self.assertEqual(second["results"][0]["status"], "duplicate")
        self.assertEqual(len(writer.records), 1)
        self.assertEqual(refine_calls, ["session-vision"])

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

    def test_local_paddle_ocr_ignores_empty_json_result_payload(self) -> None:
        extractor = LocalPaddleOcrExtractor()
        extractor._engine = type("FakeEngine", (), {"predict": lambda self, array: [EmptyJsonResult()]})()

        text = extractor.extract_text(Image.new("RGB", (64, 64), color=(255, 255, 255)))

        self.assertEqual(text, "PPT title\nKey points")

    def test_local_paddle_ocr_falls_back_to_ocr_when_predict_fails(self) -> None:
        extractor = LocalPaddleOcrExtractor()
        extractor._engine = PredictFailsEngine()

        text = extractor.extract_text(Image.new("RGB", (64, 64), color=(255, 255, 255)))

        self.assertEqual(text, "fallback result")

    def test_local_paddle_ocr_treats_empty_json_parse_error_as_empty_text(self) -> None:
        extractor = LocalPaddleOcrExtractor()
        extractor._engine = PredictEmptyOnlyEngine()

        text = extractor.extract_text(Image.new("RGB", (64, 64), color=(255, 255, 255)))

        self.assertEqual(text, "")

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
