from starlette.routing import Match

from web.backend.app.api.http_sessions import router


def _first_full_match(path: str, method: str = "GET"):
    scope = {
        "type": "http",
        "path": path,
        "method": method,
        "root_path": "",
        "scheme": "http",
        "query_string": b"",
        "headers": [],
        "app": None,
    }
    for route in router.routes:
        match, _ = route.matches(scope)
        if match == Match.FULL:
            return route
    raise AssertionError(f"no route matched {method} {path}")


def test_history_transcripts_route_matches_history_endpoint_first():
    route = _first_full_match("/sessions/history/transcripts")
    assert route.endpoint.__module__ == "web.backend.app.api.history"
    assert route.endpoint.__name__ == "get_lesson_transcripts"


def test_history_messages_route_matches_history_endpoint_first():
    route = _first_full_match("/sessions/history/messages")
    assert route.endpoint.__module__ == "web.backend.app.api.history"
    assert route.endpoint.__name__ == "get_lesson_messages"
