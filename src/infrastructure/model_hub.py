# 纯技术封装：模型加载/卸载/缓存，只做技术实现，无业务逻辑
# 核心：Core层只调用模型，不关心模型怎么加载的
from funasr import AutoModel
from sentence_transformers import SentenceTransformer
from src.infrastructure.logger import get_logger
from config.settings import settings
from silero_vad import load_silero_vad

logger = get_logger("ModelHub")


class ModelHub:
    """模型仓储：统一管理所有AI模型的加载和实例化"""
    _instance = None
    _asr_model = None
    _embed_model = None
    _vad_model = None

    def __new__(cls):
        # 单例模式，避免重复加载模型占用内存
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_asr_model(self):
        """加载语音转写模型"""
        if self._asr_model is None:
            logger.info(f"开始加载ASR模型: {settings.ASR_MODEL_NAME}")
            self._asr_model = AutoModel(model=settings.ASR_MODEL_NAME, trust_remote_code=True)
            logger.info("ASR模型加载完成")
        return self._asr_model

    def load_embed_model(self):
        """加载文本向量化模型"""
        if self._embed_model is None:
            logger.info(f"开始加载向量模型: {settings.EMBED_MODEL_NAME}")
            self._embed_model = SentenceTransformer(settings.EMBED_MODEL_NAME)
            logger.info("向量模型加载完成")
        return self._embed_model

    def load_vad_model(self):
        """加载VAD模型"""
        if self._vad_model is None:
            logger.info(f"开始加载VAD模型: silero_vad")
            self._vad_model = load_silero_vad()
            logger.info("VAD模型加载完成")
        return self._vad_model


# 全局单例模型仓储
model_hub = ModelHub()
