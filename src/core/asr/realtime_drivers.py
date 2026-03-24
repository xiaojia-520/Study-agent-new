from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Callable, Protocol

import numpy as np

from src.core.asr.realtime_models import RealtimeASRModel
from src.infrastructure.logger import get_logger

if TYPE_CHECKING:
    from src.core.asr.transcriber import ASRTranscriber

logger = get_logger("RealtimeASRDriver")

TextCallback = Callable[[str], None] | None


class ASRLike(Protocol):
    def reset_stream(self) -> None: ...

    def transcribe_offline(self, audio_data: np.ndarray) -> str: ...

    def transcribe_offline_with_punc(self, audio_data: np.ndarray) -> str: ...

    def transcribe_stream(self, speech_chunk: np.ndarray, is_final: bool = False) -> str: ...


class AudioChunkBuffer:
    def __init__(self) -> None:
        self._chunks = deque()
        self._head_offset = 0
        self._size = 0

    @property
    def size(self) -> int:
        return self._size

    def clear(self) -> None:
        self._chunks.clear()
        self._head_offset = 0
        self._size = 0

    def append(self, chunk: np.ndarray) -> None:
        arr = np.asarray(chunk, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            return
        self._chunks.append(arr)
        self._size += arr.size

    def pop(self, n: int) -> np.ndarray:
        if n <= 0 or self._size <= 0:
            return np.zeros((0,), dtype=np.float32)

        n = min(n, self._size)
        out = np.empty((n,), dtype=np.float32)
        filled = 0

        while filled < n:
            head = self._chunks[0]
            remain = head.size - self._head_offset
            take = min(n - filled, remain)

            out[filled:filled + take] = head[self._head_offset:self._head_offset + take]
            filled += take
            self._head_offset += take

            if self._head_offset >= head.size:
                self._chunks.popleft()
                self._head_offset = 0

        self._size -= n
        return out

    def pop_all(self) -> np.ndarray:
        return self.pop(self._size)


class RealtimeASRDriver:
    def on_start(self) -> None:
        raise NotImplementedError

    def on_chunk(self, chunk: np.ndarray) -> None:
        raise NotImplementedError

    def on_end(self) -> None:
        raise NotImplementedError


class ParaformerZhDriver(RealtimeASRDriver):
    def __init__(self, asr: ASRLike, on_final: TextCallback = None) -> None:
        self.asr = asr
        self.on_final = on_final
        self.buf = AudioChunkBuffer()

    def on_start(self) -> None:
        self.buf.clear()
        logger.info("VAD start -> paraformer-zh")

    def on_chunk(self, chunk: np.ndarray) -> None:
        self.buf.append(chunk)

    def on_end(self) -> None:
        seg_audio = self.buf.pop_all()
        if seg_audio.size > 0:
            try:
                final_text = self.asr.transcribe_offline_with_punc(seg_audio)
                if final_text:
                    logger.info(f"ASR(paraformer-zh): {final_text}")
                    if self.on_final:
                        try:
                            self.on_final(final_text)
                        except Exception as exc:
                            logger.error(f"final callback failed: {exc}")
            except Exception as exc:
                logger.error(f"paraformer-zh failed: {exc}")
        self.buf.clear()
        logger.info("VAD end -> paraformer-zh")


class ParaformerZhStreamingDriver(RealtimeASRDriver):
    def __init__(
        self,
        asr: ASRLike,
        *,
        stride: int,
        tail_keep: int,
        partial_log_interval: float,
        on_partial: TextCallback = None,
        on_final: TextCallback = None,
    ) -> None:
        self.asr = asr
        self.stride = stride
        self.tail_keep = tail_keep
        self.partial_log_interval = partial_log_interval
        self.on_partial = on_partial
        self.on_final = on_final
        self.buf = AudioChunkBuffer()
        self._last_partial_text = ""
        self._last_partial_ts = 0.0

    def on_start(self) -> None:
        self.buf.clear()
        self.asr.reset_stream()
        self._last_partial_text = ""
        self._last_partial_ts = 0.0
        logger.info("VAD start -> paraformer-zh-streaming")

    def on_chunk(self, chunk: np.ndarray) -> None:
        self.buf.append(chunk)
        emit_threshold = self.stride + self.tail_keep
        while self.buf.size >= emit_threshold:
            send = self.buf.pop(self.stride)
            partial_text = self.asr.transcribe_stream(send, is_final=False)
            if not partial_text:
                continue

            now = time.monotonic()
            if partial_text == self._last_partial_text:
                continue
            if now - self._last_partial_ts < self.partial_log_interval:
                continue

            logger.info(f"ASR(partial): {partial_text}")
            self._last_partial_text = partial_text
            self._last_partial_ts = now
            if self.on_partial:
                try:
                    self.on_partial(partial_text)
                except Exception as exc:
                    logger.error(f"partial callback failed: {exc}")

    def on_end(self) -> None:
        remaining = self.buf.pop_all()
        if remaining.size > 0:
            final_text = self.asr.transcribe_stream(remaining, is_final=True)
            if final_text:
                logger.info(f"ASR(final): {final_text}")
                if self.on_final:
                    try:
                        self.on_final(final_text)
                    except Exception as exc:
                        logger.error(f"final callback failed: {exc}")
        self.buf.clear()
        logger.info("VAD end -> paraformer-zh-streaming")


def _build_paraformer_zh_driver(
    model: RealtimeASRModel,
    asr: ASRLike,
    *,
    stride: int,
    tail_keep: int,
    partial_log_interval: float,
    on_partial: TextCallback = None,
    on_final: TextCallback = None,
) -> RealtimeASRDriver:
    del model, stride, tail_keep, partial_log_interval, on_partial
    return ParaformerZhDriver(asr=asr, on_final=on_final)


def _build_paraformer_zh_streaming_driver(
    model: RealtimeASRModel,
    asr: ASRLike,
    *,
    stride: int,
    tail_keep: int,
    partial_log_interval: float,
    on_partial: TextCallback = None,
    on_final: TextCallback = None,
) -> RealtimeASRDriver:
    del model
    return ParaformerZhStreamingDriver(
        asr=asr,
        stride=stride,
        tail_keep=tail_keep,
        partial_log_interval=partial_log_interval,
        on_partial=on_partial,
        on_final=on_final,
    )


_DRIVER_BUILDERS: dict[str, Callable[..., RealtimeASRDriver]] = {
    "paraformer-zh": _build_paraformer_zh_driver,
    "paraformer-zh-streaming": _build_paraformer_zh_streaming_driver,
}


def build_realtime_asr_driver(
    model: RealtimeASRModel,
    asr: ASRLike,
    *,
    stride: int,
    tail_keep: int,
    partial_log_interval: float,
    on_partial: TextCallback = None,
    on_final: TextCallback = None,
) -> RealtimeASRDriver:
    builder = _DRIVER_BUILDERS.get(model.key)
    if builder is None:
        raise ValueError(f"unsupported realtime ASR driver: {model.key}")
    return builder(
        model,
        asr,
        stride=stride,
        tail_keep=tail_keep,
        partial_log_interval=partial_log_interval,
        on_partial=on_partial,
        on_final=on_final,
    )
