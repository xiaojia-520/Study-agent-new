from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Mapping, Protocol

from PIL import Image

from config.settings import settings
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.realtime_rag_indexer import realtime_rag_indexer
from web.backend.app.services.transcript_service import transcript_service

logger = logging.getLogger(__name__)

os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "0")


class RegionTextExtractor(Protocol):
    def extract_text(self, image: Image.Image) -> str: ...


@dataclass(frozen=True, slots=True)
class VisionRegion:
    x: float
    y: float
    w: float
    h: float


@dataclass(slots=True)
class VisionRegionResult:
    region: str
    text: str = ""
    status: str = "skipped"
    chunk_id: int | None = None
    record_id: int | None = None
    error_message: str | None = None


class SessionVisionService:
    """Process classroom camera frames with user-selected regions."""

    def __init__(
        self,
        *,
        ocr_extractor: RegionTextExtractor | None = None,
        vlm_extractor: RegionTextExtractor | None = None,
        transcript_writer=transcript_service,
        rag_indexer=realtime_rag_indexer,
    ) -> None:
        self.ocr_extractor = ocr_extractor or LocalPaddleOcrExtractor()
        self.vlm_extractor = vlm_extractor or LocalQwenVlExtractor()
        self.transcript_writer = transcript_writer
        self.rag_indexer = rag_indexer
        self._last_hash_by_region: dict[tuple[str, str], str] = {}
        self._lock = threading.RLock()
        self._processing_lock = threading.Lock()

    def process_frame(
        self,
        *,
        session: RealtimeSession,
        image_bytes: bytes,
        regions: Mapping[str, Any],
        timestamp_ms: int | None = None,
        captured_at_ms: int | None = None,
    ) -> dict[str, Any]:
        if not image_bytes:
            raise ValueError("vision frame image is empty")
        if not regions:
            raise ValueError("at least one vision region is required")

        if not self._processing_lock.acquire(blocking=False):
            return {
                "session_id": session.session_id,
                "course_id": session.course_id,
                "lesson_id": session.lesson_id,
                "timestamp_ms": timestamp_ms,
                "captured_at_ms": captured_at_ms,
                "record_count": 0,
                "busy": True,
                "results": [asdict(item) for item in (
                    VisionRegionResult(
                        region=str(region_name),
                        status="busy",
                        error_message="vision parser is busy; frame skipped",
                    )
                    for region_name in regions
                    if region_name in {"ppt", "blackboard"}
                )],
            }

        try:
            image = Image.open(BytesIO(image_bytes)).convert("RGB")
            results: list[VisionRegionResult] = []
            records: list[dict[str, Any]] = []
            next_chunk_id = self.transcript_writer.next_chunk_id(session.session_id)

            for region_name in ("ppt", "blackboard"):
                if region_name not in regions:
                    continue

                result = VisionRegionResult(region=region_name)
                try:
                    region = _parse_region(regions[region_name])
                    crop = _crop_region(image, region)
                    extractor = self.ocr_extractor if region_name == "ppt" else self.vlm_extractor
                    text = _normalize_text(extractor.extract_text(crop))
                    result.text = text
                    if not text:
                        result.status = "empty"
                        results.append(result)
                        continue

                    text_hash = _hash_text(text)
                    if self._is_duplicate(session.session_id, region_name, text_hash):
                        result.status = "duplicate"
                        results.append(result)
                        continue

                    record = self._build_record(
                        session=session,
                        region_name=region_name,
                        region=region,
                        text=text,
                    chunk_id=next_chunk_id,
                    timestamp_ms=timestamp_ms,
                    captured_at_ms=captured_at_ms,
                    image_size=image.size,
                )
                    record_id = self.transcript_writer.append_transcript_record(record)
                    self.rag_indexer.append_record(session, record)
                    self._remember_hash(session.session_id, region_name, text_hash)

                    result.status = "indexed"
                    result.chunk_id = next_chunk_id
                    result.record_id = record_id
                    records.append(record)
                    next_chunk_id += 1
                except Exception as exc:
                    logger.exception("Failed to process vision region %s: %s", region_name, exc)
                    result.status = "failed"
                    result.error_message = str(exc)

                results.append(result)

            if records:
                self._flush_rag_session(session.session_id)

            return {
                "session_id": session.session_id,
                "course_id": session.course_id,
                "lesson_id": session.lesson_id,
                "timestamp_ms": timestamp_ms,
                "captured_at_ms": captured_at_ms,
                "record_count": len(records),
                "busy": False,
                "results": [asdict(item) for item in results],
            }
        finally:
            self._processing_lock.release()

    def _build_record(
        self,
        *,
        session: RealtimeSession,
        region_name: str,
        region: VisionRegion,
        text: str,
        chunk_id: int,
        timestamp_ms: int | None,
        captured_at_ms: int | None,
        image_size: tuple[int, int],
    ) -> dict[str, Any]:
        label = "PPT投影区" if region_name == "ppt" else "黑板区"
        prefixed_text = f"{label}：{text}"
        created_at = _created_at_from_capture(captured_at_ms)
        return {
            "session_id": session.session_id,
            "storage_id": f"vision-{session.session_id}",
            "course_id": session.course_id,
            "lesson_id": session.lesson_id,
            "chunk_id": chunk_id,
            "subject": session.subject or "classroom vision",
            "source_type": "video",
            "source_file": "camera-frame",
            "start_ms": timestamp_ms,
            "end_ms": timestamp_ms,
            "text": prefixed_text,
            "clean_text": prefixed_text,
            "created_at": created_at,
            "metadata": {
                "parser": "manual_roi_ocr_vlm",
                "region": region_name,
                "region_x": region.x,
                "region_y": region.y,
                "region_w": region.w,
                "region_h": region.h,
                "frame_width": image_size[0],
                "frame_height": image_size[1],
                "frame_timestamp_ms": timestamp_ms,
                "frame_captured_at_ms": captured_at_ms,
                "frame_captured_at": created_at,
            },
        }

    def _is_duplicate(self, session_id: str, region_name: str, text_hash: str) -> bool:
        with self._lock:
            return self._last_hash_by_region.get((session_id, region_name)) == text_hash

    def _remember_hash(self, session_id: str, region_name: str, text_hash: str) -> None:
        with self._lock:
            self._last_hash_by_region[(session_id, region_name)] = text_hash

    def _flush_rag_session(self, session_id: str) -> None:
        flush_session = getattr(self.rag_indexer, "flush_session", None)
        if callable(flush_session):
            flush_session(session_id)


