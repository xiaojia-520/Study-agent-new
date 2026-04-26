@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo [1/5] Checking Python...
python --version >nul 2>nul
if errorlevel 1 (
    echo Python is not available in PATH.
    echo Install Python 3.10+ first, then rerun this script.
    exit /b 1
)

echo [2/5] Creating model directories...
if not exist "models\asr" mkdir "models\asr"
if not exist "models\vad" mkdir "models\vad"
if not exist "models\punc" mkdir "models\punc"
if not exist "models\embedding" mkdir "models\embedding"
if not exist "models\ocr" mkdir "models\ocr"
if not exist "models\vlm" mkdir "models\vlm"
if not exist "models\yolo" mkdir "models\yolo"

echo [3/5] Checking Python packages...
python -c "import accelerate, funasr, huggingface_hub, modelscope, paddle, paddleocr, qwen_vl_utils, sentence_transformers, ultralytics" >nul 2>nul
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

python scripts\setup_models.py
if errorlevel 1 (
    echo Model setup failed.
    exit /b 1
)

echo.
echo setup_model.bat finished successfully.
exit /b 0
