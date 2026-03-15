from pathlib import Path

from pydantic_settings import BaseSettings


def _ensure_dir(path: Path) -> Path:
    path.mkdir(exist_ok=True, parents=True)
    return path


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    DATA_DIR: Path = _ensure_dir(BASE_DIR / "data")
    TRANSCRIPT_SAVE_DIR: Path = _ensure_dir(DATA_DIR / "transcripts")

    MODEL_BASE_DIR: Path = _ensure_dir(BASE_DIR / "models")
    ASR_MODEL_DIR: Path = _ensure_dir(MODEL_BASE_DIR / "asr")
    EMBED_MODEL_DIR: Path = _ensure_dir(MODEL_BASE_DIR / "embedding")
    VAD_MODEL_DIR: Path = _ensure_dir(MODEL_BASE_DIR / "vad")
    PUNC_MODEL_DIR: Path = _ensure_dir(MODEL_BASE_DIR / "punc")

    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    AUDIO_CHUNK_SIZE: int = 512
    VAD_THRESHOLD: float = 0.3
    AUDIO_DEVICE: int = 1

    ASR_MODEL_PATH: dict[str, str] = {
        "paraformer-zh": "speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "paraformer-zh-streaming": "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    }
    ASR_DEFAULT_MODEL_KEY: str = "paraformer-zh"
    ASR_LOCAL_MODEL_PATH: Path = ASR_MODEL_DIR
    ASR_MODEL_NAME: str = str(ASR_LOCAL_MODEL_PATH / ASR_MODEL_PATH[ASR_DEFAULT_MODEL_KEY])

    VAD_MODEL_NAME: str = str(VAD_MODEL_DIR / "speech_fsmn_vad_zh-cn-16k-common-pytorch")
    PUNC_MODEL_NAME: str = str(PUNC_MODEL_DIR / "punc_ct-transformer_cn-en-common-vocab471067-large")

    EMBED_MODEL_NAME: Path = EMBED_MODEL_DIR / "bge-small-zh-v1.5"
    VECTOR_DIM: int = 384

    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "speech_transcript"
    QDRANT_CREATE_IF_NOT_EXIST: bool = True

    class Config:
        case_sensitive = True


settings = Settings()
