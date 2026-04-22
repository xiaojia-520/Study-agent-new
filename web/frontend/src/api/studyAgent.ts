import type {
  CreateSessionPayload,
  LessonHistoryResponse,
  QueryResponse,
  QuerySessionPayload,
  SessionInfo,
  TranscriptResponse,
} from '../types/study'

export const defaultBackendBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || 'http://127.0.0.1:8000'

function normalizeBaseUrl(baseUrl = defaultBackendBaseUrl): string {
  const trimmed = baseUrl.trim()
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`
}

function buildApiUrl(path: string, baseUrl = defaultBackendBaseUrl): string {
  return new URL(path.replace(/^\//, ''), normalizeBaseUrl(baseUrl)).toString()
}

export function buildWebSocketUrl(sessionId: string, baseUrl = defaultBackendBaseUrl): string {
  const url = new URL(`ws/audio/${sessionId}`, normalizeBaseUrl(baseUrl))
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  return url.toString()
}

async function parseResponseBody(response: Response): Promise<unknown> {
  const rawText = await response.text()
  if (!rawText) {
    return null
  }

  try {
    return JSON.parse(rawText) as unknown
  } catch {
    return rawText
  }
}

function extractErrorMessage(body: unknown, fallback: string, status: number): string {
  if (body && typeof body === 'object') {
    const payload = body as Record<string, unknown>
    if (typeof payload.detail === 'string' && payload.detail.trim()) {
      return payload.detail
    }
    if (typeof payload.message === 'string' && payload.message.trim()) {
      return payload.message
    }
  }

  if (typeof body === 'string' && body.trim()) {
    return body
  }

  return `${fallback} (${status})`
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  fallbackMessage: string,
  baseUrl = defaultBackendBaseUrl,
): Promise<T> {
  const headers = new Headers(init.headers ?? {})
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(buildApiUrl(path, baseUrl), {
    ...init,
    headers,
  })
  const body = await parseResponseBody(response)

  if (!response.ok) {
    throw new Error(extractErrorMessage(body, fallbackMessage, response.status))
  }

  return (body ?? {}) as T
}

export function createSession(payload: CreateSessionPayload, baseUrl = defaultBackendBaseUrl) {
  return requestJson<SessionInfo>(
    '/sessions',
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    '创建课堂会话失败',
    baseUrl,
  )
}

export function fetchSessionTranscripts(sessionId: string, baseUrl = defaultBackendBaseUrl) {
  return requestJson<TranscriptResponse>(
    `/sessions/${sessionId}/transcripts`,
    {
      method: 'GET',
    },
    '获取转写记录失败',
    baseUrl,
  )
}

export function fetchLessonTranscripts(
  courseId: string,
  lessonId: string,
  baseUrl = defaultBackendBaseUrl,
) {
  const params = new URLSearchParams({
    course_id: courseId,
    lesson_id: lessonId,
  })
  return requestJson<TranscriptResponse>(
    `/sessions/history/transcripts?${params.toString()}`,
    {
      method: 'GET',
    },
    '获取课程转写记录失败',
    baseUrl,
  )
}

export function fetchLessonHistory(limit = 50, baseUrl = defaultBackendBaseUrl) {
  const params = new URLSearchParams({
    limit: String(limit),
  })
  return requestJson<LessonHistoryResponse>(
    `/sessions/history?${params.toString()}`,
    {
      method: 'GET',
    },
    '获取历史课程失败',
    baseUrl,
  )
}

export function querySession(
  sessionId: string,
  payload: QuerySessionPayload,
  baseUrl = defaultBackendBaseUrl,
) {
  return requestJson<QueryResponse>(
    `/sessions/${sessionId}/query`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    },
    '查询课堂内容失败',
    baseUrl,
  )
}
