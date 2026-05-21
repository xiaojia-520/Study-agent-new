from __future__ import annotations

import multiprocessing as mp
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from multiprocessing.connection import Client, Listener
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol

from config.settings import settings
from src.domain.session import RealtimeSession
from src.infrastructure.logger import get_logger

if TYPE_CHECKING:
    from src.application.speech.pipeline import WebSpeechPipeline

logger = get_logger("AsrGateway")

AsrEventType = Literal[
    "session_ready",
    "partial_transcript",
    "final_transcript",
    "worker_error",
    "session_closed",
    "worker_status",
]
TextCallback = Callable[[str], None]
ErrorCallback = Callable[[Exception], None]


@dataclass(slots=True)
class AsrEvent:
    type: AsrEventType
    session_id: str
    text: str | None = None
    error: str | None = None


@dataclass(slots=True)
class AsrSessionCallbacks:
    on_partial: TextCallback
    on_final: TextCallback
    on_error: ErrorCallback | None = None


@dataclass(slots=True)
class AsrSessionHandle:
    session_id: str
    pipeline: WebSpeechPipeline | None = None
    closed_event: threading.Event = field(default_factory=threading.Event)

    def stop(self) -> None:
        if self.pipeline is not None:
            self.pipeline.stop()


@dataclass(frozen=True, slots=True)
class RemoteWorkerEndpoint:
    host: str
    port: int


