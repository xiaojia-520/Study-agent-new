from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.application.speech_pipeline import WebSpeechPipeline
from web.backend.app.services.session_manager import session_manager

router = APIRouter(tags=["realtime-audio"])


def _make_event_payload(
    *,
    session_id: str,
    seq: int,
    event_type: str,
    text: str | None = None,
    is_final: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": event_type,
        "session_id": session_id,
        "seq": seq,
        "is_final": is_final,
        "timestamp": int(time.time()),
    }
    if text is not None:
        payload["text"] = text
    if extra:
        payload.update(extra)
    return payload


def _make_sender(websocket: WebSocket, loop: asyncio.AbstractEventLoop, session_id: str):
    def _send(event_type: str, text: str, *, is_final: bool) -> None:
        if not text:
            return
        seq = session_manager.next_event_seq(session_id)
        payload = _make_event_payload(
            session_id=session_id,
            seq=seq,
            event_type=event_type,
            text=text,
            is_final=is_final,
        )
        asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)

    return _send


@router.websocket("/ws/audio/{session_id}")
async def ws_audio(websocket: WebSocket, session_id: str):
    session = session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="session not found")
        return

    await websocket.accept()
    session_manager.mark_connected(session_id)

    loop = asyncio.get_running_loop()
    sender = _make_sender(websocket, loop, session_id)
    pipeline = WebSpeechPipeline(
        on_partial=lambda text: sender("partial_transcript", text, is_final=False),
        on_final=lambda text: sender("final_transcript", text, is_final=True),
        model_name=session.model_name,
    )
    pipeline.start()

    started_seq = session_manager.next_event_seq(session_id)
    await websocket.send_json(
        _make_event_payload(
            session_id=session_id,
            seq=started_seq,
            event_type="session_started",
            extra={
                "status": session.status.value,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "model_name": session.model_name,
            },
        )
    )

    last_metrics_at = 0.0
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                session_manager.mark_running(session_id)
                audio = np.frombuffer(message["bytes"], dtype=np.float32)
                now = time.monotonic()
                if audio.size > 0 and now - last_metrics_at >= 1.0:
                    peak = float(np.max(np.abs(audio)))
                    rms = float(np.sqrt(np.mean(audio * audio)))
                    last_metrics_at = now
                    seq = session_manager.next_event_seq(session_id)
                    await websocket.send_json(
                        _make_event_payload(
                            session_id=session_id,
                            seq=seq,
                            event_type="audio_metrics",
                            extra={"peak": peak, "rms": rms},
                        )
                    )
                await asyncio.to_thread(pipeline.feed_audio_bytes, message["bytes"])
            elif message.get("text"):
                text = message["text"].strip().lower()
                if text == "ping":
                    await websocket.send_json(
                        _make_event_payload(
                            session_id=session_id,
                            seq=session_manager.next_event_seq(session_id),
                            event_type="pong",
                        )
                    )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        session_manager.mark_error(session_id, str(exc))
        try:
            await websocket.send_json(
                _make_event_payload(
                    session_id=session_id,
                    seq=session_manager.next_event_seq(session_id),
                    event_type="session_error",
                    extra={"error": str(exc)},
                )
            )
        except Exception:
            pass
    finally:
        pipeline.stop()
        session = session_manager.mark_disconnected(session_id)
        if session is not None:
            try:
                await websocket.send_json(
                    _make_event_payload(
                        session_id=session_id,
                        seq=session_manager.next_event_seq(session_id),
                        event_type="session_stopped",
                        extra={"status": session.status.value},
                    )
                )
            except Exception:
                pass
