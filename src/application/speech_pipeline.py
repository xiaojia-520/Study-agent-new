# src/application/speech_pipeline.py
import queue
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

from config.settings import settings  # ✅ 用你的全局单例 settings
from src.infrastructure.logger import get_logger
from src.infrastructure.audio import indata_to_mono_float32
from src.core.audio.recorder import AudioRecorder
from src.core.audio.vad_processor import VADProcessor
from src.core.audio.frame_slicer import FrameSlicer
from src.core.asr.transcriber import ASRTranscriber

logger = get_logger("SpeechPipeline")


class _ChunkFIFO:
    """worker 内部语音缓冲区：避免 np.concatenate 反复拷贝"""

    def __init__(self):
        self._chunks = deque()  # deque[np.ndarray]
        self._head_offset = 0
        self._size = 0

    @property
    def size(self) -> int:
        return self._size

    def clear(self):
        self._chunks.clear()
        self._head_offset = 0
        self._size = 0

    def append(self, chunk: np.ndarray):
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


class _ASRDriverBase:
    def on_start(self):  # noqa
        raise NotImplementedError

    def on_chunk(self, chunk: np.ndarray):  # noqa
        raise NotImplementedError

    def on_end(self):  # noqa
        raise NotImplementedError


class _OnlineASRDriver(_ASRDriverBase):
    def __init__(
            self,
            asr: ASRTranscriber,
            buf: _ChunkFIFO,
            stride: int,
            tail_keep: int,
            partial_log_interval: float,
            on_partial=None,
            on_final=None,
    ):
        self.asr = asr
        self.buf = buf
        self.stride = stride
        self.tail_keep = tail_keep
        self.partial_log_interval = partial_log_interval
        self.on_partial = on_partial
        self.on_final = on_final

        self._last_partial_text = ""
        self._last_partial_ts = 0.0

    def on_start(self):
        self.buf.clear()
        self.asr.reset_stream()
        logger.info("VAD start -> 开始喂 ASR (online)")

    def on_chunk(self, chunk: np.ndarray):
        self.buf.append(chunk)

        emit_threshold = self.stride + self.tail_keep
        while self.buf.size >= emit_threshold:
            send = self.buf.pop(self.stride)
            partial_text = self.asr.transcribe_stream(send, is_final=False)

            if partial_text:
                now = time.monotonic()
                if (partial_text != self._last_partial_text) and (
                        now - self._last_partial_ts >= self.partial_log_interval):
                    logger.info(f"ASR(partial): {partial_text}")
                    self._last_partial_text = partial_text
                    self._last_partial_ts = now
                    if self.on_partial:
                        try:
                            self.on_partial(partial_text)
                        except Exception as exc:
                            logger.error(f"partial 回调失败: {exc}")

    def on_end(self):
        remaining = self.buf.pop_all()
        if remaining.size > 0:
            final_text = self.asr.transcribe_stream(remaining, is_final=True)
            if final_text:
                logger.info(f"ASR(final): {final_text}")
                if self.on_final:
                    try:
                        self.on_final(final_text)
                    except Exception as exc:
                        logger.error(f"final 回调失败: {exc}")
        self.buf.clear()
        logger.info("VAD end -> 停止喂 ASR (online)")


class _OfflineASRDriver(_ASRDriverBase):
    def __init__(self, asr: ASRTranscriber, buf: _ChunkFIFO, on_final=None):
        self.asr = asr
        self.buf = buf
        self.on_final = on_final

    def on_start(self):
        self.buf.clear()
        logger.info("VAD start -> 开始喂 ASR (offline)")

    def on_chunk(self, chunk: np.ndarray):
        self.buf.append(chunk)

    def on_end(self):
        seg_audio = self.buf.pop_all()
        if seg_audio.size > 0:
            try:
                offline_res = self.asr.transcribe_offline(seg_audio)
                if offline_res:
                    logger.info(f"ASR(offline): {offline_res}")
                    if self.on_final:
                        try:
                            self.on_final(offline_res)
                        except Exception as exc:
                            logger.error(f"final 回调失败: {exc}")
            except Exception as e:
                logger.error(f"离线ASR失败: {e}")
        self.buf.clear()
        logger.info("VAD end -> 停止喂 ASR (offline)")