class LocalPaddleOcrExtractor:
    def __init__(self) -> None:
        self._engine = None
        self._lock = threading.RLock()

    def extract_text(self, image: Image.Image) -> str:
        engine = self._get_engine()
        try:
            import numpy as np
        except ImportError as exc:
            raise ImportError("numpy is required for local OCR") from exc

        array = np.asarray(image.convert("RGB"))
        predict = getattr(engine, "predict", None)
        if callable(predict):
            raw_result = predict(array)
        else:
            raw_result = engine.ocr(array, cls=settings.OCR_USE_TEXTLINE_ORIENTATION)
        return _normalize_text("\n".join(_extract_ocr_texts(raw_result)))

    def _get_engine(self):
        with self._lock:
            if self._engine is not None:
                return self._engine

            try:
                from paddleocr import PaddleOCR
            except ImportError as exc:
                raise ImportError("paddleocr is required for local PPT OCR") from exc

            errors: list[str] = []
            for kwargs in (self._build_v3_kwargs(), self._build_v2_kwargs(), {"lang": "ch"}):
                try:
                    self._engine = PaddleOCR(**kwargs)
                    return self._engine
                except (TypeError, ValueError) as exc:
                    errors.append(str(exc))
                    logger.warning("PaddleOCR init failed with args %s: %s", sorted(kwargs), exc)
            raise RuntimeError("failed to initialize PaddleOCR: " + " | ".join(errors))

    @staticmethod
    def _build_v3_kwargs() -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "lang": "ch",
            "use_doc_orientation_classify": settings.OCR_USE_DOC_ORIENTATION_CLASSIFY,
            "use_doc_unwarping": settings.OCR_USE_DOC_UNWARPING,
            "use_textline_orientation": settings.OCR_USE_TEXTLINE_ORIENTATION,
        }
        if settings.OCR_DET_MODEL_NAME.exists():
            kwargs["text_detection_model_name"] = settings.OCR_DET_MODEL_NAME.name
            kwargs["text_detection_model_dir"] = str(settings.OCR_DET_MODEL_NAME)
        if settings.OCR_REC_MODEL_NAME.exists():
            kwargs["text_recognition_model_name"] = settings.OCR_REC_MODEL_NAME.name
            kwargs["text_recognition_model_dir"] = str(settings.OCR_REC_MODEL_NAME)
        return kwargs

    @staticmethod
    def _build_v2_kwargs() -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "lang": "ch",
            "use_angle_cls": settings.OCR_USE_TEXTLINE_ORIENTATION,
        }
        if settings.OCR_DET_MODEL_NAME.exists():
            kwargs["det_model_dir"] = str(settings.OCR_DET_MODEL_NAME)
        if settings.OCR_REC_MODEL_NAME.exists():
            kwargs["rec_model_dir"] = str(settings.OCR_REC_MODEL_NAME)
        return kwargs


