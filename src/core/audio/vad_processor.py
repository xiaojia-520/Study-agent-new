from typing import Optional

import numpy as np

from config.settings import settings
from src.infrastructure.logger import get_logger
from src.infrastructure.model_hub import model_hub

logger = get_logger("VADProcessor")


class VADProcessor:
    """Process fixed-size audio frames and return Silero VAD start/end events."""

    def __init__(self):
        self.sample_rate = settings.AUDIO_SAMPLE_RATE
        self.vad_threshold = settings.VAD_THRESHOLD
        self.vad_model: Optional[object] = None
        self.vad_iterator: Optional[object] = None
        self._is_initialized = False
        self._is_unavailable = False
        self._sample_rate: Optional[int] = None
        self._return_seconds: bool = True

    def _initialize_vad(self) -> None:
        if self._is_initialized:
            return
        if self._is_unavailable:
            return
        if self.vad_threshold is None:
            raise ValueError("VAD_THRESHOLD is not configured")
        if self.sample_rate is None:
            raise ValueError("AUDIO_SAMPLE_RATE is not configured")

        from silero_vad import VADIterator

        logger.info(f"Loading VAD model | threshold={self.vad_threshold}, sample_rate={self.sample_rate}")
        self.vad_model = model_hub.load_vad_model()
        self.vad_iterator = VADIterator(
            model=self.vad_model,
            threshold=self.vad_threshold,
            sampling_rate=self.sample_rate,
        )
        self._is_initialized = True

    @staticmethod
    def _prep_frame(frame) -> Optional[np.ndarray]:
        arr = np.asarray(frame, dtype=np.float32).squeeze()
        if arr.ndim != 1 or arr.size == 0:
            return None
        return arr

    def process_frame(self, frame):
        try:
            self._initialize_vad()
            if self.vad_iterator is None:
                return None

            frame_1d = self._prep_frame(frame)
            if frame_1d is None:
                return None

            event = self.vad_iterator(frame_1d, return_seconds=self._return_seconds)
            return event or None
        except Exception:
            self._is_unavailable = True
            logger.exception("VAD frame processing failed")
            return None

    def reset(self) -> None:
        if self.vad_iterator is not None:
            self.vad_iterator.reset_states()

    def close(self) -> None:
        if self.vad_iterator is not None:
            self.vad_iterator.reset_states()

        self.vad_model = None
        self.vad_iterator = None
        self._sample_rate = None
        self._is_initialized = False
        self._is_unavailable = False
        logger.info("VAD resources released")


vad_processor = VADProcessor()
