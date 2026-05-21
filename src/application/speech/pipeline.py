import threading
from typing import Optional

import numpy as np

from src.core.asr.realtime_drivers import RealtimeASRDriver, build_realtime_asr_driver
from src.core.asr.realtime_models import resolve_realtime_asr_model
from src.core.asr.transcriber import ASRTranscriber
from src.application.speech.stream_processor import RealtimeSpeechStreamProcessor
from src.core.audio.frame_slicer import FrameSlicer
from src.core.audio.recorder import AudioRecorder
from src.core.audio.vad_processor import VADProcessor
from src.infrastructure.audio import indata_to_mono_float32
from src.infrastructure.logger import get_logger

logger = get_logger("SpeechPipeline")


class _RealtimeSpeechPipelineBase:
    def __init__(self, *, model_key: Optional[str] = None, on_partial=None, on_final=None):
        self.vad = VADProcessor()
        self.slicer = FrameSlicer(window_size=512)
        self._driver_lock = threading.RLock()

        self._cb_in_speech = False

        self.chunk_size = [0, 20, 10]
        self.asr_stride = self.chunk_size[1] * 960
        self.tail_keep = int(0.4 * self.asr_stride)
        self.partial_log_interval = 0.25
        logger.info(
            "Realtime ASR window configured: chunk_size=%s stride=%.2fs tail=%.2fs",
            self.chunk_size,
            self.asr_stride / 16000,
            self.tail_keep / 16000,
        )

        self.on_partial = on_partial
        self.on_final = on_final

        self._current_model = resolve_realtime_asr_model(model_key)
        self.asr = ASRTranscriber(model_name=self._current_model.resolved_model_name)
        self._driver = self._build_driver()
        self._processor = RealtimeSpeechStreamProcessor(driver_getter=self._get_driver)

    def _build_driver(self) -> RealtimeASRDriver:
        return build_realtime_asr_driver(
            model=self._current_model,
            asr=self.asr,
            stride=self.asr_stride,
            tail_keep=self.tail_keep,
            partial_log_interval=self.partial_log_interval,
            on_partial=self.on_partial,
            on_final=self.on_final,
        )

    def _start_worker(self) -> None:
        self._processor.start()

    def _stop_worker(self) -> None:
        self._processor.stop()

    def _get_driver(self) -> RealtimeASRDriver:
        with self._driver_lock:
            return self._driver

    def set_asr_model(self, model_key: str) -> None:
        with self._driver_lock:
            self._current_model = resolve_realtime_asr_model(model_key)
            self._cb_in_speech = False
            self._processor.reset()
            self.asr = ASRTranscriber(model_name=self._current_model.resolved_model_name)
            self._driver = self._build_driver()

        logger.info(
            f"ASR model switched: key={self._current_model.key}, path={self._current_model.resolved_model_name}"
        )

    def feed_audio(self, audio: np.ndarray) -> None:
        if audio is None or audio.size == 0:
            return

        chunks = self.slicer.push(audio)

        for chunk in chunks:
            event = self.vad.process_frame(chunk)

            if isinstance(event, dict):
                if "start" in event:
                    self._cb_in_speech = True

                self._processor.enqueue(event, chunk, critical=True)

                if "end" in event:
                    self._cb_in_speech = False
            elif self._cb_in_speech:
                self._processor.enqueue(None, chunk, critical=False)


class SpeechPipeline(_RealtimeSpeechPipelineBase):
    def __init__(self, model_key: Optional[str] = None):
        self.recorder = AudioRecorder()
        super().__init__(model_key=model_key)

    def start(self) -> None:
        self._start_worker()
        self.recorder.start_stream(self._audio_callback)
        logger.info("Speech pipeline started")

    def stop(self) -> None:
        self.recorder.stop_stream()
        self._stop_worker()
        logger.info("Speech pipeline stopped")

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            logger.warning(f"Audio capture warning: {status}")

        need_scale = np.issubdtype(indata.dtype, np.integer)
        audio = indata_to_mono_float32(indata)

        if need_scale:
            audio = audio / 32768.0

        self.feed_audio(audio)


class WebSpeechPipeline(_RealtimeSpeechPipelineBase):
    def __init__(self, on_partial=None, on_final=None, model_name: Optional[str] = None):
        super().__init__(model_key=model_name, on_partial=on_partial, on_final=on_final)

    def start(self) -> None:
        self._start_worker()
        logger.info("WebSpeechPipeline started")

    def stop(self) -> None:
        self._stop_worker()
        logger.info("WebSpeechPipeline stopped")

    def feed_audio_bytes(self, audio_bytes: bytes) -> None:
        if not audio_bytes:
            return
        audio = np.frombuffer(audio_bytes, dtype=np.float32)
        self.feed_audio(audio)