class LocalQwenVlExtractor:
    def __init__(self) -> None:
        self._model = None
        self._processor = None
        self._lock = threading.RLock()

    def extract_text(self, image: Image.Image) -> str:
        model, processor = self._get_runtime()
        try:
            from qwen_vl_utils import process_vision_info
        except ImportError as exc:
            raise ImportError("qwen-vl-utils is required for local blackboard VLM parsing") from exc

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {
                        "type": "text",
                        "text": (
                            "请识别并概括这块黑板区域中的板书、公式、图示和关键词。"
                            "只输出可用于课堂检索的中文内容，不要描述相机画质。"
                        ),
                    },
                ],
            }
        ]
        prompt = processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(
            text=[prompt],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        )
        target_device = getattr(model, "device", None)
        if target_device is not None and hasattr(inputs, "to"):
            inputs = inputs.to(target_device)

        generated_ids = model.generate(
            **inputs,
            max_new_tokens=settings.VLM_MAX_NEW_TOKENS,
        )
        generated_trimmed = [
            output_ids[len(input_ids):]
            for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
        ]
        output_text = processor.batch_decode(
            generated_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]
        return _normalize_text(output_text)

    def _get_runtime(self):
        with self._lock:
            if self._model is not None and self._processor is not None:
                return self._model, self._processor

            if not settings.VLM_MODEL_NAME.exists():
                raise FileNotFoundError(f"VLM model path does not exist: {settings.VLM_MODEL_NAME}")

            try:
                from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
            except ImportError as exc:
                raise ImportError("transformers with Qwen2.5-VL support is required") from exc

            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                str(settings.VLM_MODEL_NAME),
                torch_dtype="auto",
                device_map=settings.VLM_DEVICE_MAP,
            )
            self._processor = AutoProcessor.from_pretrained(str(settings.VLM_MODEL_NAME))
            return self._model, self._processor


def _parse_region(value: Any) -> VisionRegion:
    if not isinstance(value, Mapping):
        raise ValueError("vision region must be an object")
    region = VisionRegion(
        x=float(value.get("x")),
        y=float(value.get("y")),
        w=float(value.get("w")),
        h=float(value.get("h")),
    )
    if region.w <= 0 or region.h <= 0:
        raise ValueError("vision region width and height must be greater than 0")
    if region.x < 0 or region.y < 0 or region.x + region.w > 1 or region.y + region.h > 1:
        raise ValueError("vision region must use normalized coordinates within [0, 1]")
    return region


def _crop_region(image: Image.Image, region: VisionRegion) -> Image.Image:
    width, height = image.size
    left = max(0, min(width - 1, round(region.x * width)))
    top = max(0, min(height - 1, round(region.y * height)))
    right = max(left + 1, min(width, round((region.x + region.w) * width)))
    bottom = max(top + 1, min(height, round((region.y + region.h) * height)))
    return image.crop((left, top, right, bottom))


def _extract_ocr_texts(value: Any) -> list[str]:
    texts: list[str] = []
    _collect_ocr_texts(value, texts)
    normalized: list[str] = []
    seen: set[str] = set()
    for text in texts:
        clean = _normalize_text(text)
        if not clean or clean in seen:
            continue
        normalized.append(clean)
        seen.add(clean)
    return normalized


def _collect_ocr_texts(value: Any, texts: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        texts.append(value)
        return
    json_payload = getattr(value, "json", None)
    if callable(json_payload):
        json_payload = json_payload()
    if isinstance(json_payload, Mapping):
        _collect_ocr_texts(json_payload, texts)
        return
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        _collect_ocr_texts(to_dict(), texts)
        return
    to_json = getattr(value, "to_json", None)
    if callable(to_json):
        _collect_ocr_texts(to_json(), texts)
        return
    if isinstance(value, Mapping):
        collected = False
        for key in ("rec_texts", "texts"):
            item = value.get(key)
            if isinstance(item, list):
                texts.extend(str(text) for text in item if str(text).strip())
                collected = True
        for key in ("text", "label"):
            item = value.get(key)
            if isinstance(item, str):
                texts.append(item)
                collected = True
        if collected:
            return
        for item in value.values():
            _collect_ocr_texts(item, texts)
        return
    if isinstance(value, tuple):
        if value and isinstance(value[0], str):
            texts.append(value[0])
            return
        for item in value:
            _collect_ocr_texts(item, texts)
        return
    if isinstance(value, list):
        for item in value:
            _collect_ocr_texts(item, texts)


def _normalize_text(value: str) -> str:
    lines = [" ".join(line.strip().split()) for line in str(value or "").splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _hash_text(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def _created_at_from_capture(captured_at_ms: int | None) -> int:
    if captured_at_ms is None:
        return int(time.time())
    try:
        value = int(captured_at_ms)
    except (TypeError, ValueError):
        return int(time.time())
    if value <= 0:
        return int(time.time())
    return value // 1000


session_vision_service = SessionVisionService()
