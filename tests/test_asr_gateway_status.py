from src.application.speech.asr_gateway import (
    AsrSessionCallbacks,
    AsrSessionHandle,
    RemoteAsrPoolGateway,
    RemoteAsrGateway,
    RemoteWorkerEndpoint,
    _address_label,
    _socket_address,
    parse_remote_worker_endpoints,
    serve_asr_commands,
)
from src.domain.session import RealtimeSession


def test_serve_asr_commands_reports_worker_status_without_session() -> None:
    commands = iter(
        [
            {"type": "status", "request_id": "status-1"},
            {"type": "shutdown"},
        ]
    )
    events = []

    serve_asr_commands(
        command_reader=lambda: next(commands),
        emit=events.append,
    )

    assert events[0]["type"] == "worker_status"
    assert events[0]["request_id"] == "status-1"
    assert events[0]["active_session_count"] == 0
    assert events[0]["active_sessions"] == []


def test_parse_remote_worker_endpoints() -> None:
    endpoints = parse_remote_worker_endpoints("127.0.0.1:8765, 127.0.0.1:8766")

    assert endpoints == [
        RemoteWorkerEndpoint("127.0.0.1", 8765),
        RemoteWorkerEndpoint("127.0.0.1", 8766),
    ]


def test_parse_remote_worker_endpoints_supports_ipv6() -> None:
    endpoints = parse_remote_worker_endpoints("[2409:8a00:2452:390:9505:5687:781f:506f]:8765")

    assert endpoints == [
        RemoteWorkerEndpoint("2409:8a00:2452:390:9505:5687:781f:506f", 8765),
    ]


def test_socket_address_formats_ipv6_for_multiprocessing_connection() -> None:
    address = _socket_address("2409:8a00:2452:390:9505:5687:781f:506f", 8765)

    assert address == ("2409:8a00:2452:390:9505:5687:781f:506f", 8765, 0, 0)
    assert _address_label(address) == "[2409:8a00:2452:390:9505:5687:781f:506f]:8765"


def test_remote_pool_routes_sessions_with_affinity() -> None:
    workers = []

    class FakeWorker:
        def __init__(self, *, host: str, port: int, auth_token: str) -> None:
            self.host = host
            self.port = port
            self.auth_token = auth_token
            self.opened = []
            self.audio = []
            self.closed = []
            workers.append(self)

        def open_session(self, session, callbacks):
            self.opened.append(session.session_id)
            return AsrSessionHandle(session_id=session.session_id)

        def push_audio(self, handle, audio_bytes: bytes) -> None:
            self.audio.append((handle.session_id, audio_bytes))

        def close_session(self, handle) -> None:
            self.closed.append(handle.session_id)

        def status(self) -> dict[str, object]:
            return {"healthy": True, "backend": "fake"}

        def close(self) -> None:
            pass

    gateway = RemoteAsrPoolGateway(
        endpoints=[
            RemoteWorkerEndpoint("127.0.0.1", 9001),
            RemoteWorkerEndpoint("127.0.0.1", 9002),
        ],
        auth_token="token",
        worker_factory=FakeWorker,
    )
    callbacks = AsrSessionCallbacks(on_partial=lambda _: None, on_final=lambda _: None)

    first = gateway.open_session(
        RealtimeSession(session_id="session-a", course_id="c", lesson_id="l"),
        callbacks,
    )
    second = gateway.open_session(
        RealtimeSession(session_id="session-b", course_id="c", lesson_id="l"),
        callbacks,
    )

    gateway.push_audio(first, b"a")
    gateway.push_audio(second, b"b")

    assert workers[0].opened == ["session-a"]
    assert workers[1].opened == ["session-b"]
    assert workers[0].audio == [("session-a", b"a")]
    assert workers[1].audio == [("session-b", b"b")]

    status = gateway.status()
    assert status["backend"] == "remote_pool"
    assert status["worker_count"] == 2
    assert status["active_session_count"] == 2


def test_remote_gateway_uses_ipv6_socket_address() -> None:
    gateway = RemoteAsrGateway.__new__(RemoteAsrGateway)
    gateway.address = _socket_address("2409:8a00:2452:390:9505:5687:781f:506f", 8765)

    assert gateway.address == ("2409:8a00:2452:390:9505:5687:781f:506f", 8765, 0, 0)
