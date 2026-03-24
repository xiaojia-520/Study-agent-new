from pathlib import Path

import numpy as np

from src.infrastructure.logger import get_logger
from src.infrastructure.model_hub import model_hub

logger = get_logger("ASRTranscriber")


class ASRTranscriber:
    def __init__(self, model_name: str | None = None):
        self.asr_model = model_hub.load_asr_model(model_name=model_name)
        self.offline_funasr_model = model_hub.load_funasr_model()
        logger.info("ASR transcriber initialized")

        self.cache = {}
        self.chunk_size = [0, 10, 5]
        self.encoder_chunk_look_back = 4
        self.decoder_chunk_look_back = 1

    def transcribe_offline(self, audio_data: np.ndarray) -> str:
        result = self.asr_model.generate(
            input=audio_data,
            batch_size_s=300,
            language="zh",
        )
        return result[0]["text"] if result else ""

    def transcribe_offline_with_punc(self, audio_data: np.ndarray) -> str:
        result = self.offline_funasr_model.generate(
            input=audio_data,
            batch_size_s=300,
            language="zh",
        )
        return result[0]["text"] if result else ""

    def reset_stream(self):
        self.cache = {}

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


class VEDIOTranscriber:
    def __init__(self):
        self.funasr_model = model_hub.load_funasr_model()

    def transcribe(self, audio: str | Path) -> str:
        res = self.funasr_model.generate(
            input=audio,
            batch_size_s=300,
            vad_kwargs={"max_single_segment_time": 60000},
        )
        return res[0]["sentence_info"]
