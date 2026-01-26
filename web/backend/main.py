import asyncio
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from src.application.speech_pipeline import WebSpeechPipeline

import time, numpy as np

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _make_sender(websocket: WebSocket, loop: asyncio.AbstractEventLoop) -> Callable[[str, str], None]:
    def _send(message_type: str, text: str) -> None:
        if not text:
            return
        payload = {"type": message_type, "text": text}
        asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)

    return _send


@app.get("/")
async def root():
    return {"status": "ok"}


@app.websocket("/ws/audio")
async def ws_audio(websocket: WebSocket):
    last = 0.0
    await websocket.accept()
    loop = asyncio.get_running_loop()
    sender = _make_sender(websocket, loop)

    pipeline = WebSpeechPipeline(
        on_partial=lambda text: sender("partial", text),
        on_final=lambda text: sender("final", text),
    )
    pipeline.start()

    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                audio = np.frombuffer(message["bytes"], dtype=np.float32)
                now = time.monotonic()
                if now - last > 1.0:
                    rms = float(np.sqrt(np.mean(audio * audio)))
                    peak = float(np.max(np.abs(audio)))
                    print("rms=", rms, "peak=", peak)
                    last = now
                await asyncio.to_thread(pipeline.feed_audio_bytes, message["bytes"])
            elif message.get("text"):
                if message["text"].strip().lower() == "ping":
                    await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        pipeline.stop()