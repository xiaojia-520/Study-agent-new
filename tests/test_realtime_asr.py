import unittest

import numpy as np

from src.core.asr.realtime_drivers import (
    ParaformerZhDriver,
    ParaformerZhStreamingDriver,
    build_realtime_asr_driver,
)
from src.core.asr.realtime_models import list_realtime_asr_model_keys, resolve_realtime_asr_model


class FakeASR:
    def reset_stream(self) -> None:
        return None

    def transcribe_offline(self, audio_data: np.ndarray) -> str:
        return "offline"

    def transcribe_stream(self, speech_chunk: np.ndarray, is_final: bool = False) -> str:
        return "final" if is_final else "partial"


class RealtimeASRTests(unittest.TestCase):
    def test_list_realtime_asr_model_keys(self) -> None:
        self.assertEqual(
            list_realtime_asr_model_keys(),
            ("paraformer-zh", "paraformer-zh-streaming"),
        )

    def test_resolve_realtime_asr_model(self) -> None:
        model = resolve_realtime_asr_model("paraformer-zh")
        self.assertEqual(model.key, "paraformer-zh")
        self.assertIn("speech_paraformer-large-vad-punc", model.resolved_model_name)

    def test_resolve_realtime_asr_model_rejects_invalid_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported realtime ASR model"):
            resolve_realtime_asr_model("unknown-model")

    def test_build_realtime_asr_driver_for_paraformer_zh(self) -> None:
        model = resolve_realtime_asr_model("paraformer-zh")
        driver = build_realtime_asr_driver(
            model=model,
            asr=FakeASR(),
            stride=9600,
            tail_keep=3360,
            partial_log_interval=0.25,
        )
        self.assertIsInstance(driver, ParaformerZhDriver)

    def test_build_realtime_asr_driver_for_paraformer_zh_streaming(self) -> None:
        model = resolve_realtime_asr_model("paraformer-zh-streaming")
        driver = build_realtime_asr_driver(
            model=model,
            asr=FakeASR(),
            stride=9600,
            tail_keep=3360,
            partial_log_interval=0.25,
        )
        self.assertIsInstance(driver, ParaformerZhStreamingDriver)


if __name__ == "__main__":
    unittest.main()
