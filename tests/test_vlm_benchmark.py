from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_IMAGE_PATH = ROOT / "img.png"
DEFAULT_MODEL_PATH = ROOT / "models" / "vlm" / "Qwen2.5-VL-3B-Instruct"
DEFAULT_MAX_IMAGE_SIZE = (960, 540)
DEFAULT_PROMPT = (
    "请识别并概括这块黑板区域中的板书、公式、图示和关键词。"
    "只输出可用于课堂检索的中文内容，不要描述相机画质。"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a local Qwen2.5-VL model on one image.")
    parser.add_argument("--image", default=str(DEFAULT_IMAGE_PATH), help="Input image path.")
    parser.add_argument("--model-path", default=str(DEFAULT_MODEL_PATH), help="Local VLM model directory.")
    parser.add_argument("--dtype", default="float16", help="Torch dtype: auto, float16, float32, bfloat16.")
    parser.add_argument("--device", default="auto", help="Target device: auto, cuda:0, cpu.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Generation max_new_tokens.")
    parser.add_argument("--max-image-width", type=int, default=DEFAULT_MAX_IMAGE_SIZE[0], help="Resize input image to this max width before inference.")
    parser.add_argument("--max-image-height", type=int, default=DEFAULT_MAX_IMAGE_SIZE[1], help="Resize input image to this max height before inference.")
    parser.add_argument("--warm-runs", type=int, default=1, help="Warm inference runs after the first run.")
    parser.add_argument("--output-json", default="", help="Optional JSON output file path.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt text used for image understanding.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_dependencies()

    image_path = Path(args.image).resolve()
    model_path = Path(args.model_path).resolve()
    if not image_path.exists():
        raise FileNotFoundError(f"image not found: {image_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"model path not found: {model_path}")

    from PIL import Image

    original_image = Image.open(image_path).convert("RGB")
    max_image_size = resolve_max_image_size(args.max_image_width, args.max_image_height)
    image = resize_image_for_benchmark(original_image, max_image_size)
    torch_module = safe_import_torch()
    device = resolve_device(torch_module, args.device)
    dtype = resolve_dtype(torch_module, args.dtype, device)

    startup = measure_startup(model_path, dtype, device)
    model = startup.pop("_model")
    processor = startup.pop("_processor")

    first_inference = measure_inference(
        model=model,
        processor=processor,
        image=image,
        prompt=args.prompt,
        max_new_tokens=args.max_new_tokens,
        device=device,
        torch_module=torch_module,
    )

    warm_runs: list[dict[str, Any]] = []
    for index in range(max(0, int(args.warm_runs))):
        metrics = measure_inference(
            model=model,
            processor=processor,
            image=image,
            prompt=args.prompt,
            max_new_tokens=args.max_new_tokens,
            device=device,
            torch_module=torch_module,
        )
        metrics["run_index"] = index + 1
        warm_runs.append(metrics)

    result = {
        "image_path": str(image_path),
        "image": {
            "original_size": list(original_image.size),
            "model_input_size": list(image.size),
            "max_size": list(max_image_size),
            "resized": image.size != original_image.size,
        },
        "model_path": str(model_path),
        "settings": {
            "dtype": args.dtype,
            "resolved_dtype": str(dtype),
            "device": args.device,
            "resolved_device": device,
            "max_new_tokens": args.max_new_tokens,
            "max_image_width": max_image_size[0],
            "max_image_height": max_image_size[1],
        },
        "torch": collect_torch_info(torch_module),
        "startup": startup,
        "first_inference": first_inference,
        "warm_inference_runs": warm_runs,
    }

    payload = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    print(payload)
    if args.output_json:
        Path(args.output_json).write_text(payload, encoding="utf-8")
    return 0


def resolve_max_image_size(width: int, height: int) -> tuple[int, int]:
    width = int(width)
    height = int(height)
    if width <= 0 or height <= 0:
        raise ValueError("--max-image-width and --max-image-height must be positive")
    return width, height


def resize_image_for_benchmark(image, max_size: tuple[int, int]):
    if image.width <= max_size[0] and image.height <= max_size[1]:
        return image

    from PIL import Image

    resized = image.copy()
    resampling = getattr(getattr(Image, "Resampling", None), "LANCZOS", None)
    if resampling is None:
        resampling = getattr(Image, "LANCZOS", 1)
    resized.thumbnail(max_size, resampling)
    return resized


def ensure_dependencies() -> None:
    missing: list[str] = []
    for module_name, package_name in (
        ("torch", "torch"),
        ("transformers", "transformers"),
        ("PIL", "Pillow"),
        ("qwen_vl_utils", "qwen-vl-utils"),
    ):
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    if missing:
        raise RuntimeError("missing Python packages: " + ", ".join(missing))


def measure_startup(model_path: Path, dtype, device: str) -> dict[str, Any]:
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    torch_module = safe_import_torch()
    reset_cuda_peak_memory(torch_module)
    start = time.perf_counter()
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        str(model_path),
        torch_dtype=dtype,
        device_map=device,
    )
    processor = AutoProcessor.from_pretrained(str(model_path), use_fast=True)
    synchronize_cuda(torch_module)
    elapsed = time.perf_counter() - start
    return {
        "seconds": round(elapsed, 3),
        "model_class": type(model).__name__,
        "processor_class": type(processor).__name__,
        "model_device": str(getattr(model, "device", "")),
        "hf_device_map": getattr(model, "hf_device_map", None),
        "cuda_memory": collect_cuda_memory(torch_module),
        "_model": model,
        "_processor": processor,
    }


def measure_inference(
    *,
    model,
    processor,
    image,
    prompt: str,
    max_new_tokens: int,
    device: str,
    torch_module,
) -> dict[str, Any]:
    from qwen_vl_utils import process_vision_info

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt},
            ],
        }
    ]
    prompt_text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(messages)
    inputs = processor(
        text=[prompt_text],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    )
    input_stats = collect_input_stats(inputs)

    if hasattr(inputs, "to"):
        inputs = inputs.to(device)

    reset_cuda_peak_memory(torch_module)
    start = time.perf_counter()
    generated_ids = model.generate(**inputs, max_new_tokens=max_new_tokens)
    synchronize_cuda(torch_module)
    elapsed = time.perf_counter() - start

    generated_trimmed = [
        output_ids[len(input_ids):]
        for input_ids, output_ids in zip(inputs.input_ids, generated_ids)
    ]
    output_text = processor.batch_decode(
        generated_trimmed,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False,
    )[0]

    lines = [line for line in str(output_text).splitlines() if line.strip()]
    return {
        "seconds": round(elapsed, 3),
        "text_length": len(output_text),
        "line_count": len(lines),
        "preview": lines[:12],
        "inputs": input_stats,
        "cuda_memory": collect_cuda_memory(torch_module),
    }


