from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from src.core.knowledge.document_models import KnowledgeAnswer
from web.backend.app.domain.session import RealtimeSession
from web.backend.app.services.session_rag_query_service import QueryScope, SessionRagQueryService


@dataclass(slots=True)
class EvalCase:
    case_id: str
    query: str
    scope: QueryScope = QueryScope.GLOBAL
    session_id: str = "eval-session"
    course_id: str | None = None
    lesson_id: str | None = None
    subject: str | None = None
    with_llm: bool | None = None
    top_k: int | None = None
    expected_substrings: tuple[str, ...] = ()
    forbidden_substrings: tuple[str, ...] = ()
    min_results: int = 0
    require_answer: bool = False
    require_citations: bool = False
    metadata: dict[str, object] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object], *, fallback_index: int) -> "EvalCase":
        query = _require_text(payload.get("query"), "query")
        scope_raw = str(payload.get("scope") or QueryScope.GLOBAL.value).strip()
        scope = QueryScope(scope_raw)
        case_id = str(payload.get("id") or payload.get("case_id") or f"case-{fallback_index}").strip()
        if not case_id:
            case_id = f"case-{fallback_index}"

        session_id = str(payload.get("session_id") or "eval-session").strip() or "eval-session"
        course_id = _optional_text(payload.get("course_id"))
        lesson_id = _optional_text(payload.get("lesson_id"))
        subject = _optional_text(payload.get("subject"))
        with_llm = _optional_bool(payload.get("with_llm"), "with_llm")
        top_k = _optional_int(payload.get("top_k"), "top_k")
        min_results = _optional_int(payload.get("min_results"), "min_results") or 0
        require_answer = bool(payload.get("require_answer", False))
        require_citations = bool(payload.get("require_citations", False))

        if scope in {QueryScope.CURRENT_LESSON, QueryScope.COURSE_HISTORY}:
            if not course_id or not lesson_id:
                raise ValueError(f"{case_id}: course_id and lesson_id are required for scope={scope.value}")
        if scope is QueryScope.COURSE_ALL and not course_id:
            raise ValueError(f"{case_id}: course_id is required for scope={scope.value}")
        if min_results < 0:
            raise ValueError(f"{case_id}: min_results must be >= 0")
        if top_k is not None and top_k <= 0:
            raise ValueError(f"{case_id}: top_k must be > 0 when provided")

        return cls(
            case_id=case_id,
            query=query,
            scope=scope,
            session_id=session_id,
            course_id=course_id,
            lesson_id=lesson_id,
            subject=subject,
            with_llm=with_llm,
            top_k=top_k,
            expected_substrings=_normalize_string_list(payload.get("expected_substrings")),
            forbidden_substrings=_normalize_string_list(payload.get("forbidden_substrings")),
            min_results=min_results,
            require_answer=require_answer,
            require_citations=require_citations,
            metadata=_extract_metadata(payload),
        )

    def build_session(self) -> RealtimeSession:
        course_id = self.course_id or "eval-course"
        lesson_id = self.lesson_id or f"{course_id}-lesson"
        return RealtimeSession(
            session_id=self.session_id,
            course_id=course_id,
            lesson_id=lesson_id,
            subject=self.subject or course_id,
            created_at=0,
            updated_at=0,
        )


@dataclass(slots=True)
class EvalCaseResult:
    case_id: str
    query: str
    scope: str
    passed: bool
    with_llm: bool
    top_k: int | None
    answer: str | None
    answer_strategy: str | None
    result_count: int
    citation_count: int
    failure_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "query": self.query,
            "scope": self.scope,
            "passed": self.passed,
            "with_llm": self.with_llm,
            "top_k": self.top_k,
            "answer": self.answer,
            "answer_strategy": self.answer_strategy,
            "result_count": self.result_count,
            "citation_count": self.citation_count,
            "failure_reasons": list(self.failure_reasons),
            "metadata": dict(self.metadata),
        }


