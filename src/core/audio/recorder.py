# 音频业务逻辑：录音采集，只做业务相关的音频处理，调用基础设施层的配置/日志
import sounddevice as sd
import numpy as np
from src.infrastructure.logger import get_logger
from config.settings import settings

logger = get_logger("AudioRecorder")


class AudioRecorder:
    """音频采集器：业务逻辑-实时采集麦克风音频流"""

    def __init__(self):
        self.sample_rate = settings.AUDIO_SAMPLE_RATE
        self.channels = settings.AUDIO_CHANNELS
        self.chunk_size = settings.AUDIO_CHUNK_SIZE
        self.stream = None
        self.audio_buffer = []
        self.device = settings.AUDIO_DEVICE
        logger.info("音频采集器初始化完成")

    def start_stream(self, callback):
        """启动音频流，回调函数处理每帧音频数据"""
        self.stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.chunk_size,
            callback=callback,
            device=self.device,
            dtype='int16'
        )
        self.stream.start()
        logger.info("麦克风录音已启动")

    def stop_stream(self):
        """停止音频流"""
        if self.stream and self.stream.active:
            self.stream.stop()
            self.stream.close()
            logger.info("麦克风录音已停止")

    @staticmethod
    def normalize_audio(audio_data: np.ndarray) -> np.ndarray:
        """业务处理：音频归一化（优化转写效果）"""
        return audio_data / np.max(np.abs(audio_data)) if np.max(np.abs(audio_data)) > 0 else audio_data
