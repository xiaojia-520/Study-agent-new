import unittest

import numpy as np

from src.application.speech.stream_processor import RealtimeSpeechStreamProcessor


class FakeDriver:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def on_start(self) -> None:
        self.calls.append("start")

    def on_chunk(self, chunk: np.ndarray) -> None:
        self.calls.append(("chunk", float(chunk[0])))

    def on_end(self) -> None:
        self.calls.append("end")


class RealtimeSpeechStreamProcessorTests(unittest.TestCase):
    def test_processes_vad_segment_in_order(self) -> None:
        driver = FakeDriver()
        processor = RealtimeSpeechStreamProcessor(driver_getter=lambda: driver)

        processor.start()
        processor.enqueue({"start": True}, np.array([1.0], dtype=np.float32), critical=True)
        processor.enqueue(None, np.array([2.0], dtype=np.float32))
        processor.enqueue({"end": True}, np.array([3.0], dtype=np.float32), critical=True)
        processor.stop()

        self.assertEqual(
            driver.calls,
            [
                "start",
                ("chunk", 1.0),
                ("chunk", 2.0),
                ("chunk", 3.0),
                "end",
            ],
        )

    def test_drops_non_critical_item_when_queue_is_full(self) -> None:
        driver = FakeDriver()
        processor = RealtimeSpeechStreamProcessor(driver_getter=lambda: driver, queue_size=1)

        self.assertTrue(
            processor.enqueue({"start": True}, np.array([1.0], dtype=np.float32), critical=True)
        )
        self.assertFalse(processor.enqueue(None, np.array([2.0], dtype=np.float32)))


if __name__ == "__main__":
    unittest.main()
