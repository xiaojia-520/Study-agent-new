export type ModelKey = 'paraformer-zh' | 'paraformer-zh-streaming' | 'paraformer-zh-streaming-2pass'
export type QueryScope = 'auto' | 'current_lesson' | 'course_all' | 'course_history' | 'global'
export type WebSocketState = 'closed' | 'connecting' | 'open'

export interface ModelOption {
  label: string
  value: ModelKey
}

export interface MicrophoneOption {
  id: string
  label: string
}

export interface SessionInfo {
  session_id: string
  course_id: string
  lesson_id: string
  status: string
  subject?: string | null
  client_id?: string | null
  sample_rate: number
  channels: number
  model_name?: string | null
  created_at: number
}

export interface CreateSessionPayload {
  course_id?: string
  lesson_id?: string
  subject?: string
  client_id?: string
  sample_rate?: number
  channels?: number
  model_name?: ModelKey
}

export interface TranscriptEntry {
  id: string
  timestamp: number
  text: string
  chunkId?: number
  sourceType?: string
}

export interface TranscriptRecordItem {
  id?: number
  session_id?: string
  course_id?: string
  lesson_id?: string
  chunk_id?: number
  text?: string
  clean_text?: string
  created_at?: number
  subject?: string
  source_type?: string
}

export interface TranscriptResponse {
  session_id?: string
  course_id?: string
  lesson_id?: string
  count: number
  items: TranscriptRecordItem[]
}

export interface RefinedTranscriptRecordItem {
  id: number
  source_record_id: number
  session_id: string
  course_id?: string | null
  lesson_id?: string | null
  chunk_id: number
  original_text: string
  refined_text: string
  created_at: number
  refined_at: number
  model_name?: string | null
  metadata: Record<string, unknown>
}

export interface RefinedTranscriptResponse {
  course_id?: string
  lesson_id?: string
  count: number
  items: RefinedTranscriptRecordItem[]
}

export interface LessonHistoryItem {
  course_id?: string | null
  lesson_id?: string | null
  first_at: number
  last_at: number
  message_count: number
  transcript_count?: number
  session_count: number
  last_session_id?: string | null
}

export interface LessonHistoryResponse {
  count: number
  items: LessonHistoryItem[]
}

export interface LessonMessageItem {
  id: number
  session_id: string
  course_id?: string | null
  lesson_id?: string | null
  role: ChatRole
  content: string
  created_at: number
  metadata: Record<string, unknown>
}

export interface LessonMessagesResponse {
  course_id: string
  lesson_id: string
  count: number
  items: LessonMessageItem[]
}

export interface LessonAssetItem {
  id: number
  asset_id: string
  session_id: string
  course_id?: string | null
  lesson_id?: string | null
  subject?: string | null
  file_name: string
  file_size: number
  media_type: string
  status: string
  batch_id?: string | null
  mineru_state?: string | null
  full_zip_url?: string | null
  markdown_path?: string | null
  record_count: number
  indexed_at?: number | null
  error_message?: string | null
  created_at: number
  updated_at: number
  metadata: Record<string, unknown>
}

export interface LessonAssetResponse {
  item: LessonAssetItem
}

export interface LessonAssetListResponse {
  session_id: string
  count: number
  items: LessonAssetItem[]
}

export interface RealtimeEvent {
  type?: string
  seq?: number
  text?: string
  timestamp?: number
  is_final?: boolean
  error?: string
  peak?: number
  rms?: number
  course_id?: string
  lesson_id?: string
  status?: string
  sample_rate?: number
  channels?: number
  model_name?: string
  [key: string]: unknown
}

export interface QueryResult {
  doc_id: string
  content: string
  score?: number | null
  session_id?: string | null
  subject?: string | null
  source_type?: string | null
  metadata?: Record<string, unknown>
}

export interface QueryCitation {
  index: number
  doc_id: string
  snippet: string
  score?: number | null
  session_id?: string | null
  subject?: string | null
  source_type?: string | null
  course_id?: string | null
  lesson_id?: string | null
  metadata?: Record<string, unknown>
}

export interface QueryResponse {
  query: string
  answer?: string | null
  results: QueryResult[]
  citations: QueryCitation[]
  metadata: Record<string, unknown>
  scope?: string
  session_id?: string
  course_id?: string
  lesson_id?: string
}

export interface QuerySessionPayload {
  query: string
  scope: QueryScope
  top_k?: number
  with_llm: boolean
}

export interface RetrievalResult {
  id: string
  title: string
  snippet: string
  source: string
  score: number | null
  docId: string
  sessionId?: string | null
  sourceType?: string | null
  metadata?: Record<string, unknown>
}

export type ChatRole = 'user' | 'assistant'

export interface ChatMessage {
  id: string
  role: ChatRole
  text: string
  createdAt: number
  relatedSources?: string[]
  error?: boolean
}
