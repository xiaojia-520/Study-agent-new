import unittest
from unittest.mock import patch

import numpy as np

from src.core.asr.realtime_drivers import (
    ParaformerZhDriver,
    ParaformerZhStreaming2PassDriver,
    ParaformerZhStreamingDriver,
    build_realtime_asr_driver,
)
from src.core.asr.realtime_models import list_realtime_asr_model_keys, resolve_realtime_asr_model
from src.core.asr.transcriber import ASRTranscriber


class FakeASR:
    def __init__(self, stream_partials: list[str] | None = None) -> None:
        self.stream_calls = []
        self.offline_inputs = []
        self.stream_partials = list(stream_partials or [])

    def reset_stream(self) -> None:
        return None

    def transcribe_offline(self, audio_data: np.ndarray) -> str:
        return "offline"

    def transcribe_offline_with_punc(self, audio_data: np.ndarray) -> str:
        self.offline_inputs.append(audio_data.copy())
        return "second-pass-final"

    def transcribe_stream(self, speech_chunk: np.ndarray, is_final: bool = False) -> str:
        self.stream_calls.append((speech_chunk.copy(), is_final))
        if not is_final and self.stream_partials:
            return self.stream_partials.pop(0)
        return "final" if is_final else "partial"


class FakeModel:
    def generate(self, **kwargs):
        del kwargs
        return [{"text": "ok"}]


class FakeModelHub:
    def __init__(self) -> None:
        self.asr_loads = 0
        self.offline_loads = 0

    def load_asr_model(self, model_name: str | None = None) -> FakeModel:
        del model_name
        self.asr_loads += 1
        return FakeModel()

    def load_funasr_model(self) -> FakeModel:
        self.offline_loads += 1
        return FakeModel()


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

    def test_resolve_realtime_asr_model_uses_streaming_default(self) -> None:
        model = resolve_realtime_asr_model(None)
        self.assertEqual(model.key, "paraformer-zh-streaming-2pass")
        self.assertIn("speech_paraformer-large_asr_nat", model.resolved_model_name)

    def test_resolve_realtime_asr_model_rejects_invalid_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported realtime ASR model"):
            resolve_realtime_asr_model("unknown-model")

    def test_transcriber_loads_offline_funasr_on_init(self) -> None:
        fake_hub = FakeModelHub()
        with patch("src.core.asr.transcriber.model_hub", fake_hub):
            transcriber = ASRTranscriber(model_name="streaming")

            self.assertEqual(fake_hub.asr_loads, 1)
            self.assertEqual(fake_hub.offline_loads, 1)

            self.assertEqual(transcriber.transcribe_offline_with_punc(np.array([1.0], dtype=np.float32)), "ok")
            self.assertEqual(fake_hub.offline_loads, 1)

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

    def test_streaming_2pass_emits_accumulated_partials(self) -> None:
        partials = []
        fake_asr = FakeASR(stream_partials=["第一段", "段第二段", "第三段"])
        model = resolve_realtime_asr_model("paraformer-zh-streaming-2pass")
        driver = build_realtime_asr_driver(
            model=model,
            asr=fake_asr,
            stride=4,
            tail_keep=0,
            partial_log_interval=0.0,
            on_partial=partials.append,
            on_final=lambda text: None,
        )

        driver.on_start()
        driver.on_chunk(np.array([1, 2, 3, 4], dtype=np.float32))
        driver.on_chunk(np.array([5, 6, 7, 8], dtype=np.float32))
        driver.on_chunk(np.array([9, 10, 11, 12], dtype=np.float32))

        self.assertEqual(partials, ["第一段", "第一段第二段", "第一段第二段第三段"])


if __name__ == "__main__":
    unittest.main()