def collect_input_stats(inputs) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for key in ("input_ids", "attention_mask", "pixel_values", "image_grid_thw"):
        value = getattr(inputs, key, None)
        if value is None and isinstance(inputs, dict):
            value = inputs.get(key)
        if value is None:
            continue
        shape = getattr(value, "shape", None)
        stats[key] = {
            "shape": list(shape) if shape is not None else None,
            "numel": int(value.numel()) if hasattr(value, "numel") else None,
        }
    return stats


def collect_torch_info(torch_module) -> dict[str, Any]:
    if torch_module is None:
        return {"available": False}
    info: dict[str, Any] = {
        "available": True,
        "version": torch_module.__version__,
        "cuda_version": torch_module.version.cuda,
        "cuda_available": torch_module.cuda.is_available(),
        "device_count": torch_module.cuda.device_count(),
    }
    if torch_module.cuda.is_available():
        info["devices"] = [
            {
                "index": index,
                "name": torch_module.cuda.get_device_name(index),
                "total_memory_bytes": torch_module.cuda.get_device_properties(index).total_memory,
            }
            for index in range(torch_module.cuda.device_count())
        ]
    return info


def resolve_device(torch_module, configured: str) -> str:
    normalized = str(configured or "auto").strip().lower()
    if normalized != "auto":
        return configured
    if torch_module is not None and torch_module.cuda.is_available():
        return "cuda:0"
    return "cpu"


def resolve_dtype(torch_module, configured: str, device: str):
    normalized = str(configured or "auto").strip().lower()
    if normalized == "auto":
        if torch_module is not None and device.startswith("cuda"):
            return torch_module.float16
        return "auto"
    if torch_module is None:
        return normalized
    dtype = getattr(torch_module, normalized, None)
    if dtype is None:
        raise ValueError(f"unsupported dtype: {configured}")
    return dtype


def collect_cuda_memory(torch_module) -> dict[str, Any] | None:
    if torch_module is None or not torch_module.cuda.is_available():
        return None
    device = torch_module.cuda.current_device()
    return {
        "device_index": device,
        "allocated_bytes": torch_module.cuda.memory_allocated(device),
        "reserved_bytes": torch_module.cuda.memory_reserved(device),
        "max_allocated_bytes": torch_module.cuda.max_memory_allocated(device),
        "max_reserved_bytes": torch_module.cuda.max_memory_reserved(device),
    }


def reset_cuda_peak_memory(torch_module) -> None:
    if torch_module is None or not torch_module.cuda.is_available():
        return
    synchronize_cuda(torch_module)
    torch_module.cuda.reset_peak_memory_stats()


def synchronize_cuda(torch_module) -> None:
    if torch_module is None or not torch_module.cuda.is_available():
        return
    torch_module.cuda.synchronize()


def safe_import_torch():
    try:
        import torch
    except ImportError:
        return None
    return torch


if __name__ == "__main__":
    raise SystemExit(main())
