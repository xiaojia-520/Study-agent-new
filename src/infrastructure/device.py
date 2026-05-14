from __future__ import annotations


def is_cuda_available() -> bool:
    try:
        import torch
    except ImportError:
        return False

    return bool(torch.cuda.is_available())


def resolve_device(requested: str | None) -> str:
    device = (requested or "").strip().lower()
    cuda_available = is_cuda_available()
    if not device or device == "auto":
        return "cuda" if cuda_available else "cpu"
    if device.startswith("cuda") and not cuda_available:
        return "cpu"
    return device
