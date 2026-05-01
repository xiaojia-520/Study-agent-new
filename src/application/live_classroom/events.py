from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.domain.session import RealtimeSession


@dataclass(frozen=True, slots=True)
class TranscriptFinalized:
    session: RealtimeSession
    record: Mapping[str, Any]
