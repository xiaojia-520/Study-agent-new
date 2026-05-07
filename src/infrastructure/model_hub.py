from funasr import AutoModel
from sentence_transformers import SentenceTransformer
from silero_vad import load_silero_vad
import threading

from config.settings import settings
from src.infrastructure.logger import get_logger

logger = get_logger("ModelHub")


def _resolve_device(requested: str | None) -> str:
    device = (requested or "").strip().lower()
    if device and device != "auto":
        return device

    try:
        import torch
    except ImportError:
        return "cpu"

    return "cuda" if torch.cuda.is_available() else "cpu"


class ModelHub:
    _instance = None
    _asr_models = {}
    _embed_model = None
    _vad_model = None

    def __init__(self):
        self.funasr_model = None
        self.funasr_2pass_model = None
        self._asr_lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_asr_model(self, model_name: str | None = None):
        resolved_model_name = model_name or settings.ASR_MODEL_NAME
        resolved_device = _resolve_device(settings.ASR_DEVICE)
        with self._asr_lock:
            model = self._asr_models.get(resolved_model_name)
            if model is None:
                logger.info(f"Loading ASR model: {resolved_model_name} on device={resolved_device}")
                model = AutoModel(
                    model=resolved_model_name,
                    trust_remote_code=True,
                    disable_update=True,
                    device=resolved_device,
                )
                self._asr_models[resolved_model_name] = model
                logger.info("ASR model loaded")
        return model

    def reset_asr_model(self, model_name: str | None = None):
        with self._asr_lock:
            if model_name is None:
                self._asr_models.clear()
                return
            self._asr_models.pop(model_name, None)

    def load_embed_model(self):
        if self._embed_model is None:
            resolved_device = _resolve_device(settings.EMBED_DEVICE)
            logger.info(f"Loading embed model: {settings.EMBED_MODEL_NAME} on device={resolved_device}")
            self._embed_model = SentenceTransformer(settings.EMBED_MODEL_NAME, device=resolved_device)
            logger.info("Embed model loaded")
        return self._embed_model

    def load_vad_model(self):
        if self._vad_model is None:
            logger.info("Loading VAD model: silero_vad")
            self._vad_model = load_silero_vad()
            logger.info("VAD model loaded")
        return self._vad_model

    def load_funasr_model(self):
        if self.funasr_model is None:
            resolved_device = _resolve_device(settings.ASR_DEVICE)
            logger.info(f"Loading FunASR offline model with punc/vad on device={resolved_device}")
            self.funasr_model = AutoModel(
                model=settings.ASR_MODEL_NAME,
                vad_model=settings.VAD_MODEL_NAME,
                punc_model=settings.PUNC_MODEL_NAME,
                sentence_timestamp=True,
                disable_update=True,
                device=resolved_device,
            )
            logger.info("FunASR offline model loaded")
        return self.funasr_model


model_hub = ModelHub()
