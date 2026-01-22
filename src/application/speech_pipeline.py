# src/application/speech_pipeline.py
import queue
import threading
import time
from collections import deque
import numpy as np

from src.infrastructure.logger import get_logger
from src.core.audio.recorder import AudioRecorder
from src.core.audio.vad_processor import VADProcessor
from src.core.audio.frame_slicer import FrameSlicer
from src.core.asr.transcriber import ASRTranscriber

logger = get_logger("SpeechPipeline")


class _ChunkFIFO:
    """
    ✅ worker 内部“语音缓冲区”（极限优化版）

    目标：替代 np.concatenate 反复拷贝
    - append：只把 chunk 放进 deque（O(1)）
    - pop(n)：需要喂 ASR 时，才拷贝出连续 n samples（每 stride 一次）
    - pop_all：end 时一次性拷贝剩余用于 final
    """

    def __init__(self):
        self._chunks = deque()     # deque[np.ndarray]
        self._head_offset = 0      # 当前头 chunk 已消费到的位置
        self._size = 0             # 总样本数

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
        """弹出 n 个 samples（一次拷贝），用于喂 ASR。"""
        if n <= 0 or self._size <= 0:
            return np.zeros((0,), dtype=np.float32)

        n = min(n, self._size)
        out = np.empty((n,), dtype=np.float32)
        filled = 0

        while filled < n:
            head = self._chunks[0]
            remain_in_head = head.size - self._head_offset
            take = min(n - filled, remain_in_head)

            out[filled:filled + take] = head[self._head_offset:self._head_offset + take]
            filled += take
            self._head_offset += take

            if self._head_offset >= head.size:
                self._chunks.popleft()
                self._head_offset = 0

        self._size -= n
        return out

    def pop_all(self) -> np.ndarray:
        """弹出所有剩余 samples（一次拷贝），用于 end/final。"""
        return self.pop(self._size)


