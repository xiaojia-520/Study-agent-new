from __future__ import annotations

from pathlib import Path

from huggingface_hub import snapshot_download
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
    }

    for path in targets.values():
        path.mkdir(parents=True, exist_ok=True)

    print("[4/5] Downloading embedding model...")
    if has_files(targets["embed"]):
        print("  - skip:", targets["embed"])
    else:
        snapshot_download(
            repo_id="BAAI/bge-small-zh-v1.5",
            local_dir=str(targets["embed"]),
            local_dir_use_symlinks=False,
        )
        print("  - done:", targets["embed"])

    print("[5/5] Downloading FunASR models...")
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

    print("")
    print("Model setup completed.")
    print("Embedding :", targets["embed"])
    print("ASR       :", targets["asr"])
    print("VAD       :", targets["vad"])
    print("PUNC      :", targets["punc"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
