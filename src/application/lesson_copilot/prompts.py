import json

def build_decision_prompt(context, user_message, tools, tool_results) -> str:
    tool_lines = []
    for tool in tools:
        tool_lines.append(f"- {tool.name}: {tool.description}")

    result_lines = []
    for item in tool_results:
        if item.ok:
            result_lines.append(f"- {item.name}: {json.dumps(_summarize_tool_content(item.content), ensure_ascii=False)}")
        else:
            result_lines.append(f"- {item.name}: ERROR: {item.error}")

    if not result_lines:
        result_lines.append("- none")

    return f"""
You are a lesson copilot.

Current lesson:
- course_id: {context.course_id}
- lesson_id: {context.lesson_id}
- session_id: {context.session_id or "not available"}

User request:
{user_message}

Available tools:
{chr(10).join(tool_lines)}

Previous tool results:
{chr(10).join(result_lines)}

Rules:
1. When the user asks for lesson notes or a lesson summary, prefer reading an existing lesson note before generating a new one.
2. If enough information is available, return a final answer.
3. Reply to the user in the same language as the user request.
4. Keep tool arguments as an object. Use an empty object when no arguments are needed.
5. Return JSON only.
6. Use read-only tools first when they can answer the question.
7. Do not call session-specific tools when session_id is not available.
8. If the user explicitly asks for quiz questions, exercises, or self-check questions, use generate_lesson_quiz.
9. If the user explicitly asks for a structured lesson summary and the note is not enough, use generate_lesson_summary.
10. If the user asks to inspect transcripts, use get_lesson_transcripts or get_refined_lesson_transcripts.
11. If the user asks about videos or replay, use get_lesson_videos.
12. If the user asks about uploaded files or materials, use get_session_assets.
13. If the user asks a factual lesson question that requires retrieval, use query_lesson_knowledge with a query argument.
14. Include a short thought field that summarizes the current decision in one sentence. Keep it concise and operational.

Output JSON schema:
{{
  "action": "tool" | "final",
  "thought": "one-sentence reasoning summary",
  "tool_name": "tool name when action is tool",
  "arguments": {{}},
  "final_answer": "answer text when action is final"
}}
""".strip()


def _summarize_tool_content(content):
    if isinstance(content, dict):
        summary = {}
        for key in (
            "note_id",
            "status",
            "title",
            "summary",
            "overview",
            "count",
            "query",
            "answer",
            "course_id",
            "lesson_id",
            "session_id",
            "subject",
            "error_message",
        ):
            value = content.get(key)
            if value is not None:
                summary[key] = value
        for key in ("note", "items", "questions", "results", "citations", "key_points", "review_items", "important_terms"):
            value = content.get(key)
            if isinstance(value, list):
                summary[f"{key}_count"] = len(value)
                summary[key] = value[:3]
            elif isinstance(value, dict) and key == "note":
                overview = value.get("overview")
                if isinstance(overview, str) and overview.strip():
                    summary.setdefault("overview", overview.strip())
        metadata = content.get("metadata")
        if isinstance(metadata, dict):
            metadata_summary = {}
            for key in ("scope", "scope_label", "citation_count", "record_count", "question_count_generated"):
                value = metadata.get(key)
                if value is not None:
                    metadata_summary[key] = value
            if metadata_summary:
                summary["metadata"] = metadata_summary
        return summary or content
    return content
