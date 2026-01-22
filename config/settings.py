# 全局配置中心 - 最终完整版（适配BASE_DIR拼接本地模型）
from pydantic_settings import BaseSettings
import os
from pathlib import Path


class Settings(BaseSettings):
    # 项目根目录 (Path对象)
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    # 数据存储目录
    DATA_DIR: Path = BASE_DIR / "data"
    DATA_DIR.mkdir(exist_ok=True)
    TRANSCRIPT_SAVE_DIR: Path = DATA_DIR / "transcripts"
    TRANSCRIPT_SAVE_DIR.mkdir(exist_ok=True)
    # 模型根目录
    MODEL_BASE_DIR: Path = BASE_DIR / "models"
    MODEL_BASE_DIR.mkdir(exist_ok=True)
    ASR_MODEL_DIR: Path = MODEL_BASE_DIR / "asr"
    ASR_MODEL_DIR.mkdir(exist_ok=True)
    EMBED_MODEL_DIR: Path = MODEL_BASE_DIR / "embedding"
    EMBED_MODEL_DIR.mkdir(exist_ok=True)
    VAD_MODEL_DIR: Path = MODEL_BASE_DIR / "vad"
    VAD_MODEL_DIR.mkdir(exist_ok=True)

    # ===== 音频配置 =====
    AUDIO_SAMPLE_RATE: int = 16000
    AUDIO_CHANNELS: int = 1
    AUDIO_FRAME_MS: int = 30
    VAD_AGGRESSIVENESS: int = 2
    AUDIO_CHUNK_SIZE: int = 512
    VAD_THRESHOLD: float = 0.3  # VAD 语音检测阈值（0-1，值越高越严格）
    AUDIO_DEVICE: int = 1

    # ===== ✅ ASR配置【核心修改：BASE_DIR拼接本地模型路径】=====
    # 写法1：本地已下载好模型 → 直接指向模型文件夹（推荐，优先用这个）
    ASR_MODEL_NAME: str = str(Path(BASE_DIR / "models" / "asr" / "speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online"))
    ASR_USE_OFFLINE: bool = True
    ASR_LOCAL_MODEL_PATH: Path = ASR_MODEL_DIR

    # ===== ✅ 向量模型配置【同样支持BASE_DIR拼接】=====
    EMBED_MODEL_NAME: Path = BASE_DIR / "models" / "embedding" / "bge-small-zh-v1.5"
    VECTOR_DIM: int = 384
    EMBED_LOCAL_MODEL_PATH: Path = EMBED_MODEL_DIR

    # ===== 存储配置 =====
    TRANSCRIPT_ROOT_DIR: Path = TRANSCRIPT_SAVE_DIR
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "speech_transcript"
    QDRANT_CREATE_IF_NOT_EXIST: bool = True

    class Config:
        case_sensitive = True


# 全局单例配置对象
settings = Settings()
