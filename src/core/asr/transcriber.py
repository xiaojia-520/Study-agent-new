import numpy as np
from src.infrastructure.model_hub import model_hub
from src.infrastructure.logger import get_logger
from pathlib import Path

logger = get_logger("ASRTranscriber")


class ASRTranscriber:
    def __init__(self):
        self.asr_model = model_hub.load_asr_model()
        logger.info("语音转写器初始化完成")

        # ✅ 流式相关：一句话内复用
        self.cache = {}
        self.chunk_size = [0, 10, 5]  # 600ms 粒度（常用默认）:contentReference[oaicite:1]{index=1}
        self.encoder_chunk_look_back = 4  # look-back 上下文 :contentReference[oaicite:2]{index=2}
        self.decoder_chunk_look_back = 1

    # 你原来的离线方法保留
    def transcribe_offline(self, audio_data: np.ndarray) -> str:
        result = self.asr_model.generate(
            input=audio_data,
            batch_size_s=300,
            language="zh",
        )
        return result[0]["text"] if result else ""

    # ✅ 新增：开始一段新语音（VAD start 时调用）
    def reset_stream(self):
        self.cache = {}

    # ✅ 新增：流式喂入（worker 线程调用）
    def transcribe_stream(self, speech_chunk: np.ndarray, is_final: bool = False) -> str:
        res = self.asr_model.generate(
            input=speech_chunk,
            cache=self.cache,
            is_final=is_final,
            chunk_size=self.chunk_size,
            encoder_chunk_look_back=self.encoder_chunk_look_back,
            decoder_chunk_look_back=self.decoder_chunk_look_back,
        )
        return res[0].get("text", "") if res else ""

    def transcribe(self, audio: str | Path) -> str:
        res = self.asr_model.generate(

            input=audio,
            batch_size_s=300
        )
        return res[0].get("text", "") if res else ""
