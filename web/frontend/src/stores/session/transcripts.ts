import type { Ref } from 'vue'

import {
  fetchLessonTranscripts,
  fetchSessionTranscripts,
} from '../../api/studyAgent'
import type {
  SessionInfo,
  TranscriptEntry,
  TranscriptRecordItem,
} from '../../types/study'

export function toMilliseconds(timestamp?: number): number {
  if (!timestamp) {
    return Date.now()
  }
  return timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000
}

export function mapTranscriptItem(sessionId: string, item: TranscriptRecordItem): TranscriptEntry | null {
  const text = String(item.clean_text || item.text || '').trim()
  if (!text) {
    return null
  }

  const chunkId = typeof item.chunk_id === 'number' ? item.chunk_id : undefined
  return {
    id: chunkId !== undefined ? `chunk-${sessionId}-${chunkId}` : `chunk-${sessionId}-${text.slice(0, 12)}`,
    timestamp: toMilliseconds(item.created_at),
    text,
    chunkId,
    sourceType: item.source_type,
  }
}

export function createTranscriptActions(args: {
  backendBaseUrl: Ref<string>
  sessionInfo: Ref<SessionInfo | null>
  transcriptList: Ref<TranscriptEntry[]>
}) {
  const { backendBaseUrl, sessionInfo, transcriptList } = args

  async function hydrateTranscriptsFromServer(): Promise<void> {
    if (!sessionInfo.value) {
      return
    }

    const response =
      sessionInfo.value.course_id && sessionInfo.value.lesson_id
        ? await fetchLessonTranscripts(
            sessionInfo.value.course_id,
            sessionInfo.value.lesson_id,
            backendBaseUrl.value,
          )
        : await fetchSessionTranscripts(sessionInfo.value.session_id, backendBaseUrl.value)
    const fallbackSessionId = response.session_id || sessionInfo.value.session_id
    const mapped = response.items
      .map((item) => mapTranscriptItem(item.session_id || fallbackSessionId || '', item))
      .filter((item): item is TranscriptEntry => item !== null)
      .sort((left, right) => left.timestamp - right.timestamp)

    transcriptList.value = mapped
  }

  return {
    hydrateTranscriptsFromServer,
  }
}
