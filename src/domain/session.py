from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SessionStatus(str, Enum):
    IDLE = "idle"
    CONNECTED = "connected"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(slots=True)
class RealtimeSession:
    session_id: str
    course_id: str
    lesson_id: str
    subject: Optional[str] = None
    client_id: Optional[str] = None
    sample_rate: int = 16000
    channels: int = 1
    model_name: Optional[str] = None
    status: SessionStatus = SessionStatus.IDLE
    active_connections: int = 0
    created_at: int = 0
    updated_at: int = 0
    last_error: Optional[str] = None
    event_seq: int = field(default=0, repr=False)