class AsrGateway(Protocol):
    def open_session(self, session: RealtimeSession, callbacks: AsrSessionCallbacks) -> AsrSessionHandle: ...

    def push_audio(self, handle: AsrSessionHandle, audio_bytes: bytes) -> None: ...

    def close_session(self, handle: AsrSessionHandle) -> None: ...

    def status(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class InProcessAsrGateway:
    def open_session(self, session: RealtimeSession, callbacks: AsrSessionCallbacks) -> AsrSessionHandle:
        from src.application.speech.pipeline import WebSpeechPipeline

        pipeline = WebSpeechPipeline(
            on_partial=callbacks.on_partial,
            on_final=callbacks.on_final,
            model_name=session.model_name,
        )
        pipeline.start()
        return AsrSessionHandle(session_id=session.session_id, pipeline=pipeline)

    def push_audio(self, handle: AsrSessionHandle, audio_bytes: bytes) -> None:
        if handle.pipeline is None:
            raise RuntimeError("in-process ASR session has no pipeline")
        handle.pipeline.feed_audio_bytes(audio_bytes)

    def close_session(self, handle: AsrSessionHandle) -> None:
        handle.stop()
        handle.closed_event.set()

    def status(self) -> dict[str, object]:
        return {
            "backend": "inprocess",
            "healthy": True,
            "active_session_count": 0,
        }

    def close(self) -> None:
        return None


class ProcessAsrGateway:
    """Run realtime ASR pipelines in a dedicated worker process."""

    def __init__(
        self,
        *,
        queue_size: int = settings.ASR_WORKER_QUEUE_SIZE,
        close_timeout_seconds: float = settings.ASR_WORKER_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self.queue_size = max(1, int(queue_size))
        self.close_timeout_seconds = max(0.1, float(close_timeout_seconds))
        self._ctx = mp.get_context("spawn")
        self._command_q: mp.Queue = self._ctx.Queue(maxsize=self.queue_size)
        self._event_q: mp.Queue = self._ctx.Queue(maxsize=self.queue_size)
        self._process = self._ctx.Process(
            target=run_queue_worker,
            args=(self._command_q, self._event_q),
            daemon=False,
            name="study-agent-asr-worker",
        )
        self._callbacks: dict[str, AsrSessionCallbacks] = {}
        self._handles: dict[str, AsrSessionHandle] = {}
        self._status_requests: dict[str, queue.Queue[dict[str, object]]] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._reader = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="asr-worker-event-reader",
        )
        self._process.start()
        self._reader.start()

    def open_session(self, session: RealtimeSession, callbacks: AsrSessionCallbacks) -> AsrSessionHandle:
        handle = AsrSessionHandle(session_id=session.session_id)
        with self._lock:
            self._callbacks[session.session_id] = callbacks
            self._handles[session.session_id] = handle
        self._put_command(
            {
                "type": "open_session",
                "session_id": session.session_id,
                "model_name": session.model_name,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "subject": session.subject,
            }
        )
        return handle

    def push_audio(self, handle: AsrSessionHandle, audio_bytes: bytes) -> None:
        self._put_command(
            {
                "type": "push_audio",
                "session_id": handle.session_id,
                "audio": bytes(audio_bytes),
            }
        )

    def close_session(self, handle: AsrSessionHandle) -> None:
        self._put_command({"type": "close_session", "session_id": handle.session_id})
        handle.closed_event.wait(timeout=self.close_timeout_seconds)
        with self._lock:
            self._callbacks.pop(handle.session_id, None)
            self._handles.pop(handle.session_id, None)

    def status(self) -> dict[str, object]:
        request_id = _new_request_id()
        response_q: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        with self._lock:
            self._status_requests[request_id] = response_q

        try:
            self._put_command({"type": "status", "request_id": request_id})
            try:
                payload = response_q.get(timeout=1.0)
            except queue.Empty:
                return {
                    "backend": "process",
                    "healthy": False,
                    "error": "ASR worker status request timed out",
                    "process_alive": self._process.is_alive(),
                }
            payload["backend"] = "process"
            payload["healthy"] = True
            payload["process_alive"] = self._process.is_alive()
            return payload
        finally:
            with self._lock:
                self._status_requests.pop(request_id, None)

    def close(self) -> None:
        self._stop_event.set()
        try:
            self._put_command({"type": "shutdown"}, block=False)
        except RuntimeError:
            pass
        if self._reader.is_alive():
            self._reader.join(timeout=2.0)
        if self._process.is_alive():
            self._process.join(timeout=5.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2.0)

    def _put_command(self, payload: dict[str, object], *, block: bool = True) -> None:
        if not self._process.is_alive():
            raise RuntimeError("ASR worker process is not running")
        try:
            if block:
                self._command_q.put(payload, timeout=1.0)
            else:
                self._command_q.put_nowait(payload)
        except queue.Full as exc:
            raise RuntimeError("ASR worker command queue is full") from exc

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                raw_event = self._event_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if not isinstance(raw_event, dict):
                continue
            self._dispatch_event(raw_event)

    def _dispatch_event(self, raw_event: dict[str, object]) -> None:
        session_id = str(raw_event.get("session_id") or "")
        event_type = str(raw_event.get("type") or "")
        if event_type == "worker_status":
            self._resolve_status_request(raw_event)
            return
        if not session_id:
            return

        with self._lock:
            callbacks = self._callbacks.get(session_id)
            handle = self._handles.get(session_id)

        if event_type == "session_closed":
            if handle is not None:
                handle.closed_event.set()
            return

        if callbacks is None:
            return

        if event_type == "partial_transcript":
            text = str(raw_event.get("text") or "").strip()
            if text:
                callbacks.on_partial(text)
            return

        if event_type == "final_transcript":
            text = str(raw_event.get("text") or "").strip()
            if text:
                callbacks.on_final(text)
            return

        if event_type == "worker_error" and callbacks.on_error is not None:
            callbacks.on_error(RuntimeError(str(raw_event.get("error") or "ASR worker failed")))

    def _resolve_status_request(self, raw_event: dict[str, object]) -> None:
        request_id = str(raw_event.get("request_id") or "")
        if not request_id:
            return
        with self._lock:
            response_q = self._status_requests.get(request_id)
        if response_q is None:
            return
        try:
            response_q.put_nowait(dict(raw_event))
        except queue.Full:
            pass


class RemoteAsrGateway:
    """Connect the backend to an externally managed ASR worker process."""

    def __init__(
        self,
        *,
        host: str = settings.ASR_WORKER_HOST,
        port: int = settings.ASR_WORKER_PORT,
        auth_token: str = settings.ASR_WORKER_AUTH_TOKEN,
        connect_timeout_seconds: float = settings.ASR_WORKER_CONNECT_TIMEOUT_SECONDS,
        close_timeout_seconds: float = settings.ASR_WORKER_CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self.address = (host, int(port))
        self.authkey = str(auth_token).encode("utf-8")
        self.connect_timeout_seconds = max(0.1, float(connect_timeout_seconds))
        self.close_timeout_seconds = max(0.1, float(close_timeout_seconds))
        self._callbacks: dict[str, AsrSessionCallbacks] = {}
        self._handles: dict[str, AsrSessionHandle] = {}
        self._status_requests: dict[str, queue.Queue[dict[str, object]]] = {}
        self._lock = threading.RLock()
        self._send_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._connection = None
        self._reader = threading.Thread(
            target=self._reader_loop,
            daemon=True,
            name="asr-remote-event-reader",
        )
        self._connect()
        self._reader.start()

    def open_session(self, session: RealtimeSession, callbacks: AsrSessionCallbacks) -> AsrSessionHandle:
        handle = AsrSessionHandle(session_id=session.session_id)
        with self._lock:
            self._callbacks[session.session_id] = callbacks
            self._handles[session.session_id] = handle
        self._send(
            {
                "type": "open_session",
                "session_id": session.session_id,
                "model_name": session.model_name,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "subject": session.subject,
            }
        )
        return handle

    def push_audio(self, handle: AsrSessionHandle, audio_bytes: bytes) -> None:
        self._send(
            {
                "type": "push_audio",
                "session_id": handle.session_id,
                "audio": bytes(audio_bytes),
            }
        )

    def close_session(self, handle: AsrSessionHandle) -> None:
        self._send({"type": "close_session", "session_id": handle.session_id})
        handle.closed_event.wait(timeout=self.close_timeout_seconds)
        with self._lock:
            self._callbacks.pop(handle.session_id, None)
            self._handles.pop(handle.session_id, None)

    def status(self) -> dict[str, object]:
        request_id = _new_request_id()
        response_q: queue.Queue[dict[str, object]] = queue.Queue(maxsize=1)
        with self._lock:
            self._status_requests[request_id] = response_q

        try:
            self._send({"type": "status", "request_id": request_id})
            try:
                payload = response_q.get(timeout=1.0)
            except queue.Empty:
                return {
                    "backend": "remote",
                    "healthy": False,
                    "error": "ASR worker status request timed out",
                    "address": f"{self.address[0]}:{self.address[1]}",
                }
            payload["backend"] = "remote"
            payload["healthy"] = True
            payload["address"] = f"{self.address[0]}:{self.address[1]}"
            return payload
        except Exception as exc:
            return {
                "backend": "remote",
                "healthy": False,
                "error": str(exc),
                "address": f"{self.address[0]}:{self.address[1]}",
            }
        finally:
            with self._lock:
                self._status_requests.pop(request_id, None)

    def close(self) -> None:
        self._stop_event.set()
        if self._reader.is_alive():
            self._reader.join(timeout=2.0)
        connection = self._connection
        self._connection = None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _connect(self) -> None:
        deadline = time.monotonic() + self.connect_timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._connection = Client(self.address, authkey=self.authkey)
                logger.info("Connected to remote ASR worker at %s:%s", self.address[0], self.address[1])
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.2)
        message = f"failed to connect to ASR worker at {self.address[0]}:{self.address[1]}"
        raise RuntimeError(message) from last_error

    def _send(self, payload: dict[str, object]) -> None:
        connection = self._connection
        if connection is None:
            raise RuntimeError("ASR worker connection is not available")
        with self._send_lock:
            connection.send(payload)

    def _reader_loop(self) -> None:
        connection = self._connection
        if connection is None:
            return
        while not self._stop_event.is_set():
            try:
                if not connection.poll(0.2):
                    continue
                raw_event = connection.recv()
            except (EOFError, OSError):
                self._notify_disconnected()
                return
            if not isinstance(raw_event, dict):
                continue
            self._dispatch_event(raw_event)

    def _dispatch_event(self, raw_event: dict[str, object]) -> None:
        session_id = str(raw_event.get("session_id") or "")
        event_type = str(raw_event.get("type") or "")
        if event_type == "worker_status":
            self._resolve_status_request(raw_event)
            return
        if not session_id:
            return

        with self._lock:
            callbacks = self._callbacks.get(session_id)
            handle = self._handles.get(session_id)

        if event_type == "session_closed":
            if handle is not None:
                handle.closed_event.set()
            return

        if callbacks is None:
            return

        if event_type == "partial_transcript":
            text = str(raw_event.get("text") or "").strip()
            if text:
                callbacks.on_partial(text)
            return

        if event_type == "final_transcript":
            text = str(raw_event.get("text") or "").strip()
            if text:
                callbacks.on_final(text)
            return

        if event_type == "worker_error" and callbacks.on_error is not None:
            callbacks.on_error(RuntimeError(str(raw_event.get("error") or "ASR worker failed")))

    def _resolve_status_request(self, raw_event: dict[str, object]) -> None:
        request_id = str(raw_event.get("request_id") or "")
        if not request_id:
            return
        with self._lock:
            response_q = self._status_requests.get(request_id)
        if response_q is None:
            return
        try:
            response_q.put_nowait(dict(raw_event))
        except queue.Full:
            pass

    def _notify_disconnected(self) -> None:
        with self._lock:
            callbacks = list(self._callbacks.items())
            handles = list(self._handles.values())
            self._callbacks.clear()
            self._handles.clear()
        for handle in handles:
            handle.closed_event.set()
        for _, session_callbacks in callbacks:
            if session_callbacks.on_error is not None:
                session_callbacks.on_error(RuntimeError("remote ASR worker disconnected"))


@dataclass(slots=True)
class _RemoteWorkerSlot:
    endpoint: RemoteWorkerEndpoint
    gateway: AsrGateway
    active_sessions: set[str] = field(default_factory=set)


class RemoteAsrPoolGateway:
    """Route sessions across externally managed ASR workers with session affinity."""

    def __init__(
        self,
        *,
        endpoints: list[RemoteWorkerEndpoint],
        auth_token: str = settings.ASR_WORKER_AUTH_TOKEN,
        worker_factory: Callable[..., AsrGateway] = RemoteAsrGateway,
    ) -> None:
        if not endpoints:
            raise ValueError("at least one ASR worker endpoint is required")
        self._lock = threading.RLock()
        self._session_slots: dict[str, _RemoteWorkerSlot] = {}
        self._slots = [
            _RemoteWorkerSlot(
                endpoint=endpoint,
                gateway=worker_factory(
                    host=endpoint.host,
                    port=endpoint.port,
                    auth_token=auth_token,
                ),
            )
            for endpoint in endpoints
        ]

    def open_session(self, session: RealtimeSession, callbacks: AsrSessionCallbacks) -> AsrSessionHandle:
        with self._lock:
            slot = self._session_slots.get(session.session_id)
            if slot is None:
                slot = min(self._slots, key=lambda item: len(item.active_sessions))
                self._session_slots[session.session_id] = slot

        handle = slot.gateway.open_session(session, callbacks)
        with self._lock:
            slot.active_sessions.add(session.session_id)
        return handle

    def push_audio(self, handle: AsrSessionHandle, audio_bytes: bytes) -> None:
        slot = self._slot_for_session(handle.session_id)
        slot.gateway.push_audio(handle, audio_bytes)

    def close_session(self, handle: AsrSessionHandle) -> None:
        slot = self._slot_for_session(handle.session_id)
        try:
            slot.gateway.close_session(handle)
        finally:
            with self._lock:
                slot.active_sessions.discard(handle.session_id)
                self._session_slots.pop(handle.session_id, None)

    def status(self) -> dict[str, object]:
        worker_statuses: list[dict[str, object]] = []
        with self._lock:
            slots = list(self._slots)

        for index, slot in enumerate(slots):
            try:
                status = dict(slot.gateway.status())
            except Exception as exc:
                status = {"healthy": False, "error": str(exc)}
            status["worker_index"] = index
            status["configured_endpoint"] = f"{slot.endpoint.host}:{slot.endpoint.port}"
            status["assigned_session_count"] = len(slot.active_sessions)
            status["assigned_sessions"] = sorted(slot.active_sessions)
            worker_statuses.append(status)

        return {
            "backend": "remote_pool",
            "healthy": all(bool(item.get("healthy")) for item in worker_statuses),
            "worker_count": len(worker_statuses),
            "active_session_count": sum(len(slot.active_sessions) for slot in slots),
            "workers": worker_statuses,
        }

    def close(self) -> None:
        with self._lock:
            slots = list(self._slots)
            self._session_slots.clear()
            for slot in slots:
                slot.active_sessions.clear()

        for slot in slots:
            slot.gateway.close()

    def _slot_for_session(self, session_id: str) -> _RemoteWorkerSlot:
        with self._lock:
            slot = self._session_slots.get(session_id)
        if slot is None:
            raise RuntimeError(f"ASR session is not routed to a worker: {session_id}")
        return slot


def build_asr_gateway() -> AsrGateway:
    backend = settings.ASR_RUNTIME_BACKEND.strip().lower()
    if backend in {"", "inprocess", "inline"}:
        return InProcessAsrGateway()
    if backend in {"process", "worker"}:
        return ProcessAsrGateway()
    if backend in {"remote", "external", "client"}:
        endpoints = parse_remote_worker_endpoints(settings.ASR_WORKER_ENDPOINTS)
        if endpoints:
            return RemoteAsrPoolGateway(endpoints=endpoints)
        return RemoteAsrGateway()
    raise ValueError(f"unsupported ASR_RUNTIME_BACKEND: {settings.ASR_RUNTIME_BACKEND}")


def _new_request_id() -> str:
    return f"{time.monotonic_ns()}-{threading.get_ident()}"


def parse_remote_worker_endpoints(raw_value: str) -> list[RemoteWorkerEndpoint]:
    endpoints: list[RemoteWorkerEndpoint] = []
    for raw_item in raw_value.replace(";", ",").split(","):
        item = raw_item.strip()
        if not item:
            continue
        host, separator, port_text = item.rpartition(":")
        if not separator or not host.strip() or not port_text.strip():
            raise ValueError(f"invalid ASR worker endpoint: {item!r}; expected host:port")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise ValueError(f"invalid ASR worker endpoint port: {item!r}") from exc
        endpoints.append(RemoteWorkerEndpoint(host=host.strip(), port=port))
    return endpoints


def _warmup_asr_worker_models() -> dict[str, object]:
    model_key = "paraformer-zh-streaming-2pass"
    started_at = time.monotonic()
    status: dict[str, object] = {
        "enabled": True,
        "model_key": model_key,
        "offline_model": bool(settings.ASR_WARMUP_OFFLINE_MODEL),
        "ok": False,
    }
    try:
        from src.core.asr.realtime_models import resolve_realtime_asr_model
        from src.infrastructure.model_hub import model_hub

        warmup_model = resolve_realtime_asr_model(model_key)
        logger.info("ASR worker warmup: loading %s from %s", warmup_model.key, warmup_model.resolved_model_name)
        model_hub.load_asr_model(model_name=warmup_model.resolved_model_name)
        if settings.ASR_WARMUP_OFFLINE_MODEL:
            logger.info("ASR worker warmup: loading offline second-pass model")
            model_hub.load_funasr_model()
        status.update(
            {
                "ok": True,
                "resolved_model_name": warmup_model.resolved_model_name,
                "seconds": round(time.monotonic() - started_at, 3),
            }
        )
        logger.info("ASR worker warmup complete in %.3fs", status["seconds"])
    except Exception as exc:
        status.update(
            {
                "error": str(exc),
                "seconds": round(time.monotonic() - started_at, 3),
            }
        )
        logger.exception("ASR worker warmup failed")
    return status


def run_queue_worker(command_q, event_q) -> None:
    serve_asr_commands(
        command_reader=command_q.get,
        emit=lambda payload: event_q.put(payload),
    )


def run_remote_worker_server(
    *,
    host: str = settings.ASR_WORKER_HOST,
    port: int = settings.ASR_WORKER_PORT,
    auth_token: str = settings.ASR_WORKER_AUTH_TOKEN,
) -> None:
    address = (host, int(port))
    authkey = str(auth_token).encode("utf-8")
    listener = Listener(address, authkey=authkey)
    logger.info("ASR worker listening on %s:%s pid=%s", host, port, os.getpid())
    try:
        while True:
            connection = listener.accept()
            logger.info("ASR worker accepted controller connection from %s", listener.last_accepted)
            try:
                serve_asr_commands(
                    command_reader=connection.recv,
                    emit=lambda payload, conn=connection: conn.send(payload),
                )
            except EOFError:
                logger.info("ASR worker controller disconnected")
            finally:
                try:
                    connection.close()
                except Exception:
                    pass
    finally:
        listener.close()


def serve_asr_commands(
    *,
    command_reader: Callable[[], object],
    emit: Callable[[dict[str, object]], None],
    warmup_on_start: bool = True,
) -> None:
    pipelines: dict[str, Any] = {}
    started_at = time.monotonic()
    warmup_status = _warmup_asr_worker_models() if warmup_on_start else {"enabled": False}

    def publish(
        event_type: AsrEventType,
        session_id: str,
        *,
        text: str | None = None,
        error: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "type": event_type,
            "session_id": session_id,
            "text": text,
            "error": error,
            "timestamp": int(time.time()),
        }
        if extra:
            payload.update(extra)
        emit(payload)

    def close_pipeline(session_id: str) -> None:
        pipeline = pipelines.pop(session_id, None)
        if pipeline is not None:
            pipeline.stop()
        publish("session_closed", session_id)

    while True:
        command = command_reader()
        if not isinstance(command, dict):
            continue
        command_type = str(command.get("type") or "")
        session_id = str(command.get("session_id") or "")

        try:
            if command_type == "shutdown":
                for active_session_id in list(pipelines):
                    close_pipeline(active_session_id)
                return

            if command_type == "status":
                request_id = str(command.get("request_id") or "")
                publish(
                    "worker_status",
                    "",
                    extra={
                        "request_id": request_id,
                        "pid": os.getpid(),
                        "active_session_count": len(pipelines),
                        "active_sessions": sorted(pipelines.keys()),
                        "uptime_seconds": round(time.monotonic() - started_at, 3),
                        "warmup": warmup_status,
                    },
                )
                continue

            if command_type == "open_session":
                if not session_id:
                    continue
                existing = pipelines.pop(session_id, None)
                if existing is not None:
                    existing.stop()
                from src.application.speech.pipeline import WebSpeechPipeline

                pipeline = WebSpeechPipeline(
                    on_partial=lambda text, sid=session_id: publish("partial_transcript", sid, text=text),
                    on_final=lambda text, sid=session_id: publish("final_transcript", sid, text=text),
                    model_name=str(command.get("model_name") or "") or None,
                )
                pipeline.start()
                pipelines[session_id] = pipeline
                publish("session_ready", session_id)
                continue

            if command_type == "push_audio":
                pipeline = pipelines.get(session_id)
                if pipeline is None:
                    publish("worker_error", session_id, error="ASR session is not open")
                    continue
                audio = command.get("audio")
                if isinstance(audio, bytes):
                    pipeline.feed_audio_bytes(audio)
                continue

            if command_type == "close_session":
                if session_id:
                    close_pipeline(session_id)
                continue
        except Exception as exc:
            if session_id:
                publish("worker_error", session_id, error=str(exc))
            logger.exception("ASR worker command failed")
