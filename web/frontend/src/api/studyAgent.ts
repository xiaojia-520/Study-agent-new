import type {
  CreateSessionPayload,
  LessonAssetListResponse,
  LessonAssetResponse,
  LessonHistoryResponse,
  LessonMessagesResponse,
  QueryResponse,
  QuerySessionPayload,
  RefinedTranscriptResponse,
  SessionInfo,
  SessionVideoListResponse,
  SessionVideoResponse,
  TranscriptResponse,
  VisionFrameResponse,
  VisionRegion,
} from '../types/study'

export const defaultBackendBaseUrl =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim() || 'http://127.0.0.1:8000'

function normalizeBaseUrl(baseUrl = defaultBackendBaseUrl): string {
  const trimmed = baseUrl.trim()
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`
}

export function buildApiUrl(path: string, baseUrl = defaultBackendBaseUrl): string {
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
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
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

export interface UploadSessionVideoOptions {
  recordingStartedAtMs?: number
  recordingEndedAtMs?: number
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

export function uploadSessionAsset(sessionId: string, file: File, baseUrl = defaultBackendBaseUrl) {
  const body = new FormData()
  body.append('file', file)
  return requestJson<LessonAssetResponse>(
    `/sessions/${sessionId}/assets`,
    {
      method: 'POST',
      body,
    },
    '上传课堂素材失败',
    baseUrl,
  )
}

export function fetchSessionAssets(sessionId: string, baseUrl = defaultBackendBaseUrl) {
  return requestJson<LessonAssetListResponse>(
    `/sessions/${sessionId}/assets`,
    {
      method: 'GET',
    },
    '获取课堂素材失败',
    baseUrl,
  )
}

export function fetchLessonAsset(assetId: string, baseUrl = defaultBackendBaseUrl) {
  return requestJson<LessonAssetResponse>(
    `/sessions/assets/${assetId}`,
    {
      method: 'GET',
    },
    '获取素材状态失败',
    baseUrl,
  )
}

export function uploadSessionVideo(
  sessionId: string,
  file: File,
  baseUrl = defaultBackendBaseUrl,
  options: UploadSessionVideoOptions = {},
) {
  const body = new FormData()
  body.append('file', file)
  if (typeof options.recordingStartedAtMs === 'number' && Number.isFinite(options.recordingStartedAtMs)) {
    body.append('recording_started_at_ms', String(Math.max(0, Math.round(options.recordingStartedAtMs))))
  }
  if (typeof options.recordingEndedAtMs === 'number' && Number.isFinite(options.recordingEndedAtMs)) {
    body.append('recording_ended_at_ms', String(Math.max(0, Math.round(options.recordingEndedAtMs))))
  }
  return requestJson<SessionVideoResponse>(
    `/sessions/${sessionId}/videos`,
    {
      method: 'POST',
      body,
    },
    '上传课堂视频失败',
    baseUrl,
  )
}

export function fetchSessionVideos(sessionId: string, baseUrl = defaultBackendBaseUrl) {
  return requestJson<SessionVideoListResponse>(
    `/sessions/${sessionId}/videos`,
    {
      method: 'GET',
    },
    '获取课堂视频失败',
    baseUrl,
  )
}

export function fetchSessionVideo(videoId: string, baseUrl = defaultBackendBaseUrl) {
  return requestJson<SessionVideoResponse>(
    `/sessions/videos/${videoId}`,
    {
      method: 'GET',
    },
    '获取视频字幕状态失败',
    baseUrl,
  )
}

export function fetchLessonVideos(
  courseId: string,
  lessonId: string,
  baseUrl = defaultBackendBaseUrl,
) {
  const params = new URLSearchParams({
    course_id: courseId,
    lesson_id: lessonId,
  })
  return requestJson<SessionVideoListResponse>(
    `/sessions/history/videos?${params.toString()}`,
    {
      method: 'GET',
    },
    '获取历史课堂视频失败',
    baseUrl,
  )
}

export function uploadVisionFrame(
  sessionId: string,
  file: Blob,
  regions: Partial<Record<'ppt' | 'blackboard', VisionRegion>>,
  timestampMs?: number,
  capturedAtMs?: number,
  baseUrl = defaultBackendBaseUrl,
) {
  const body = new FormData()
  body.append('file', file, `vision-frame-${Date.now()}.jpg`)
  body.append('regions', JSON.stringify(regions))
  if (typeof timestampMs === 'number' && Number.isFinite(timestampMs)) {
    body.append('timestamp_ms', String(Math.max(0, Math.round(timestampMs))))
  }
  if (typeof capturedAtMs === 'number' && Number.isFinite(capturedAtMs)) {
    body.append('captured_at_ms', String(Math.max(0, Math.round(capturedAtMs))))
  }
  return requestJson<VisionFrameResponse>(
    `/sessions/${sessionId}/vision-frame`,
    {
      method: 'POST',
      body,
    },
    '上传视觉帧失败',
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

export function fetchRefinedLessonTranscripts(
  courseId: string,
  lessonId: string,
  baseUrl = defaultBackendBaseUrl,
) {
  const params = new URLSearchParams({
    course_id: courseId,
    lesson_id: lessonId,
  })
  return requestJson<RefinedTranscriptResponse>(
    `/sessions/history/refined-transcripts?${params.toString()}`,
    {
      method: 'GET',
    },
    'Fetch refined lesson transcripts failed',
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

export function fetchLessonMessages(
  courseId: string,
  lessonId: string,
  baseUrl = defaultBackendBaseUrl,
) {
  const params = new URLSearchParams({
    course_id: courseId,
    lesson_id: lessonId,
  })
  return requestJson<LessonMessagesResponse>(
    `/sessions/history/messages?${params.toString()}`,
    {
      method: 'GET',
    },
    '获取历史问答失败',
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
