from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable


SendJson = Callable[[dict[str, Any]], Awaitable[None]]


class RealtimeEventPublisher:
    def __init__(self, *, sequence_getter: Callable[[str], int]) -> None:
        self.sequence_getter = sequence_getter

    def make_event_payload(
        self,
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

    def make_sender(
        self,
        *,
        send_json: SendJson,
        loop: asyncio.AbstractEventLoop,
        session_id: str,
    ) -> Callable[..., None]:
        def _send(event_type: str, text: str, *, is_final: bool) -> None:
            if not text:
                return
            seq = self.sequence_getter(session_id)
            payload = self.make_event_payload(
                session_id=session_id,
                seq=seq,
                event_type=event_type,
                text=text,
                is_final=is_final,
            )
            asyncio.run_coroutine_threadsafe(send_json(payload), loop)

        return _send