class SpeechPipeline:
    """
    callback 线程：切帧 + VAD + 入队（尽量轻）
    worker 线程：事件驱动 start/end + 在线/离线 ASR（策略封装）
    """

    def __init__(self):
        self.recorder = AudioRecorder()
        self.vad = VADProcessor()
        self.slicer = FrameSlicer(window_size=512)  # Silero 16k 固定 512

        self.q = queue.Queue(maxsize=2000)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._asr_worker_loop, daemon=True)

        # worker / callback 状态
        self._in_speech = False
        self._cb_in_speech = False

        # streaming 参数（online 用）
        # 你 ASRTranscriber 里 chunk_size=[0,10,5]，这里保持一致
        self.chunk_size = [0, 10, 5]
        self.asr_stride = self.chunk_size[1] * 960  # 600ms
        self.tail_keep = int(0.35 * self.asr_stride)
        self.partial_log_interval = 0.25

        # buffers
        self._buf = _ChunkFIFO()  # online
        self._seg_buf = _ChunkFIFO()  # offline

        # 热切配置锁
        self._cfg_lock = threading.Lock()

        # init asr + driver（按 settings 当前配置）
        self.asr = ASRTranscriber()
        self._driver = self._build_driver()

    # ---------------------------
    # public
    # ---------------------------

    def start(self):
        self._stop_event.clear()
        if not self._worker.is_alive():
            self._worker = threading.Thread(target=self._asr_worker_loop, daemon=True)
            self._worker.start()

        self.recorder.start_stream(self._audio_callback)
        logger.info("语音处理流水线已启动")

    def stop(self):
        self.recorder.stop_stream()

        self._stop_event.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

        logger.info("语音处理流水线已停止")

    def set_asr_model(self, key_or_folder: str):
        """
        ✅ 给 web 用：切换 ASR 模型
        - key_or_folder 可以是 "funasr-offline"/"funasr-online"
        - 也可以直接传模型文件夹名（比如 "speech_paraformer-large_asr_nat-...-online"）
        """
        with self._cfg_lock:
            folder = self._resolve_model_folder(key_or_folder)
            is_offline = self._infer_offline(key_or_folder, folder)

            # 写回你的 settings（model_hub.load_asr_model 通常会读这些）
            settings.ASR_USE_OFFLINE = is_offline
            settings.ASR_MODEL_NAME = str(settings.ASR_LOCAL_MODEL_PATH / folder)

            # 清状态，避免串句
            self._in_speech = False
            self._cb_in_speech = False
            self._buf.clear()
            self._seg_buf.clear()
            self._drain_queue()

            # 由于 ASRTranscriber 目前无 set_model，直接重建最稳
            self.asr = ASRTranscriber()
            self._driver = self._build_driver()

        logger.info(
            f"ASR 模型已切换: key={key_or_folder}, offline={settings.ASR_USE_OFFLINE}, path={settings.ASR_MODEL_NAME}")

    # ---------------------------
    # helpers
    # ---------------------------

    def _build_driver(self) -> _ASRDriverBase:
        if settings.ASR_USE_OFFLINE:
            return _OfflineASRDriver(asr=self.asr, buf=self._seg_buf)
        return _OnlineASRDriver(
            asr=self.asr,
            buf=self._buf,
            stride=self.asr_stride,
            tail_keep=self.tail_keep,
            partial_log_interval=self.partial_log_interval,
        )

    @staticmethod
    def _resolve_model_folder(key_or_folder: str) -> str:
        # settings.ASR_MODEL_PATH 是 dict（你现在这么配的）
        mp = getattr(settings, "ASR_MODEL_PATH", None)
        if isinstance(mp, dict) and key_or_folder in mp:
            return mp[key_or_folder]
        return key_or_folder

    @staticmethod
    def _infer_offline(key: str, folder: str) -> bool:
        k = (key or "").lower()
        f = (folder or "").lower()
        # 明确 key
        if k in ("funasr-offline", "offline"):
            return True
        if k in ("funasr-online", "online"):
            return False
        # 兜底：用名字推断
        if "online" in f:
            return False
        return True

    def _drain_queue(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    # ---------------------------
    # callback
    # ---------------------------

    def _put_nonblocking(self, item, critical: bool = False) -> bool:
        try:
            self.q.put_nowait(item)
            return True
        except queue.Full:
            if not critical:
                return False
            # 关键帧抢位
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(item)
                return True
            except queue.Full:
                return False

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"音频采集状态异常: {status}")

        # 1) 转 1D float32
        need_scale = np.issubdtype(indata.dtype, np.integer)
        audio = indata_to_mono_float32(indata)

        # 2) int -> [-1,1]
        if need_scale:
            audio = audio / 32768.0

        # 3) 切 512
        chunks = self.slicer.push(audio)

        # 4) VAD + 入队（静音不入队，但 VAD 每帧都跑）
        for chunk in chunks:
            event = self.vad.process_frame(chunk)

            if isinstance(event, dict):
                if "start" in event:
                    self._cb_in_speech = True

                self._put_nonblocking((event, chunk), critical=True)

                if "end" in event:
                    self._cb_in_speech = False
            else:
                if self._cb_in_speech:
                    self._put_nonblocking((None, chunk), critical=False)

    # ---------------------------
    # worker
    # ---------------------------

    def _asr_worker_loop(self):
        while not self._stop_event.is_set():
            item = self.q.get()
            if item is None:
                break

            event, chunk = item
            end_now = False

            # 读一次 driver（避免切模型时半句不一致）
            with self._cfg_lock:
                driver = self._driver

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


