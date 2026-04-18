from __future__ import annotations

from typing import Iterable

from src.core.knowledge.document_models import AnswerCitation


RAG_CITED_ANSWER_SYSTEM_PROMPT = """You are a retrieval-grounded study assistant.

Answer the user's question using only the retrieved context blocks provided below.
Rules:
- Do not invent facts that are not supported by the retrieved context.
- If the context is insufficient, say so plainly.
- Keep the answer concise and directly useful for studying.
- Cite factual statements inline using square-bracket citations like [1] or [1][2].
- Only cite citation numbers that exist in the provided context.
- Prefer the same language as the user's question. Default to Simplified Chinese when unclear.
"""

NO_CONTEXT_ANSWER = "I could not find enough relevant transcript context to answer this question reliably."


def build_rag_cited_answer_prompt(
    *,
    question: str,
    scope_label: str,
    citations: Iterable[AnswerCitation],
) -> str:
    context_blocks = []
    for citation in citations:
        course_id = citation.course_id or "-"
        lesson_id = citation.lesson_id or "-"
        subject = citation.subject or "-"
        score = f"{citation.score:.3f}" if citation.score is not None else "-"
        context_blocks.append(
            "\n".join(
                [
                    f"[{citation.index}] doc_id={citation.doc_id}",
                    f"subject={subject}",
                    f"course_id={course_id}",
                    f"lesson_id={lesson_id}",
                    f"score={score}",
                    citation.snippet,
                ]
            )
        )

    joined_context = "\n\n".join(context_blocks)
    return "\n\n".join(
        [
            RAG_CITED_ANSWER_SYSTEM_PROMPT.strip(),
            f"Question: {question.strip()}",
            f"Query scope: {scope_label}",
            "Retrieved context blocks:",
            joined_context or "[no context retrieved]",
            "Write the final answer only. Do not output JSON or any extra headings.",
        ]
    )


LESSON_SUMMARY_JSON_SCHEMA = """{
  "summary": "2-4 sentence lesson summary",
  "key_points": ["key point 1", "key point 2"],
  "review_items": ["review item 1", "review item 2"],
  "important_terms": [
    {"term": "term", "definition": "short definition"}
  ]
}"""

LESSON_SUMMARY_SYSTEM_PROMPT = """You are a study assistant that converts lesson transcripts into structured study notes.

Rules:
- Use only information supported by the transcript.
- Keep the summary concise and study-oriented.
- Key points should capture the main ideas or conclusions from the lesson.
- Review items should list concepts the learner should revisit or memorize.
- Important terms should contain short definitions grounded in the transcript.
- Prefer the same language as the transcript. Default to Simplified Chinese when unclear.
- Return valid JSON only. Do not wrap it in markdown fences.
"""


def build_lesson_summary_chunk_prompt(
    *,
    transcript_chunk: str,
    chunk_index: int,
    chunk_count: int,
    max_items: int,
    focus: str | None = None,
) -> str:
    focus_line = f"Focus instruction: {focus.strip()}" if focus and focus.strip() else "Focus instruction: none"
    return "\n\n".join(
        [
            LESSON_SUMMARY_SYSTEM_PROMPT.strip(),
            f"Transcript chunk: {chunk_index}/{chunk_count}",
            focus_line,
            f"Return at most {max_items} key points, {max_items} review items, and {max_items} important terms.",
            "JSON schema:",
            LESSON_SUMMARY_JSON_SCHEMA,
            "Transcript:",
            transcript_chunk.strip(),
        ]
    )


def build_lesson_summary_merge_prompt(
    *,
    chunk_summaries_json: str,
    max_items: int,
    focus: str | None = None,
) -> str:
    focus_line = f"Focus instruction: {focus.strip()}" if focus and focus.strip() else "Focus instruction: none"
    return "\n\n".join(
        [
            LESSON_SUMMARY_SYSTEM_PROMPT.strip(),
            focus_line,
            f"Merge the chunk summaries into one final lesson note with at most {max_items} key points, "
            f"{max_items} review items, and {max_items} important terms.",
            "Deduplicate overlapping ideas and keep the final answer coherent.",
            "JSON schema:",
            LESSON_SUMMARY_JSON_SCHEMA,
            "Chunk summaries JSON:",
            chunk_summaries_json.strip(),
        ]
    )


LESSON_QUIZ_JSON_SCHEMA = """{
  "questions": [
    {
      "question": "question text",
      "question_type": "multiple_choice",
      "options": ["option A", "option B", "option C", "option D"],
      "answer": "correct answer text",
      "explanation": "why this answer is correct"
    }
  ]
}"""

LESSON_QUIZ_SYSTEM_PROMPT = """You are a study assistant that turns lesson transcripts into practice questions.

Rules:
- Use only information supported by the transcript.
- Prefer clear, teachable questions over tricky questions.
- Generate concise explanations grounded in the transcript.
- Use the same language as the transcript. Default to Simplified Chinese when unclear.
- Return valid JSON only. Do not wrap it in markdown fences.
- If the transcript is too thin, return fewer questions instead of inventing content.
"""


def build_lesson_quiz_chunk_prompt(
    *,
    transcript_chunk: str,
    chunk_index: int,
    chunk_count: int,
    question_count: int,
    focus: str | None = None,
) -> str:
    focus_line = f"Focus instruction: {focus.strip()}" if focus and focus.strip() else "Focus instruction: none"
    return "\n\n".join(
        [
            LESSON_QUIZ_SYSTEM_PROMPT.strip(),
            f"Transcript chunk: {chunk_index}/{chunk_count}",
            focus_line,
            f"Generate up to {question_count} questions from this transcript chunk.",
            "Prefer a mix of multiple choice and short answer when appropriate.",
            "JSON schema:",
            LESSON_QUIZ_JSON_SCHEMA,
            "Transcript:",
            transcript_chunk.strip(),
        ]
    )


def build_lesson_quiz_merge_prompt(
    *,
    chunk_quizzes_json: str,
    question_count: int,
    focus: str | None = None,
) -> str:
    focus_line = f"Focus instruction: {focus.strip()}" if focus and focus.strip() else "Focus instruction: none"
    return "\n\n".join(
        [
            LESSON_QUIZ_SYSTEM_PROMPT.strip(),
            focus_line,
            f"Merge the chunk-level questions into one final quiz with at most {question_count} questions.",
            "Remove duplicates and keep the strongest, most useful questions.",
            "JSON schema:",
            LESSON_QUIZ_JSON_SCHEMA,
            "Chunk quizzes JSON:",
            chunk_quizzes_json.strip(),
        ]
    )
