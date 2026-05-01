from __future__ import annotations

import queue
import threading
from typing import Callable

import numpy as np

from src.core.asr.realtime_drivers import RealtimeASRDriver

SpeechEvent = dict[str, object] | None
SpeechFrameItem = tuple[SpeechEvent, np.ndarray] | None


class RealtimeSpeechStreamProcessor:
    """Run VAD-delimited audio chunks through the active ASR driver."""

    def __init__(
        self,
        *,
        driver_getter: Callable[[], RealtimeASRDriver],
        queue_size: int = 2000,
    ) -> None:
        self.driver_getter = driver_getter
        self.q: queue.Queue[SpeechFrameItem] = queue.Queue(maxsize=queue_size)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._in_speech = False

    def start(self) -> None:
        self._stop_event.clear()
        if not self._worker.is_alive():
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        try:
            self.q.put(None, timeout=0.5)
        except queue.Full:
            pass

        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

    def reset(self) -> None:
        self._in_speech = False
        self.drain()

    def drain(self) -> None:
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def enqueue(self, event: SpeechEvent, chunk: np.ndarray, *, critical: bool = False) -> bool:
        item: SpeechFrameItem = (event, chunk)
        try:
            self.q.put_nowait(item)
            return True
        except queue.Full:
            if not critical:
                return False
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(item)
                return True
            except queue.Full:
                return False

    def _worker_loop(self) -> None:
        while True:
            item = self.q.get()
            if item is None:
                break

            event, chunk = item
            end_now = False
            driver = self.driver_getter()

            if isinstance(event, dict):
                if "start" in event:
                    self._in_speech = True
                    driver.on_start()
                if "end" in event:
                    end_now = True

            if not self._in_speech:
                continue

            driver.on_chunk(chunk)

            if end_now:
                driver.on_end()
                self._in_speech = False