class WebSpeechPipeline:
    """WebSocket 语音流处理：接收外部音频帧，输出实时/最终文本。"""

    def __init__(self, on_partial=None, on_final=None):
        self.vad = VADProcessor()
        self.slicer = FrameSlicer(window_size=512)

        self.q = queue.Queue(maxsize=2000)
        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._asr_worker_loop, daemon=True)

        self._in_speech = False
        self._cb_in_speech = False

        self.chunk_size = [0, 10, 5]
        self.asr_stride = self.chunk_size[1] * 960
        self.tail_keep = int(0.35 * self.asr_stride)
        self.partial_log_interval = 0.25

        self._buf = _ChunkFIFO()
        self._seg_buf = _ChunkFIFO()

        self._cfg_lock = threading.Lock()

        self.asr = ASRTranscriber()
        self.on_partial = on_partial
        self.on_final = on_final
        self._driver = self._build_driver()

    def start(self):
        self._stop_event.clear()
        if not self._worker.is_alive():
            self._worker = threading.Thread(target=self._asr_worker_loop, daemon=True)
            self._worker.start()
        logger.info("WebSpeechPipeline 已启动")

    def stop(self):
        self._stop_event.set()
        try:
            self.q.put_nowait(None)
        except queue.Full:
            pass

        if self._worker.is_alive():
            self._worker.join(timeout=2.0)
        logger.info("WebSpeechPipeline 已停止")

    def feed_audio_bytes(self, audio_bytes: bytes):
        if not audio_bytes:
            return
        audio = np.frombuffer(audio_bytes, dtype=np.float32)
        self.feed_audio(audio)

    def feed_audio(self, audio: np.ndarray):
        if audio is None or audio.size == 0:
            return

        chunks = self.slicer.push(audio)

        for chunk in chunks:
            event = self.vad.process_frame(chunk)

            if isinstance(event, dict):
                if "start" in event:
                    self._cb_in_speech = True

                self._put_nonblocking((event, chunk), critical=True)

                if "end" in event:
                    self._cb_in_speech = False
            else:
                if self._cb_in_speech:
                    self._put_nonblocking((None, chunk), critical=False)

    def _build_driver(self) -> _ASRDriverBase:
        if settings.ASR_USE_OFFLINE:
            return _OfflineASRDriver(asr=self.asr, buf=self._seg_buf, on_final=self.on_final)
        return _OnlineASRDriver(
            asr=self.asr,
            buf=self._buf,
            stride=self.asr_stride,
            tail_keep=self.tail_keep,
            partial_log_interval=self.partial_log_interval,
            on_partial=self.on_partial,
            on_final=self.on_final,
        )

    @staticmethod
    def _resolve_model_folder(key_or_folder: str) -> str:
        mp = getattr(settings, "ASR_MODEL_PATH", None)
        if isinstance(mp, dict) and key_or_folder in mp:
            return mp[key_or_folder]
        return key_or_folder

    @staticmethod
    def _infer_offline(key: str, folder: str) -> bool:
        k = (key or "").lower()
        f = (folder or "").lower()
        if k in ("funasr-offline", "offline"):
            return True
        if k in ("funasr-online", "online"):
            return False
        if "online" in f:
            return False
        return True

    def _drain_queue(self):
        try:
            while True:
                self.q.get_nowait()
        except queue.Empty:
            pass

    def _put_nonblocking(self, item, critical: bool = False) -> bool:
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

    def _asr_worker_loop(self):
        while not self._stop_event.is_set():
            item = self.q.get()
            if item is None:
                break

            event, chunk = item
            end_now = False

            with self._cfg_lock:
                driver = self._driver

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
