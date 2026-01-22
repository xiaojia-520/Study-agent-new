from silero_vad import VADIterator
from typing import Optional
import numpy as np

from config.settings import settings
from src.infrastructure.logger import get_logger
from src.infrastructure.model_hub import model_hub

logger = get_logger("VADProcessor")


class VADProcessor:
    """
    只负责：输入一帧音频 -> 输出 VAD 事件（start/end）或 None
    """

    def __init__(self):
        self.sample_rate = settings.AUDIO_SAMPLE_RATE
        self.vad_threshold = settings.VAD_THRESHOLD
        self.vad_model: Optional[object] = model_hub.load_vad_model()
        self.vad_iterator: Optional[VADIterator] = VADIterator(
            model=self.vad_model,
            threshold=self.vad_threshold,
            sampling_rate=self.sample_rate,
        )
        self._is_initialized = False

        # ✅ 参数只在初始化阶段读取一次（不要散落在 process_frame 里）
        self._sample_rate: Optional[int] = None
        self._return_seconds: bool = True  # 想改成 False 也只改这里

    def _initialize_vad(self) -> None:
        if self._is_initialized:
            return
        if self.vad_threshold is None:
            raise ValueError("配置项 VAD_THRESHOLD 未设置")
        if self.sample_rate is None:
            raise ValueError("配置项 AUDIO_SAMPLE_RATE 未设置")

        logger.info(f"加载 VAD 模型 | threshold={self.vad_threshold}, sample_rate={self.sample_rate}")



    @staticmethod
    def _prep_frame(frame) -> Optional[np.ndarray]:
        """
        统一把输入整理成：1D float32 单声道波形
        """
        arr = np.asarray(frame, dtype=np.float32).squeeze()
        if arr.ndim != 1 or arr.size == 0:
            return None
        return arr

    def process_frame(self, frame):
        """
        输入：一帧音频（建议来自 FrameSlicer 的固定窗口，如 512 samples）
        输出：
          - None
          - {"start": t} 或 {"end": t}
        """
        try:
            if self.vad_iterator is None:
                return None

            frame_1d = self._prep_frame(frame)
            if frame_1d is None:
                return None

            event = self.vad_iterator(frame_1d, return_seconds=self._return_seconds)
            return event or None

        except Exception:
            return None

    def reset(self) -> None:
        """重置 VAD 状态（切换音源/新一段开始时可用）"""
        if self.vad_iterator is not None:
            self.vad_iterator.reset_states()

    def close(self) -> None:
        """释放 VAD 资源"""
        if self.vad_iterator is not None:
            self.vad_iterator.reset_states()

        self.vad_model = None
        self.vad_iterator = None
        self._sample_rate = None
        self._is_initialized = False
        logger.info("VAD 资源已释放")


vad_processor = VADProcessor()
