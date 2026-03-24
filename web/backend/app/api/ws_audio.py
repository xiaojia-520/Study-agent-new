from __future__ import annotations

import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from web.backend.app.services.realtime_speech_service import realtime_speech_service
from web.backend.app.services.session_manager import session_manager

router = APIRouter(tags=["realtime-audio"])


@router.websocket("/ws/audio/{session_id}")
async def ws_audio(websocket: WebSocket, session_id: str):
    session = session_manager.get_session(session_id)
    if session is None:
        await websocket.close(code=4404, reason="session not found")
        return

    await websocket.accept()
    session_manager.mark_connected(session_id)

    loop = asyncio.get_running_loop()
    pipeline = realtime_speech_service.create_pipeline(
        websocket=websocket,
        loop=loop,
        session=session,
    )
    await websocket.send_json(await realtime_speech_service.make_session_started_payload(session))

    last_metrics_at = 0.0
    try:
        while True:
            message = await websocket.receive()
            if message.get("bytes"):
                last_metrics_at, metrics_payload = await realtime_speech_service.process_audio_message(
                    session_id=session_id,
                    audio_bytes=message["bytes"],
                    pipeline=pipeline,
                    last_metrics_at=last_metrics_at,
                )
                if metrics_payload is not None:
                    await websocket.send_json(metrics_payload)
            elif message.get("text"):
                text = message["text"].strip().lower()
                if text == "ping":
                    await websocket.send_json(await realtime_speech_service.make_pong_payload(session_id))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket.send_json(await realtime_speech_service.make_error_payload(session_id, exc))
        except Exception:
            pass
    finally:
        stopped_payload = await realtime_speech_service.shutdown_session(session_id, pipeline)
        if stopped_payload is not None:
            try:
                await websocket.send_json(stopped_payload)
            except Exception:
                pass
