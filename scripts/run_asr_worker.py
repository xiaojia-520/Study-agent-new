from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.settings import settings
from src.application.speech.asr_gateway import run_remote_worker_server


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the standalone Study Agent ASR worker.")
    parser.add_argument("--host", default=settings.ASR_WORKER_HOST, help="Bind host for the ASR worker listener.")
    parser.add_argument("--port", type=int, default=settings.ASR_WORKER_PORT, help="Bind port for the ASR worker listener.")
    parser.add_argument(
        "--auth-token",
        default=settings.ASR_WORKER_AUTH_TOKEN,
        help="Authentication token shared with the backend gateway.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_remote_worker_server(
        host=args.host,
        port=args.port,
        auth_token=args.auth_token,
    )


if __name__ == "__main__":
    main()