def load_eval_cases(path: Path) -> list[EvalCase]:
    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(target)

    cases: list[EvalCase] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"eval case at {target}:{line_number} must be a JSON object")
            try:
                cases.append(EvalCase.from_dict(payload, fallback_index=line_number))
            except ValueError as exc:
                raise ValueError(f"invalid eval case at {target}:{line_number}: {exc}") from exc
    return cases


def evaluate_cases(
    cases: Sequence[EvalCase],
    *,
    service: SessionRagQueryService,
    default_with_llm: bool = False,
    default_top_k: int | None = None,
) -> list[EvalCaseResult]:
    return [
        evaluate_case(
            case,
            service=service,
            default_with_llm=default_with_llm,
            default_top_k=default_top_k,
        )
        for case in cases
    ]


def evaluate_case(
    case: EvalCase,
    *,
    service: SessionRagQueryService,
    default_with_llm: bool = False,
    default_top_k: int | None = None,
) -> EvalCaseResult:
    requested_with_llm = default_with_llm if case.with_llm is None else case.with_llm
    requested_top_k = case.top_k if case.top_k is not None else default_top_k

    answer = service.query_session(
        session_id=case.session_id,
        query_text=case.query,
        scope=case.scope,
        top_k=requested_top_k,
        with_llm=requested_with_llm,
    )
    return score_eval_case(
        case,
        answer,
        with_llm=requested_with_llm,
        top_k=requested_top_k,
    )


def score_eval_case(
    case: EvalCase,
    answer: KnowledgeAnswer,
    *,
    with_llm: bool,
    top_k: int | None,
) -> EvalCaseResult:
    failure_reasons: list[str] = []
    answer_text = (answer.answer or "").strip() or None
    answer_strategy = _optional_text(answer.metadata.get("answer_strategy"))
    citation_count = len(answer.citations)
    result_count = len(answer.results)

    if case.require_answer and not answer_text:
        failure_reasons.append("answer is required but missing")
    if case.require_citations and citation_count <= 0:
        failure_reasons.append("citations are required but missing")
    if result_count < case.min_results:
        failure_reasons.append(f"expected at least {case.min_results} results, got {result_count}")

    target_text = answer_text or "\n".join(result.content for result in answer.results)
    normalized_target = _normalize_text(target_text)

    for expected in case.expected_substrings:
        if _normalize_text(expected) not in normalized_target:
            failure_reasons.append(f"missing expected substring: {expected}")
    for forbidden in case.forbidden_substrings:
        if _normalize_text(forbidden) in normalized_target:
            failure_reasons.append(f"found forbidden substring: {forbidden}")

    return EvalCaseResult(
        case_id=case.case_id,
        query=case.query,
        scope=case.scope.value,
        passed=not failure_reasons,
        with_llm=with_llm,
        top_k=top_k,
        answer=answer_text,
        answer_strategy=answer_strategy,
        result_count=result_count,
        citation_count=citation_count,
        failure_reasons=failure_reasons,
        metadata=dict(answer.metadata),
    )


def build_session_registry(cases: Iterable[EvalCase]) -> dict[str, RealtimeSession]:
    registry: dict[str, RealtimeSession] = {}
    for case in cases:
        registry[case.session_id] = case.build_session()
    return registry


def _require_text(value: object, field_name: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ValueError(f"{field_name} is required")
    return text


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer when provided") from exc


def _optional_bool(value: object, field_name: str) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise ValueError(f"{field_name} must be a boolean when provided")


def _normalize_string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    normalized: list[str] = []
    for item in value:
        text = _optional_text(item)
        if text is not None:
            normalized.append(text)
    return tuple(normalized)


def _extract_metadata(payload: Mapping[str, object]) -> dict[str, object]:
    ignored_keys = {
        "id",
        "case_id",
        "query",
        "scope",
        "session_id",
        "course_id",
        "lesson_id",
        "subject",
        "with_llm",
        "top_k",
        "expected_substrings",
        "forbidden_substrings",
        "min_results",
        "require_answer",
        "require_citations",
    }
    return {str(key): value for key, value in payload.items() if key not in ignored_keys}


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())
