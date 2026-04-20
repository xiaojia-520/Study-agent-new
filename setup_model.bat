@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0"

echo [1/5] Checking Python...
python --version >nul 2>nul
if errorlevel 1 (
    echo Python is not available in PATH.
    echo Install Python 3.10+ first, then rerun this script.
    exit /b 1
)

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "MODEL_DIR=%ROOT_DIR%\models"
set "ASR_DIR=%MODEL_DIR%\asr\speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
set "VAD_DIR=%MODEL_DIR%\vad\speech_fsmn_vad_zh-cn-16k-common-pytorch"
set "PUNC_DIR=%MODEL_DIR%\punc\punc_ct-transformer_cn-en-common-vocab471067-large"
set "EMBED_DIR=%MODEL_DIR%\embedding\bge-small-zh-v1.5"

echo [2/5] Creating model directories...
if not exist "%MODEL_DIR%\asr" mkdir "%MODEL_DIR%\asr"
if not exist "%MODEL_DIR%\vad" mkdir "%MODEL_DIR%\vad"
if not exist "%MODEL_DIR%\punc" mkdir "%MODEL_DIR%\punc"
if not exist "%MODEL_DIR%\embedding" mkdir "%MODEL_DIR%\embedding"

echo [3/5] Checking Python packages...
python -c "import funasr, sentence_transformers, huggingface_hub, modelscope" >nul 2>nul
if errorlevel 1 (
    echo Installing required packages...
    python -m pip install -U pip
    if errorlevel 1 exit /b 1
    python -m pip install -r requirements-rag.txt huggingface_hub modelscope
    if errorlevel 1 (
        echo Failed to install required packages.
        exit /b 1
    )
)

set "TMP_PY=%TEMP%\setup_models_%RANDOM%%RANDOM%.py"
> "%TMP_PY%" (
    echo from pathlib import Path
    echo import sys
    echo from huggingface_hub import snapshot_download
    echo from modelscope import snapshot_download as ms_snapshot_download
    echo.
    echo root = Path(r"%ROOT_DIR%")
    echo targets = {
    echo     "embed": root / "models" / "embedding" / "bge-small-zh-v1.5",
    echo     "asr": root / "models" / "asr" / "speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    echo     "vad": root / "models" / "vad" / "speech_fsmn_vad_zh-cn-16k-common-pytorch",
    echo     "punc": root / "models" / "punc" / "punc_ct-transformer_cn-en-common-vocab471067-large",
    echo }
    echo for path in targets.values():
    echo     path.mkdir(parents=True, exist_ok=True)
    echo.
    echo def has_files(path: Path) -> bool:
    echo     return any(path.iterdir())
    echo.
    echo print("[4/5] Downloading embedding model...")
    echo if has_files(targets["embed"]):
    echo     print("  - skip:", targets["embed"])
    echo else:
    echo     snapshot_download(
    echo         repo_id="BAAI/bge-small-zh-v1.5",
    echo         local_dir=str(targets["embed"]),
    echo         local_dir_use_symlinks=False,
    echo     )
    echo     print("  - done:", targets["embed"])
    echo.
    echo print("[5/5] Downloading FunASR models...")
    echo ms_models = [
    echo     ("damo/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch", targets["asr"]),
    echo     ("damo/speech_fsmn_vad_zh-cn-16k-common-pytorch", targets["vad"]),
    echo     ("damo/punc_ct-transformer_cn-en-common-vocab471067-large", targets["punc"]),
    echo ]
    echo for model_id, target_dir in ms_models:
    echo     if has_files(target_dir):
    echo         print("  - skip:", target_dir)
    echo         continue
    echo     ms_snapshot_download(model_id, local_dir=str(target_dir))
    echo     print("  - done:", target_dir)
    echo.
    echo print("")
    echo print("Model setup completed.")
    echo print("Embedding :", targets["embed"])
    echo print("ASR       :", targets["asr"])
    echo print("VAD       :", targets["vad"])
    echo print("PUNC      :", targets["punc"])
)

python "%TMP_PY%"
set "EXIT_CODE=%ERRORLEVEL%"
del "%TMP_PY%" >nul 2>nul

if not "%EXIT_CODE%"=="0" (
    echo Model setup failed.
    exit /b %EXIT_CODE%
)

echo.
echo setup_model.bat finished successfully.
exit /b 0
