import unittest

import numpy as np

from src.core.asr.realtime_drivers import (
    ParaformerZhDriver,
    ParaformerZhStreaming2PassDriver,
    ParaformerZhStreamingDriver,
    build_realtime_asr_driver,
)
from src.core.asr.realtime_models import list_realtime_asr_model_keys, resolve_realtime_asr_model


class FakeASR:
    def __init__(self) -> None:
        self.stream_calls = []
        self.offline_inputs = []

    def reset_stream(self) -> None:
        return None

    def transcribe_offline(self, audio_data: np.ndarray) -> str:
        return "offline"

    def transcribe_offline_with_punc(self, audio_data: np.ndarray) -> str:
        self.offline_inputs.append(audio_data.copy())
        return "second-pass-final"

    def transcribe_stream(self, speech_chunk: np.ndarray, is_final: bool = False) -> str:
        self.stream_calls.append((speech_chunk.copy(), is_final))
        return "final" if is_final else "partial"


class RealtimeASRTests(unittest.TestCase):
    def test_list_realtime_asr_model_keys(self) -> None:
        self.assertEqual(
            list_realtime_asr_model_keys(),
            ("paraformer-zh", "paraformer-zh-streaming", "paraformer-zh-streaming-2pass"),
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

    def test_build_realtime_asr_driver_for_paraformer_zh_streaming_2pass(self) -> None:
        model = resolve_realtime_asr_model("paraformer-zh-streaming-2pass")
        driver = build_realtime_asr_driver(
            model=model,
            asr=FakeASR(),
            stride=4,
            tail_keep=0,
            partial_log_interval=0.0,
        )
        self.assertIsInstance(driver, ParaformerZhStreaming2PassDriver)

    def test_streaming_2pass_emits_partial_and_offline_final(self) -> None:
        partials = []
        finals = []
        fake_asr = FakeASR()
        model = resolve_realtime_asr_model("paraformer-zh-streaming-2pass")
        driver = build_realtime_asr_driver(
            model=model,
            asr=fake_asr,
            stride=4,
            tail_keep=0,
            partial_log_interval=0.0,
            on_partial=partials.append,
            on_final=finals.append,
        )

        driver.on_start()
        driver.on_chunk(np.array([1, 2, 3, 4], dtype=np.float32))
        driver.on_chunk(np.array([5, 6], dtype=np.float32))
        driver.on_end()

        self.assertEqual(partials, ["partial"])
        self.assertEqual(finals, ["second-pass-final"])
        self.assertEqual([is_final for _, is_final in fake_asr.stream_calls], [False, True])
        self.assertEqual(len(fake_asr.offline_inputs), 1)
        np.testing.assert_array_equal(
            fake_asr.offline_inputs[0],
            np.array([1, 2, 3, 4, 5, 6], dtype=np.float32),
        )


if __name__ == "__main__":
    unittest.main()
