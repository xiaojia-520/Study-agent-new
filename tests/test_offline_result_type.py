from pathlib import Path
from pprint import pprint

from src.core.asr.transcriber import ASRTranscriber


TEST_AUDIO_PATH = Path(
    r"E:\Study-agent-new-master\models\asr\speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online\example\asr_example.wav"
)


def main() -> None:
    transcriber = ASRTranscriber()
    result = transcriber.asr_model.generate(
        input=str(TEST_AUDIO_PATH),
        batch_size_s=300,
        language="zh",
    )

    print(f"audio_path={TEST_AUDIO_PATH}")
    print(f"type(result)={type(result)}")
    if isinstance(result, list) and result:
        print(f"type(result[0])={type(result[0])}")
    pprint(result)


if __name__ == "__main__":
    main()
