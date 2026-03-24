from pathlib import Path
from pprint import pprint

from src.infrastructure.model_hub import model_hub


TEST_AUDIO_PATH = Path(
    r"E:\Study-agent-new-master\models\asr\speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online\example\asr_example.wav"
)


def main() -> None:
    funasr_model = model_hub.load_funasr_model()
    result = funasr_model.generate(
        input=str(TEST_AUDIO_PATH),
        batch_size_s=300,
        language="zh",
    )

    print("funasr path: model_hub.load_funasr_model -> funasr_model.generate")
    print(f"audio_path={TEST_AUDIO_PATH}")
    print(f"type(result)={type(result)}")
    if isinstance(result, list) and result:
        print(f"type(result[0])={type(result[0])}")
    pprint(result)


if __name__ == "__main__":
    main()