class SpeechPipeline:
    def __init__(self):
        self.recorder = AudioRecorder()
        self.vad = VADProcessor()

        # ✅ FrameSlicer 已优化为 deque 实现（回调线程更稳）
        self.slicer = FrameSlicer(window_size=512)  # Silero 16k 固定 512

        # ✅ ASR 预初始化（避免第一次推理卡 callback）
        self.asr = ASRTranscriber()

        # ✅ 音频队列：callback -> worker
        self.q = queue.Queue(maxsize=2000)

        self._stop_event = threading.Event()
        self._worker = threading.Thread(target=self._asr_worker_loop, daemon=True)

        # ✅ worker 内部状态（只在 worker 线程用）
        self._in_speech = False
        self._buf = _ChunkFIFO()

        # ✅ callback 内部状态（只在 callback 线程用）
        # 作用：静音帧不入队，只在“speech 段内”才把 chunk 入队
        self._cb_in_speech = False

        # FunASR streaming stride：chunk_size[1] * 960 (16k 下 960 ≈ 60ms)
        self.chunk_size = [0, 10, 5]
        self.asr_stride = self.chunk_size[1] * 960  # 10*960=9600 samples ~ 600ms

        # ✅ “尾巴保留”策略：越小字幕越快，但 end 时更容易丢尾字
        # 极限建议：0.25~0.5 stride；你想更跟嘴就调小
        self.tail_keep = int(0.35 * self.asr_stride)  # 默认保留 ~210ms 尾巴

        # ✅ 降低日志 IO 开销（partial 太频繁会拖慢 worker）
        self._last_partial_text = ""
        self._last_partial_ts = 0.0
        self.partial_log_interval = 0.25  # 秒：节流

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
            self.q.put_nowait(None)  # sentinel
        except queue.Full:
            pass

        if self._worker.is_alive():
            self._worker.join(timeout=2.0)

        logger.info("语音处理流水线已停止")

    # ---------------------------
    # callback: 尽量“只做轻活”
    # ---------------------------

    def _put_nonblocking(self, item, critical: bool = False):
        """
        critical = False  → 普通音频帧
        critical = True   → VAD start / end 这种“控制帧”
        """

        # ① 正常情况：队列没满，直接入队
        try:
            self.q.put_nowait(item)
            return

        except queue.Full:
            # ② 队列满了

            # ②-1 普通帧：直接丢
            if not critical:
                return

            # ②-2 关键帧（start / end）：尝试“抢位”
            try:
                _ = self.q.get_nowait()  # 丢掉一个旧 item
            except queue.Empty:
                pass

            # ②-3 再试一次把关键帧塞进去
            try:
                self.q.put_nowait(item)
            except queue.Full:
                # ②-4 极端情况下还是失败 → 放弃（但已经尽力）
                return

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.warning(f"音频采集状态异常: {status}")

        # 1) 转 1D float32
        audio = indata.astype(np.float32).squeeze()
        if audio.ndim != 1:
            audio = audio.reshape(-1)

        # 2) 归一化到 [-1,1]（int16 -> float）
        audio = audio / 32768.0

        # 3) 切成 512 的块
        chunks = self.slicer.push(audio)

        # 4) 每块喂给 VAD
        # ✅ 极限优化：静音帧不再入队（但 VAD 仍然每帧都跑，保证能产生 end）
        for chunk in chunks:
            event = self.vad.process_frame(chunk)  # {"start":...} / {"end":...} / None

            if isinstance(event, dict):
                # start/end 一定要入队（关键帧）
                if "start" in event:
                    self._cb_in_speech = True

                # 关键帧：尽量保证送到 worker（否则 worker 可能收不到 end 卡死）
                self._put_nonblocking((event, chunk), critical=True)

                if "end" in event:
                    # 注意：end 事件那一帧也会入队（上面已入）
                    # end 之后的纯静音帧将不再入队
                    self._cb_in_speech = False
            else:
                # 非事件帧：仅在 speech 段内才入队（否则静音帧会把队列塞满）
                if self._cb_in_speech:
                    self._put_nonblocking((None, chunk), critical=False)
                else:
                    # 静音且无事件：直接丢（省队列、省 worker 的 get 次数）
                    pass

    # ---------------------------
    # worker: 事件驱动 + 流式喂 ASR
    # ---------------------------

    def _asr_worker_loop(self):
        """
        后台线程：按 VAD start/end 控制是否喂 ASR
        - start：reset cache，开始累积并流式喂入
        - partial：当 buf >= stride + tail_keep 就吐一段（比原来的 2*stride 更快出字幕）
        - end：把剩余 buffer 用 is_final=True 喂一次，强制吐尾字，然后停止喂
        """
        while not self._stop_event.is_set():
            item = self.q.get()
            if item is None:
                break

            event, chunk = item
            end_now = False

            # 1) 处理事件（start 需要在 append chunk 前执行，确保该 chunk 计入新一句）
            if isinstance(event, dict):
                if "start" in event:
                    # 即使本来就在 speech，也当作重开一句，避免缓存串句
                    self._in_speech = True
                    self._buf.clear()
                    self.asr.reset_stream()
                    logger.info("VAD start -> 开始喂 ASR")

                if "end" in event:
                    # end 需要在 append chunk 后执行 final，确保“end 那一帧”也能被计入
                    end_now = True

            # 2) 非 speech 段：直接跳过音频
            if not self._in_speech:
                continue

            # 3) speech 段：累计 chunk（O(1)）
            self._buf.append(chunk)

            # 4) 更快吐字幕：只要 buf >= stride + tail_keep 就送 stride
            #    tail_keep 留在 buf 里，保证 end 时 final 更稳，不吞尾字
            emit_threshold = self.asr_stride + self.tail_keep
            while self._buf.size >= emit_threshold:
                send = self._buf.pop(self.asr_stride)  # 每次仅拷贝 stride（≈600ms）
                partial_text = self.asr.feed_stream(send, is_final=False)

                # ✅ 日志节流：避免 IO 拖慢 worker
                if partial_text:
                    now = time.monotonic()
                    if (partial_text != self._last_partial_text) and (now - self._last_partial_ts >= self.partial_log_interval):
                        logger.info(f"ASR(partial): {partial_text}")
                        self._last_partial_text = partial_text
                        self._last_partial_ts = now

            # 5) end：flush 全部剩余并 final（保证尾字）
            if end_now:
                remaining = self._buf.pop_all()
                if remaining.size > 0:
                    final_text = self.asr.feed_stream(remaining, is_final=True)
                    if final_text:
                        logger.info(f"ASR(final): {final_text}")

                self._in_speech = False
                self._buf.clear()
                logger.info("VAD end -> 停止喂 ASR")
