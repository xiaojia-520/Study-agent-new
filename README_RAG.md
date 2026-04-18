# RAG Runtime

This repository includes a minimal runnable `LlamaIndex + Qdrant` RAG path for transcript indexing and querying.

## Default runtime mode

- Embedding model: local `sentence-transformers` model from `config.settings.RAG_EMBED_MODEL_NAME`
- Qdrant: local embedded storage under `data/qdrant/` by default
- LLM answer generation: optional, controlled by `RAG_ENABLE_LLM`
- Realtime indexing: enabled by default for websocket final transcripts, with buffered flush thresholds

## Configuration

Edit [config/.env](/E:/Study-agent-new-master/config/.env) or export environment variables.

Important keys:

- `RAG_QDRANT_PREFER_LOCAL`
- `RAG_QDRANT_LOCAL_PATH`
- `RAG_TRANSCRIPT_ROOT`
- `RAG_EMBED_MODEL_NAME`
- `RAG_ENABLE_LLM`
- `RAG_LLM_PROVIDER`
- `RAG_LLM_MODEL`
- `RAG_LLM_API_KEY`
- `RAG_LLM_API_BASE`
- `RAG_REALTIME_INDEXING_ENABLED`
- `RAG_REALTIME_FLUSH_RECORDS`
- `RAG_REALTIME_FLUSH_CHARS`
- `RAG_REALTIME_FLUSH_INTERVAL_SECONDS`

## Build the index

```powershell
python scripts/rag_build_index.py --path data/transcripts/demo_session_for_check.jsonl --recreate
```

## Retrieval-only query

```powershell
python scripts/rag_query.py "What is the first point?" --reindex-path data/transcripts/demo_session_for_check.jsonl --recreate
```

## LLM answer mode

Enable `RAG_ENABLE_LLM=true` and set OpenAI-compatible config first, then run:

```powershell
python scripts/rag_query.py "What does this lesson explain?" --with-llm
```

## Minimal evaluation set

Use the demo fixture transcript and cases to establish a repeatable baseline:

```powershell
python scripts/rag_eval.py `
  --cases tests/fixtures/rag_eval_demo_cases.jsonl `
  --reindex-path tests/fixtures/rag_eval_demo_transcript.jsonl `
  --recreate
```

If you also want to evaluate answer generation, enable your LLM config and run:

```powershell
python scripts/rag_eval.py `
  --cases tests/fixtures/rag_eval_demo_cases_llm.jsonl `
  --reindex-path tests/fixtures/rag_eval_demo_transcript.jsonl `
  --recreate `
  --with-llm
```

Each case in the JSONL file can set:

- `query`
- `scope`
- `session_id`
- `course_id`
- `lesson_id`
- `with_llm`
- `top_k`
- `expected_substrings`
- `forbidden_substrings`
- `min_results`
- `require_answer`
- `require_citations`

## Quasi-realtime indexing

When the FastAPI websocket backend receives `final_transcript` events, it now:

1. Persists them to JSONL.
2. Buffers them per session.
3. Flushes buffered records to Qdrant when one of these conditions is met:
   - buffered record count reaches `RAG_REALTIME_FLUSH_RECORDS`
   - buffered char count reaches `RAG_REALTIME_FLUSH_CHARS`
   - buffer stays idle longer than `RAG_REALTIME_FLUSH_INTERVAL_SECONDS`
4. Flushes the tail again on websocket session shutdown.
