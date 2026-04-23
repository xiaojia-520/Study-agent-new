from pathlib import Path

from pydantic_settings import BaseSettings


def _ensure_dir(path: Path) -> Path:
    path.mkdir(exist_ok=True, parents=True)
    return path


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).resolve().parent.parent

    DATA_DIR: Path = _ensure_dir(BASE_DIR / "data")
    TRANSCRIPT_SAVE_DIR: Path = _ensure_dir(DATA_DIR / "transcripts")
    ASSET_SAVE_DIR: Path = _ensure_dir(DATA_DIR / "assets")
    MINERU_RESULT_DIR: Path = _ensure_dir(DATA_DIR / "mineru_results")
    QDRANT_LOCAL_DIR: Path = _ensure_dir(DATA_DIR / "qdrant")
    SQLITE_DB_PATH: Path = DATA_DIR / "study_agent.sqlite3"

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
        "paraformer-zh-streaming-2pass": "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
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

    RAG_TRANSCRIPT_ROOT: Path = TRANSCRIPT_SAVE_DIR
    RAG_EMBED_MODEL_NAME: Path = EMBED_MODEL_NAME
    RAG_QDRANT_COLLECTION: str = "speech_transcript_chunks"
    RAG_QDRANT_PREFER_LOCAL: bool = True
    RAG_QDRANT_LOCAL_PATH: Path = _ensure_dir(QDRANT_LOCAL_DIR / "speech_transcript_chunks")
    RAG_QDRANT_TIMEOUT: int = 10
    RAG_TOP_K: int = 5
    RAG_CHUNK_MAX_CHARS: int = 500
    RAG_CHUNK_OVERLAP_RECORDS: int = 1
    RAG_CHUNK_MIN_CHARS: int = 80
    RAG_SPLIT_LONG_RECORD: bool = True
    RAG_ENABLE_LLM: bool = False
    RAG_REALTIME_INDEXING_ENABLED: bool = True
    RAG_REALTIME_FLUSH_RECORDS: int = 3
    RAG_REALTIME_FLUSH_CHARS: int = 300
    RAG_REALTIME_FLUSH_INTERVAL_SECONDS: float = 20.0
    RAG_REALTIME_QUEUE_SIZE: int = 256
    RAG_LLM_PROVIDER: str = "openai"
    RAG_LLM_MODEL: str = "gpt-4o-mini"
    RAG_LLM_API_KEY: str = ""
    RAG_LLM_API_BASE: str = ""
    RAG_LLM_TEMPERATURE: float = 0.1
    RAG_LLM_MAX_TOKENS: int | None = 512
    RAG_LLM_TIMEOUT: float = 60.0

    MINERU_API_TOKEN: str = ""
    MINERU_BASE_URL: str = "https://mineru.net"
    MINERU_MODEL_VERSION: str = "vlm"
    MINERU_LANGUAGE: str = "ch"
    MINERU_ENABLE_FORMULA: bool = True
    MINERU_ENABLE_TABLE: bool = True
    MINERU_IS_OCR: bool = False
    MINERU_POLL_INTERVAL_SECONDS: float = 3.0
    MINERU_POLL_TIMEOUT_SECONDS: float = 600.0
    MINERU_REQUEST_TIMEOUT_SECONDS: float = 30.0
    MINERU_UPLOAD_TIMEOUT_SECONDS: float = 300.0
    MINERU_DOWNLOAD_TIMEOUT_SECONDS: float = 300.0
    MINERU_AUTO_INDEX_ENABLED: bool = True
    MINERU_MAX_UPLOAD_BYTES: int = 200 * 1024 * 1024

    class Config:
        case_sensitive = True
        env_file = Path(__file__).resolve().parent / ".env"
        env_file_encoding = "utf-8"


settings = Settings()
