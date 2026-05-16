from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from src.application.container import ApplicationServices
from web.backend.app.dependencies import get_backend_services
from web.backend.app.execution import run_blocking
from web.backend.app.presenters import (
    group_query_result_items,
    query_citation_response_item,
    query_result_response_item,
)
from web.backend.app.schemas import SessionQueryRequest, SessionQuizRequest, SessionSummaryRequest

router = APIRouter(prefix="/sessions", tags=["learning"])


@router.post("/{session_id}/query")
async def query_session(
    session_id: str,
    payload: SessionQueryRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    try:
        answer = await run_blocking(
            services.session_rag_query.query_session,
            session_id=session_id,
            query_text=payload.query,
            scope=payload.scope,
            top_k=payload.top_k,
            with_llm=payload.with_llm,
            include_rag_context=payload.include_rag_context,
            classroom_context_mode=payload.classroom_context_mode,
            asset_ids=payload.asset_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    classifier = services.session_rag_query.classify_source_kind
    metadata = dict(answer.metadata)
    result_items = [query_result_response_item(result, classifier) for result in answer.results]
    citation_items = [query_citation_response_item(citation, classifier) for citation in answer.citations]
    return {
        "query": answer.query,
        "answer": answer.answer,
        "results": result_items,
        "grouped_results": group_query_result_items(result_items),
        "citations": citation_items,
        "metadata": metadata,
        "scope": metadata.get("scope"),
        "session_id": metadata.get("session_id"),
        "course_id": metadata.get("course_id"),
        "lesson_id": metadata.get("lesson_id"),
    }


@router.post("/{session_id}/summary")
async def summarize_session(
    session_id: str,
    payload: SessionSummaryRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    try:
        summary = await run_blocking(
            services.lesson_summary.generate_summary,
            session_id=session_id,
            focus=payload.focus,
            max_items=payload.max_items,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session transcript not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "session_id": summary.session_id,
        "course_id": summary.course_id,
        "lesson_id": summary.lesson_id,
        "subject": summary.subject,
        "summary": summary.summary,
        "key_points": list(summary.key_points),
        "review_items": list(summary.review_items),
        "important_terms": [asdict(item) for item in summary.important_terms],
        "metadata": dict(summary.metadata),
    }


@router.post("/{session_id}/quiz")
async def generate_session_quiz(
    session_id: str,
    payload: SessionQuizRequest,
    services: ApplicationServices = Depends(get_backend_services),
):
    try:
        quiz = await run_blocking(
            services.lesson_quiz.generate_quiz,
            session_id=session_id,
            focus=payload.focus,
            question_count=payload.question_count,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"session transcript not found: {session_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "session_id": quiz.session_id,
        "course_id": quiz.course_id,
        "lesson_id": quiz.lesson_id,
        "subject": quiz.subject,
        "questions": [asdict(item) for item in quiz.questions],
        "metadata": dict(quiz.metadata),
    }
