from __future__ import annotations

from dataclasses import dataclass

from config.settings import settings


@dataclass(frozen=True, slots=True)
class RealtimeASRModel:
    key: str
    folder: str
    resolved_model_name: str


def list_realtime_asr_model_keys() -> tuple[str, ...]:
    return tuple(settings.ASR_MODEL_PATH.keys())


def resolve_realtime_asr_model(model_key: str | None) -> RealtimeASRModel:
    resolved_key = model_key or settings.ASR_DEFAULT_MODEL_KEY
    folder = settings.ASR_MODEL_PATH.get(resolved_key)
    if folder is None:
        supported_keys = ", ".join(list_realtime_asr_model_keys())
        raise ValueError(f"unsupported realtime ASR model: {resolved_key}. supported: {supported_keys}")
    return RealtimeASRModel(
        key=resolved_key,
        folder=folder,
        resolved_model_name=str(settings.ASR_LOCAL_MODEL_PATH / folder),
    )
