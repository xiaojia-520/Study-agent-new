from __future__ import annotations

from pathlib import Path

from huggingface_hub import hf_hub_download, snapshot_download
from modelscope import snapshot_download as ms_snapshot_download


def has_files(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    targets = {
        "embed": root / "models" / "embedding" / "bge-small-zh-v1.5",
        "asr": root / "models" / "asr" / "speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
        "vad": root / "models" / "vad" / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
        "punc": root / "models" / "punc" / "punc_ct-transformer_cn-en-common-vocab471067-large",
        "yolo_dir": root / "models" / "yolo",
        "ocr_det": root / "models" / "ocr" / "PP-OCRv5_mobile_det",
        "ocr_rec": root / "models" / "ocr" / "PP-OCRv5_mobile_rec",
        "qwen_vl": root / "models" / "vlm" / "Qwen2.5-VL-7B-Instruct",
    }
    yolo11_weight_path = targets["yolo_dir"] / "yolo11s.pt"

    for path in targets.values():
        path.mkdir(parents=True, exist_ok=True)

    print("[4/8] Downloading embedding model...")
    if has_files(targets["embed"]):
        print("  - skip:", targets["embed"])
    else:
        snapshot_download(
            repo_id="BAAI/bge-small-zh-v1.5",
            local_dir=str(targets["embed"]),
            local_dir_use_symlinks=False,
        )
        print("  - done:", targets["embed"])

    print("[5/8] Downloading FunASR models...")
    ms_models = [
        (
            "damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            targets["asr"],
        ),
        ("damo/speech_fsmn_vad_zh-cn-16k-common-pytorch", targets["vad"]),
        ("damo/punc_ct-transformer_cn-en-common-vocab471067-large", targets["punc"]),
    ]
    for model_id, target_dir in ms_models:
        if has_files(target_dir):
            print("  - skip:", target_dir)
            continue
        ms_snapshot_download(model_id, local_dir=str(target_dir))
        print("  - done:", target_dir)

    print("[6/8] Downloading YOLO11 detection model...")
    if yolo11_weight_path.exists():
        print("  - skip:", yolo11_weight_path)
    else:
        hf_hub_download(
            repo_id="Ultralytics/YOLO11",
            filename=yolo11_weight_path.name,
            local_dir=str(targets["yolo_dir"]),
            local_dir_use_symlinks=False,
        )
        print("  - done:", yolo11_weight_path)

    print("[7/8] Downloading PaddleOCR models...")
    hf_models = [
        ("PaddlePaddle/PP-OCRv5_mobile_det", targets["ocr_det"]),
        ("PaddlePaddle/PP-OCRv5_mobile_rec", targets["ocr_rec"]),
    ]
    for model_id, target_dir in hf_models:
        if has_files(target_dir):
            print("  - skip:", target_dir)
            continue
        snapshot_download(
            repo_id=model_id,
            local_dir=str(target_dir),
            local_dir_use_symlinks=False,
        )
        print("  - done:", target_dir)

    print("[8/8] Downloading Qwen2.5-VL model...")
    if has_files(targets["qwen_vl"]):
        print("  - skip:", targets["qwen_vl"])
    else:
        snapshot_download(
            repo_id="Qwen/Qwen2.5-VL-7B-Instruct",
            local_dir=str(targets["qwen_vl"]),
            local_dir_use_symlinks=False,
        )
        print("  - done:", targets["qwen_vl"])

    print("")
    print("Model setup completed.")
    print("Embedding :", targets["embed"])
    print("ASR       :", targets["asr"])
    print("VAD       :", targets["vad"])
    print("PUNC      :", targets["punc"])
    print("YOLO11    :", yolo11_weight_path)
    print("OCR DET   :", targets["ocr_det"])
    print("OCR REC   :", targets["ocr_rec"])
    print("QWEN VL   :", targets["qwen_vl"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
