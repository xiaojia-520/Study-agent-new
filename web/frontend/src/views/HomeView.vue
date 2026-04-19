<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

type QueryScope = 'auto' | 'current_lesson' | 'course_all' | 'course_history' | 'global'

interface SessionInfo {
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

interface MicrophoneOption {
  deviceId: string
  label: string
}

interface TranscriptItem {
  chunk_id?: number
  text?: string
  clean_text?: string
  created_at?: number
  subject?: string
  source_type?: string
}

interface QueryResult {
  doc_id: string
  content: string
  score?: number | null
  session_id?: string | null
  subject?: string | null
  source_type?: string | null
  metadata?: Record<string, unknown>
}

interface QueryCitation {
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

interface QueryResponse {
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

interface LessonConcept {
  term: string
  definition: string
}

interface LessonSummaryResponse {
  session_id: string
  course_id: string
  lesson_id: string
  subject: string
  summary: string
  key_points: string[]
  review_items: string[]
  important_terms: LessonConcept[]
  metadata: Record<string, unknown>
}

interface LessonQuizQuestion {
  question: string
  question_type: string
  answer: string
  explanation: string
  options: string[]
}

interface LessonQuizResponse {
  session_id: string
  course_id: string
  lesson_id: string
  subject: string
  questions: LessonQuizQuestion[]
  metadata: Record<string, unknown>
}

interface TranscriptResponse {
  session_id: string
  count: number
  items: TranscriptItem[]
}

interface RealtimeEvent {
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

const backendBaseUrl = ref('http://127.0.0.1:8000')
const subject = ref('课堂记录')
const courseIdInput = ref('')
const clientId = ref('browser-studio')
const modelName = ref('paraformer-zh')
const modelOptions = [
  { value: 'paraformer-zh', label: 'paraformer-zh' },
  { value: 'paraformer-zh-streaming', label: 'paraformer-zh-streaming' },
]

const microphoneOptions = ref<MicrophoneOption[]>([])
const selectedDeviceId = ref('')

const sessionInfo = ref<SessionInfo | null>(null)
const websocketState = ref<'closed' | 'connecting' | 'open'>('closed')
const creatingSession = ref(false)
const connectingSocket = ref(false)
const recording = ref(false)
const loadingTranscripts = ref(false)
const querying = ref(false)
const loadingSummary = ref(false)
const loadingQuiz = ref(false)

const partialTranscript = ref('')
const finalTranscripts = ref<Array<{ seq: number; text: string; timestamp: number }>>([])
const persistedTranscripts = ref<TranscriptItem[]>([])
const eventLog = ref<RealtimeEvent[]>([])

const errorMessage = ref('')
const summaryErrorMessage = ref('')
const quizErrorMessage = ref('')

const audioFrameCount = ref(0)
const audioPeak = ref(0)
const audioRms = ref(0)

const queryText = ref('')
const queryScope = ref<QueryScope>('auto')
const queryTopKInput = ref('5')
const queryWithLlm = ref(true)
const queryResponse = ref<QueryResponse | null>(null)

const summaryFocus = ref('')
const summaryMaxItems = ref(4)
const lessonSummary = ref<LessonSummaryResponse | null>(null)
const summaryStale = ref(false)

const quizFocus = ref('')
const quizQuestionCount = ref(4)
const lessonQuiz = ref<LessonQuizResponse | null>(null)
const quizStale = ref(false)

let websocket: WebSocket | null = null
let socketConnectPromise: Promise<void> | null = null
let mediaStream: MediaStream | null = null
let audioContext: AudioContext | null = null
let mediaSourceNode: MediaStreamAudioSourceNode | null = null
let processorNode: ScriptProcessorNode | null = null
let muteGainNode: GainNode | null = null

const scopeOptions: Array<{ value: QueryScope; label: string }> = [
  { value: 'auto', label: '自动判断' },
  { value: 'current_lesson', label: '当前课时' },
  { value: 'course_all', label: '整门课程' },
  { value: 'course_history', label: '课程历史' },
  { value: 'global', label: '全库检索' },
]

const hasSession = computed(() => sessionInfo.value !== null)
const hasTranscriptData = computed(
  () => finalTranscripts.value.length > 0 || persistedTranscripts.value.length > 0,
)
const liveTranscriptCount = computed(() => finalTranscripts.value.length)
const archiveTranscriptCount = computed(() => persistedTranscripts.value.length)
const shortSessionId = computed(() => sessionInfo.value?.session_id.slice(0, 8) ?? '未创建')
const websocketReady = computed(() => websocketState.value === 'open')
const wsUrlPreview = computed(() => {
  if (!sessionInfo.value) {
    return '创建会话后显示'
  }
  return buildWebSocketUrl(sessionInfo.value.session_id)
})

const visibleFinalTranscripts = computed(() => finalTranscripts.value.slice(0, 8))
const visiblePersistedTranscripts = computed(() =>
  [...persistedTranscripts.value]
    .sort((left, right) => (right.chunk_id ?? 0) - (left.chunk_id ?? 0))
    .slice(0, 8),
)

const latestTranscriptText = computed(() => {
  const latestLive = finalTranscripts.value[0]?.text.trim()
  if (latestLive) {
    return latestLive
  }
  const latestArchive = visiblePersistedTranscripts.value[0]
  return latestArchive?.clean_text?.trim() || latestArchive?.text?.trim() || ''
})

const sessionStageLabel = computed(() => {
  if (!sessionInfo.value) {
    return '尚未开始'
  }
  if (recording.value) {
    return '采集中'
  }
  if (websocketReady.value) {
    return '已连接'
  }
  return '已创建'
})

const statusToneClass = computed(() => {
  if (recording.value) {
    return 'is-live'
  }
  if (websocketReady.value) {
    return 'is-ready'
  }
  if (errorMessage.value) {
    return 'is-warning'
  }
  return 'is-muted'
})

const queryNoticeText = computed(() => {
  const response = queryResponse.value
  if (!response) {
    return '提一个问题，系统会先检索当前课堂内容，再决定是否调用大模型组织回答。'
  }
  const metadata = response.metadata
  if (metadataBoolean(metadata, 'llm_fallback')) {
    return 'LLM 合成失败，当前展示的是命中的原始片段。'
  }
  if (metadataBoolean(metadata, 'llm_used')) {
    return '回答已基于检索到的课堂片段进行综合，并保留引用编号。'
  }
  if (response.results.length > 0) {
    return '本次只返回了检索片段，你可以继续追问或切换检索范围。'
  }
  return '当前范围内没有找到相关内容，可以换个问法或扩大范围。'
})

const queryLlmStatus = computed(() => {
  const response = queryResponse.value
  if (!response) {
    return queryWithLlm.value ? '待生成' : '纯检索'
  }
  const metadata = response.metadata
  if (metadataBoolean(metadata, 'llm_fallback')) {
    return '回退到检索'
  }
  if (metadataBoolean(metadata, 'llm_used')) {
    return 'LLM 已生成'
  }
  if (response.answer) {
    return '上下文不足提示'
  }
  return '纯检索'
})

const queryErrorDetail = computed(() => {
  const response = queryResponse.value
  if (!response) {
    return ''
  }
  return metadataText(response.metadata, 'llm_error')
})

const effectiveScopeLabel = computed(() =>
  mapScopeToLabel(queryResponse.value?.scope || metadataText(queryResponse.value?.metadata, 'scope') || ''),
)

const answerText = computed(() => {
  const response = queryResponse.value
  if (!response) {
    return '在这里输入你的问题。系统会结合当前课时、课程历史或全局知识库返回答案。'
  }
  if (response.answer?.trim()) {
    return response.answer.trim()
  }
  if (response.results.length > 0) {
    return '已展示命中的课堂原文。你可以继续追问、扩大检索范围，或重新生成课后总结。'
  }
  return '当前没有检索到足够内容。'
})

const summaryCopyText = computed(() => {
  const summary = lessonSummary.value
  if (!summary) {
    return ''
  }
  const lines = [
    `总结：${summary.summary}`,
    '',
    '关键知识点：',
    ...summary.key_points.map((item, index) => `${index + 1}. ${item}`),
    '',
    '待复习：',
    ...summary.review_items.map((item, index) => `${index + 1}. ${item}`),
    '',
    '重要术语：',
    ...summary.important_terms.map((item) => `${item.term}：${item.definition}`),
  ]
  return lines.join('\n')
})

const quizCopyText = computed(() => {
  const quiz = lessonQuiz.value
  if (!quiz) {
    return ''
  }
  return quiz.questions
    .map((question, index) => {
      const options = question.options.map((item) => `- ${item}`).join('\n')
      return [
        `${index + 1}. ${question.question}`,
        options,
        `答案：${question.answer}`,
        `解析：${question.explanation}`,
      ]
        .filter(Boolean)
        .join('\n')
    })
    .join('\n\n')
})

function normalizeBaseUrl(): string {
  const trimmed = backendBaseUrl.value.trim()
  return trimmed.endsWith('/') ? trimmed : `${trimmed}/`
}

function buildApiUrl(path: string): string {
  return new URL(path.replace(/^\//, ''), normalizeBaseUrl()).toString()
}

function buildWebSocketUrl(sessionId: string): string {
  const url = new URL(`ws/audio/${sessionId}`, normalizeBaseUrl())
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

async function requestJson<T>(path: string, init: RequestInit, fallback: string): Promise<T> {
  const headers = new Headers(init.headers ?? {})
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers,
  })
  const body = await parseResponseBody(response)

  if (!response.ok) {
    throw new Error(extractErrorMessage(body, fallback, response.status))
  }

  return (body ?? {}) as T
}

function metadataBoolean(metadata: Record<string, unknown> | undefined, key: string): boolean {
  return metadata?.[key] === true
}

function metadataText(metadata: Record<string, unknown> | undefined, key: string): string {
  const value = metadata?.[key]
  return typeof value === 'string' ? value : ''
}

function mapScopeToLabel(scope: string): string {
  const labelMap: Record<string, string> = {
    auto: '自动判断',
    current_lesson: '当前课时',
    course_all: '整门课程',
    course_history: '课程历史',
    global: '全库检索',
  }
  return labelMap[scope] || '当前课时'
}

function formatTimestamp(value?: number): string {
  if (!value) {
    return '刚刚'
  }
  return new Date(value * 1000).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatScore(score?: number | null): string {
  if (typeof score !== 'number') {
    return 'n/a'
  }
  return score.toFixed(3)
}

function formatPercent(value: number): string {
  return `${Math.min(100, Math.round(value * 100))}%`
}

function questionTypeLabel(questionType: string): string {
  const labelMap: Record<string, string> = {
    single_choice: '单选题',
    multiple_choice: '多选题',
    short_answer: '简答题',
    true_false: '判断题',
  }
  return labelMap[questionType] || '题目'
}

function resetPanels(): void {
  partialTranscript.value = ''
  finalTranscripts.value = []
  persistedTranscripts.value = []
  eventLog.value = []
  queryResponse.value = null
  lessonSummary.value = null
  lessonQuiz.value = null
  summaryErrorMessage.value = ''
  quizErrorMessage.value = ''
  summaryStale.value = false
  quizStale.value = false
  audioFrameCount.value = 0
  audioPeak.value = 0
  audioRms.value = 0
}

function markGeneratedContentStale(): void {
  if (lessonSummary.value) {
    summaryStale.value = true
  }
  if (lessonQuiz.value) {
    quizStale.value = true
  }
}

function addRealtimeEvent(payload: RealtimeEvent): void {
  eventLog.value = [payload, ...eventLog.value].slice(0, 40)
}

async function refreshMicrophones(): Promise<void> {
  if (!navigator.mediaDevices?.enumerateDevices) {
    errorMessage.value = '当前浏览器不支持麦克风设备枚举。'
    return
  }

  try {
    try {
      const permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true })
      permissionStream.getTracks().forEach((track) => track.stop())
    } catch {
      // Ignore permission prompts here and still try to enumerate devices.
    }

    const devices = await navigator.mediaDevices.enumerateDevices()
    const inputs = devices
      .filter((device) => device.kind === 'audioinput')
      .map((device, index) => ({
        deviceId: device.deviceId,
        label: device.label || `麦克风 ${index + 1}`,
      }))

    microphoneOptions.value = inputs
    if (!selectedDeviceId.value || !inputs.some((item) => item.deviceId === selectedDeviceId.value)) {
      selectedDeviceId.value = inputs[0]?.deviceId ?? ''
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '获取麦克风列表失败。'
  }
}

function updateSessionFromEvent(payload: RealtimeEvent): void {
  if (!sessionInfo.value) {
    return
  }
  if (payload.status) {
    sessionInfo.value.status = payload.status
  }
  if (payload.course_id) {
    sessionInfo.value.course_id = payload.course_id
  }
  if (payload.lesson_id) {
    sessionInfo.value.lesson_id = payload.lesson_id
  }
  if (payload.sample_rate) {
    sessionInfo.value.sample_rate = payload.sample_rate
  }
  if (payload.channels) {
    sessionInfo.value.channels = payload.channels
  }
  if (payload.model_name) {
    sessionInfo.value.model_name = payload.model_name
  }
}

async function fetchPersistedTranscripts(silent = false): Promise<void> {
  if (!sessionInfo.value) {
    return
  }

  if (!silent) {
    loadingTranscripts.value = true
  }

  try {
    const response = await requestJson<TranscriptResponse>(
      `/sessions/${sessionInfo.value.session_id}/transcripts`,
      { method: 'GET' },
      '获取课堂记录失败',
    )
    persistedTranscripts.value = response.items
  } catch (error) {
    if (!silent) {
      errorMessage.value = error instanceof Error ? error.message : '获取课堂记录失败。'
    }
  } finally {
    if (!silent) {
      loadingTranscripts.value = false
    }
  }
}

async function refreshPersistedTranscripts(): Promise<void> {
  await fetchPersistedTranscripts(false)
}

function handleRealtimeEvent(payload: RealtimeEvent): void {
  addRealtimeEvent(payload)
  updateSessionFromEvent(payload)

  switch (payload.type) {
    case 'partial_transcript':
      partialTranscript.value = typeof payload.text === 'string' ? payload.text : ''
      break
    case 'final_transcript':
      if (typeof payload.text === 'string' && payload.text.trim()) {
        partialTranscript.value = ''
        finalTranscripts.value = [
          {
            seq: payload.seq ?? Date.now(),
            text: payload.text.trim(),
            timestamp: payload.timestamp ?? Math.floor(Date.now() / 1000),
          },
          ...finalTranscripts.value,
        ].slice(0, 20)
        markGeneratedContentStale()
        void fetchPersistedTranscripts(true)
      }
      break
    case 'audio_metrics':
      if (typeof payload.peak === 'number') {
        audioPeak.value = payload.peak
      }
      if (typeof payload.rms === 'number') {
        audioRms.value = payload.rms
      }
      break
    case 'session_error':
      errorMessage.value = typeof payload.error === 'string' ? payload.error : '实时语音服务异常。'
      break
    case 'session_started':
    case 'session_stopped':
    default:
      break
  }
}

async function createSession(): Promise<void> {
  creatingSession.value = true
  errorMessage.value = ''

  try {
    await disconnectWebSocket()
    resetPanels()

    const response = await requestJson<SessionInfo>(
      '/sessions',
      {
        method: 'POST',
        body: JSON.stringify({
          subject: subject.value.trim() || undefined,
          course_id: courseIdInput.value.trim() || undefined,
          client_id: clientId.value.trim() || undefined,
          model_name: modelName.value,
        }),
      },
      '创建会话失败',
    )

    sessionInfo.value = response
    await fetchPersistedTranscripts(true)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '创建会话失败。'
  } finally {
    creatingSession.value = false
  }
}

async function disconnectWebSocket(): Promise<void> {
  await stopRecording()

  if (websocket) {
    const currentSocket = websocket
    websocket = null
    socketConnectPromise = null

    if (
      currentSocket.readyState === WebSocket.CONNECTING ||
      currentSocket.readyState === WebSocket.OPEN
    ) {
      currentSocket.close(1000, 'client disconnect')
    }
  }

  websocketState.value = 'closed'
  connectingSocket.value = false
}

async function connectWebSocket(): Promise<void> {
  if (!sessionInfo.value) {
    throw new Error('请先创建课堂会话。')
  }
  if (websocket?.readyState === WebSocket.OPEN) {
    return
  }
  if (socketConnectPromise) {
    return socketConnectPromise
  }

  errorMessage.value = ''
  connectingSocket.value = true
  websocketState.value = 'connecting'

  const currentSocket = new WebSocket(buildWebSocketUrl(sessionInfo.value.session_id))
  websocket = currentSocket

  socketConnectPromise = new Promise<void>((resolve, reject) => {
    let handshakeCompleted = false

    currentSocket.onopen = () => {
      handshakeCompleted = true
      connectingSocket.value = false
      websocketState.value = 'open'
      socketConnectPromise = null
      resolve()
    }

    currentSocket.onmessage = (message) => {
      if (typeof message.data !== 'string') {
        return
      }

      try {
        handleRealtimeEvent(JSON.parse(message.data) as RealtimeEvent)
      } catch {
        // Ignore malformed events from the stream.
      }
    }

    currentSocket.onerror = () => {
      errorMessage.value = 'WebSocket 连接失败。'
      if (!handshakeCompleted) {
        connectingSocket.value = false
        websocketState.value = 'closed'
        websocket = null
        socketConnectPromise = null
        reject(new Error('WebSocket 连接失败。'))
      }
    }

    currentSocket.onclose = (closeEvent) => {
      if (websocket === currentSocket) {
        websocket = null
      }
      websocketState.value = 'closed'
      connectingSocket.value = false
      if (recording.value) {
        void stopRecording()
      }
      if (!handshakeCompleted) {
        socketConnectPromise = null
        reject(new Error(closeEvent.reason || 'WebSocket 连接已关闭。'))
        return
      }
      socketConnectPromise = null
    }
  })

  return socketConnectPromise
}

async function openRealtimeChannel(): Promise<void> {
  try {
    await connectWebSocket()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'WebSocket 连接失败。'
  }
}

function downsampleBuffer(source: Float32Array, sourceRate: number, targetRate: number): Float32Array {
  if (targetRate <= 0 || sourceRate <= 0 || source.length === 0) {
    return new Float32Array()
  }
  if (sourceRate === targetRate || sourceRate < targetRate) {
    return Float32Array.from(source)
  }

  const ratio = sourceRate / targetRate
  const length = Math.max(1, Math.round(source.length / ratio))
  const result = new Float32Array(length)

  let sourceOffset = 0
  for (let index = 0; index < length; index += 1) {
    const nextOffset = Math.min(source.length, Math.round((index + 1) * ratio))
    const start = Math.min(source.length - 1, Math.round(sourceOffset))
    let accumulator = 0
    let count = 0

    for (let position = start; position < nextOffset; position += 1) {
      accumulator += source[position] ?? 0
      count += 1
    }

    result[index] = count > 0 ? accumulator / count : (source[start] ?? 0)
    sourceOffset = nextOffset
  }

  return result
}

async function releaseAudioResources(): Promise<void> {
  if (processorNode) {
    processorNode.onaudioprocess = null
    processorNode.disconnect()
    processorNode = null
  }
  if (mediaSourceNode) {
    mediaSourceNode.disconnect()
    mediaSourceNode = null
  }
  if (muteGainNode) {
    muteGainNode.disconnect()
    muteGainNode = null
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop())
    mediaStream = null
  }
  if (audioContext && audioContext.state !== 'closed') {
    await audioContext.close()
  }
  audioContext = null
}

async function startRecording(): Promise<void> {
  if (!sessionInfo.value) {
    errorMessage.value = '请先创建课堂会话。'
    return
  }

  try {
    await connectWebSocket()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'WebSocket 连接失败。'
    return
  }

  try {
    await releaseAudioResources()

    const targetSampleRate = sessionInfo.value.sample_rate || 16000
    const constraints: MediaStreamConstraints = {
      audio: {
        deviceId: selectedDeviceId.value ? { exact: selectedDeviceId.value } : undefined,
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    }

    mediaStream = await navigator.mediaDevices.getUserMedia(constraints)
    audioContext = new AudioContext({ sampleRate: targetSampleRate })
    await audioContext.resume()

    mediaSourceNode = audioContext.createMediaStreamSource(mediaStream)
    processorNode = audioContext.createScriptProcessor(4096, 1, 1)
    muteGainNode = audioContext.createGain()
    muteGainNode.gain.value = 0

    processorNode.onaudioprocess = (audioEvent: AudioProcessingEvent) => {
      if (!recording.value || !websocket || websocket.readyState !== WebSocket.OPEN) {
        return
      }

      const input = audioEvent.inputBuffer.getChannelData(0)
      const pcm = downsampleBuffer(input, audioEvent.inputBuffer.sampleRate, targetSampleRate)
      if (!pcm.length) {
        return
      }

      audioFrameCount.value += 1
      try {
        websocket.send(pcm.buffer.slice(0))
      } catch (error) {
        errorMessage.value = error instanceof Error ? error.message : '音频发送失败。'
      }
    }

    mediaSourceNode.connect(processorNode)
    processorNode.connect(muteGainNode)
    muteGainNode.connect(audioContext.destination)
    recording.value = true
  } catch (error) {
    await releaseAudioResources()
    errorMessage.value = error instanceof Error ? error.message : '启动录音失败。'
  }
}

async function stopRecording(): Promise<void> {
  recording.value = false
  await releaseAudioResources()
}

async function askQuestion(): Promise<void> {
  if (!sessionInfo.value) {
    errorMessage.value = '请先创建课堂会话。'
    return
  }
  if (!queryText.value.trim()) {
    errorMessage.value = '请输入问题。'
    return
  }

  querying.value = true
  errorMessage.value = ''

  try {
    const topK = Number.parseInt(queryTopKInput.value, 10)
    queryResponse.value = await requestJson<QueryResponse>(
      `/sessions/${sessionInfo.value.session_id}/query`,
      {
        method: 'POST',
        body: JSON.stringify({
          query: queryText.value.trim(),
          scope: queryScope.value,
          top_k: Number.isFinite(topK) && topK > 0 ? topK : undefined,
          with_llm: queryWithLlm.value,
        }),
      },
      '课堂问答失败',
    )
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '课堂问答失败。'
  } finally {
    querying.value = false
  }
}

function useLatestTranscript(): void {
  if (latestTranscriptText.value) {
    queryText.value = latestTranscriptText.value
  }
}

async function generateSummary(): Promise<void> {
  if (!sessionInfo.value) {
    errorMessage.value = '请先创建课堂会话。'
    return
  }

  loadingSummary.value = true
  summaryErrorMessage.value = ''

  try {
    lessonSummary.value = await requestJson<LessonSummaryResponse>(
      `/sessions/${sessionInfo.value.session_id}/summary`,
      {
        method: 'POST',
        body: JSON.stringify({
          focus: summaryFocus.value.trim() || undefined,
          max_items: summaryMaxItems.value,
        }),
      },
      '生成课后总结失败',
    )
    summaryStale.value = false
  } catch (error) {
    summaryErrorMessage.value = error instanceof Error ? error.message : '生成课后总结失败。'
  } finally {
    loadingSummary.value = false
  }
}

async function generateQuiz(): Promise<void> {
  if (!sessionInfo.value) {
    errorMessage.value = '请先创建课堂会话。'
    return
  }

  loadingQuiz.value = true
  quizErrorMessage.value = ''

  try {
    lessonQuiz.value = await requestJson<LessonQuizResponse>(
      `/sessions/${sessionInfo.value.session_id}/quiz`,
      {
        method: 'POST',
        body: JSON.stringify({
          focus: quizFocus.value.trim() || undefined,
          question_count: quizQuestionCount.value,
        }),
      },
      '生成课堂测验失败',
    )
    quizStale.value = false
  } catch (error) {
    quizErrorMessage.value = error instanceof Error ? error.message : '生成课堂测验失败。'
  } finally {
    loadingQuiz.value = false
  }
}

async function copyText(text: string, successLabel: string): Promise<void> {
  if (!text.trim()) {
    return
  }

  try {
    await navigator.clipboard.writeText(text)
  } catch {
    errorMessage.value = `${successLabel}复制失败，请检查浏览器剪贴板权限。`
  }
}

onMounted(() => {
  void refreshMicrophones()
})

onUnmounted(() => {
  void disconnectWebSocket()
})
</script>

<template>
  <main class="study-shell">
    <section class="hero-band">
      <div class="hero-copy">
        <p class="hero-kicker">Study Agent</p>
        <h1>把一节课变成可回看、可追问、可复习的学习工作台。</h1>
        <p class="hero-text">
          这里不是调试台，而是课堂助手。实时转写先把内容沉淀下来，再用检索和 LLM 把它整理成回答、总结和自测。
        </p>
        <div class="hero-tags">
          <span>实时转写</span>
          <span>课堂问答</span>
          <span>课后总结</span>
          <span>自动测验</span>
        </div>
      </div>

      <aside class="hero-status" :class="statusToneClass">
        <div class="status-pill">
          <span>当前阶段</span>
          <strong>{{ sessionStageLabel }}</strong>
        </div>
        <dl class="hero-metrics">
          <div>
            <dt>会话</dt>
            <dd>{{ shortSessionId }}</dd>
          </div>
          <div>
            <dt>实时摘录</dt>
            <dd>{{ liveTranscriptCount }}</dd>
          </div>
          <div>
            <dt>落盘记录</dt>
            <dd>{{ archiveTranscriptCount }}</dd>
          </div>
          <div>
            <dt>音频帧</dt>
            <dd>{{ audioFrameCount }}</dd>
          </div>
        </dl>
      </aside>
    </section>

    <p v-if="errorMessage" class="notice notice-error">
      {{ errorMessage }}
    </p>

    <div class="workspace-grid">
      <div class="main-column">
        <section class="card card-form">
          <div class="section-head">
            <div>
              <p class="section-kicker">课堂控制</p>
              <h2>开始一节新的课堂</h2>
            </div>
            <span class="inline-badge">{{ websocketReady ? 'WebSocket 已连接' : '待连接' }}</span>
          </div>

          <div class="form-grid">
            <label class="field field-wide">
              <span>课堂主题</span>
              <input v-model="subject" type="text" placeholder="例如：HTTP 与 Session" />
            </label>

            <label class="field">
              <span>ASR 模型</span>
              <select v-model="modelName">
                <option v-for="option in modelOptions" :key="option.value" :value="option.value">
                  {{ option.label }}
                </option>
              </select>
            </label>

            <label class="field">
              <span>麦克风</span>
              <select v-model="selectedDeviceId">
                <option value="">默认设备</option>
                <option v-for="device in microphoneOptions" :key="device.deviceId" :value="device.deviceId">
                  {{ device.label }}
                </option>
              </select>
            </label>
          </div>

          <details class="advanced-panel">
            <summary>高级设置</summary>
            <div class="form-grid">
              <label class="field field-wide">
                <span>后端地址</span>
                <input v-model="backendBaseUrl" type="text" placeholder="http://127.0.0.1:8000" />
              </label>

              <label class="field">
                <span>课程 ID</span>
                <input v-model="courseIdInput" type="text" placeholder="留空时根据主题生成" />
              </label>

              <label class="field">
                <span>客户端 ID</span>
                <input v-model="clientId" type="text" placeholder="browser-studio" />
              </label>
            </div>
          </details>

          <div class="action-row">
            <button class="button button-primary" :disabled="creatingSession" @click="createSession">
              {{ creatingSession ? '创建中...' : '创建课堂' }}
            </button>
            <button class="button button-secondary" :disabled="!hasSession || connectingSocket" @click="openRealtimeChannel">
              {{ connectingSocket ? '连接中...' : '连接实时通道' }}
            </button>
            <button class="button button-ghost" :disabled="!websocketReady" @click="disconnectWebSocket">
              断开连接
            </button>
            <button class="button button-accent" :disabled="!hasSession || recording" @click="startRecording">
              开始录音
            </button>
            <button class="button button-ghost" :disabled="!recording" @click="stopRecording">
              停止录音
            </button>
            <button class="button button-ghost" @click="refreshMicrophones">
              刷新麦克风
            </button>
            <button class="button button-ghost" @click="resetPanels">
              清空面板
            </button>
          </div>

          <div class="session-strip">
            <article>
              <span>Session</span>
              <strong>{{ sessionInfo?.session_id || '未创建' }}</strong>
            </article>
            <article>
              <span>Course</span>
              <strong>{{ sessionInfo?.course_id || '待生成' }}</strong>
            </article>
            <article>
              <span>Lesson</span>
              <strong>{{ sessionInfo?.lesson_id || '待生成' }}</strong>
            </article>
            <article>
              <span>WS URL</span>
              <strong>{{ wsUrlPreview }}</strong>
            </article>
          </div>
        </section>

        <section class="card">
          <div class="section-head">
            <div>
              <p class="section-kicker">实时课堂</p>
              <h2>课堂摘录</h2>
            </div>
            <div class="metric-pills">
              <span>峰值 {{ formatPercent(audioPeak) }}</span>
              <span>均值 {{ formatPercent(audioRms) }}</span>
            </div>
          </div>

          <div class="transcript-layout">
            <article class="transcript-focus">
              <p class="small-label">实时片段</p>
              <p v-if="partialTranscript" class="partial-bubble">{{ partialTranscript }}</p>
              <p v-else class="placeholder">
                正在等待新的增量转写。连接并开始录音后，这里会实时滚动显示。
              </p>
            </article>

            <article class="transcript-column">
              <div class="mini-head">
                <h3>最新终稿</h3>
                <span>{{ liveTranscriptCount }} 条</span>
              </div>
              <ul v-if="visibleFinalTranscripts.length" class="transcript-list">
                <li v-for="item in visibleFinalTranscripts" :key="item.seq">
                  <div class="list-meta">
                    <span>#{{ item.seq }}</span>
                    <span>{{ formatTimestamp(item.timestamp) }}</span>
                  </div>
                  <p>{{ item.text }}</p>
                </li>
              </ul>
              <p v-else class="placeholder">还没有实时终稿，开始录音后会自动出现。</p>
            </article>

            <article class="transcript-column">
              <div class="mini-head">
                <h3>已保存记录</h3>
                <button class="text-button" :disabled="!hasSession || loadingTranscripts" @click="refreshPersistedTranscripts">
                  {{ loadingTranscripts ? '刷新中...' : '刷新' }}
                </button>
              </div>
              <ul v-if="visiblePersistedTranscripts.length" class="transcript-list">
                <li v-for="item in visiblePersistedTranscripts" :key="item.chunk_id">
                  <div class="list-meta">
                    <span>#{{ item.chunk_id }}</span>
                    <span>{{ formatTimestamp(item.created_at) }}</span>
                  </div>
                  <p>{{ item.clean_text || item.text }}</p>
                </li>
              </ul>
              <p v-else class="placeholder">课堂内容落盘后会显示在这里。</p>
            </article>
          </div>
        </section>

        <section class="card">
          <div class="section-head">
            <div>
              <p class="section-kicker">课堂问答</p>
              <h2>先检索课堂，再组织答案</h2>
            </div>
            <span class="inline-badge">{{ queryLlmStatus }}</span>
          </div>

          <label class="field">
            <span>你的问题</span>
            <textarea
              v-model="queryText"
              rows="4"
              placeholder="例如：这节课里老师如何解释 Session 和 Cookie 的关系？"
            />
          </label>

          <div class="query-controls">
            <label class="field">
              <span>检索范围</span>
              <select v-model="queryScope">
                <option v-for="item in scopeOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </label>

            <label class="field">
              <span>Top K</span>
              <input v-model="queryTopKInput" type="number" min="1" max="20" />
            </label>

            <label class="checkbox-field">
              <input v-model="queryWithLlm" type="checkbox" />
              <span>后端启用 LLM 时，自动生成综合回答</span>
            </label>
          </div>

          <div class="action-row">
            <button class="button button-primary" :disabled="!hasSession || querying" @click="askQuestion">
              {{ querying ? '查询中...' : '开始提问' }}
            </button>
            <button class="button button-ghost" :disabled="!latestTranscriptText" @click="useLatestTranscript">
              带入最新摘录
            </button>
            <button
              class="button button-ghost"
              :disabled="!queryResponse?.answer"
              @click="copyText(queryResponse?.answer || '', '答案')"
            >
              复制答案
            </button>
          </div>

          <div class="qa-summary">
            <div>
              <span>实际范围</span>
              <strong>{{ effectiveScopeLabel }}</strong>
            </div>
            <div>
              <span>Course</span>
              <strong>{{ queryResponse?.course_id || sessionInfo?.course_id || '未创建' }}</strong>
            </div>
            <div>
              <span>Lesson</span>
              <strong>{{ queryResponse?.lesson_id || sessionInfo?.lesson_id || '未创建' }}</strong>
            </div>
          </div>

          <p class="notice notice-soft">
            {{ queryNoticeText }}
          </p>
          <p v-if="queryErrorDetail" class="notice notice-error">
            具体错误：{{ queryErrorDetail }}
          </p>

          <article class="answer-panel">
            <p class="small-label">回答</p>
            <p class="answer-text">{{ answerText }}</p>
          </article>

          <div class="result-grid">
            <article class="subcard">
              <div class="mini-head">
                <h3>引用来源</h3>
                <span>{{ queryResponse?.citations.length || 0 }} 条</span>
              </div>
              <ul v-if="queryResponse?.citations.length" class="result-list">
                <li v-for="item in queryResponse.citations" :key="item.doc_id">
                  <div class="list-meta">
                    <span>[{{ item.index }}]</span>
                    <span>score {{ formatScore(item.score) }}</span>
                  </div>
                  <strong>{{ item.subject || item.course_id || '课堂内容' }}</strong>
                  <p>{{ item.snippet }}</p>
                  <small>{{ item.doc_id }}</small>
                </li>
              </ul>
              <p v-else class="placeholder">回答生成后，对应的引用来源会展示在这里。</p>
            </article>

            <article class="subcard">
              <div class="mini-head">
                <h3>命中原文</h3>
                <span>{{ queryResponse?.results.length || 0 }} 条</span>
              </div>
              <ul v-if="queryResponse?.results.length" class="result-list">
                <li v-for="item in queryResponse.results" :key="item.doc_id">
                  <div class="list-meta">
                    <span>{{ item.doc_id }}</span>
                    <span>score {{ formatScore(item.score) }}</span>
                  </div>
                  <p>{{ item.content }}</p>
                </li>
              </ul>
              <p v-else class="placeholder">检索到的原始片段会展示在这里。</p>
            </article>
          </div>
        </section>
      </div>

      <aside class="side-column">
        <section class="card side-card">
          <div class="section-head">
            <div>
              <p class="section-kicker">课后整理</p>
              <h2>课程总结</h2>
            </div>
            <span class="inline-badge" :class="{ 'badge-warning': summaryStale }">
              {{ summaryStale ? '已有新内容' : '可随时生成' }}
            </span>
          </div>

          <div class="form-grid compact-grid">
            <label class="field field-wide">
              <span>关注重点</span>
              <input v-model="summaryFocus" type="text" placeholder="例如：重点总结 Session 的作用和实现方式" />
            </label>

            <label class="field">
              <span>输出条数</span>
              <input v-model.number="summaryMaxItems" type="number" min="3" max="8" />
            </label>
          </div>

          <div class="action-row">
            <button class="button button-primary" :disabled="!hasTranscriptData || loadingSummary" @click="generateSummary">
              {{ loadingSummary ? '生成中...' : '生成总结' }}
            </button>
            <button class="button button-ghost" :disabled="!summaryCopyText" @click="copyText(summaryCopyText, '总结')">
              复制总结
            </button>
          </div>

          <p v-if="summaryErrorMessage" class="notice notice-error">{{ summaryErrorMessage }}</p>
          <p v-else-if="summaryStale" class="notice notice-soft">
            自从上次生成总结后，课堂新增了内容，建议重新生成。
          </p>

          <div v-if="lessonSummary" class="study-stack">
            <article class="study-block">
              <p class="small-label">总结</p>
              <p class="answer-text">{{ lessonSummary.summary }}</p>
            </article>

            <article class="study-block">
              <p class="small-label">关键知识点</p>
              <ul class="bullet-list">
                <li v-for="item in lessonSummary.key_points" :key="item">{{ item }}</li>
              </ul>
            </article>

            <article class="study-block">
              <p class="small-label">待复习项</p>
              <ul class="bullet-list">
                <li v-for="item in lessonSummary.review_items" :key="item">{{ item }}</li>
              </ul>
            </article>

            <article class="study-block">
              <p class="small-label">重要术语</p>
              <div class="term-grid">
                <div v-for="item in lessonSummary.important_terms" :key="item.term" class="term-card">
                  <strong>{{ item.term }}</strong>
                  <p>{{ item.definition }}</p>
                </div>
              </div>
            </article>
          </div>

          <p v-else class="placeholder">
            生成后，这里会给出一段课后总结、关键知识点、复习项和术语卡片。
          </p>
        </section>

        <section class="card side-card">
          <div class="section-head">
            <div>
              <p class="section-kicker">自测练习</p>
              <h2>课堂测验</h2>
            </div>
            <span class="inline-badge" :class="{ 'badge-warning': quizStale }">
              {{ quizStale ? '建议重出' : '立即生成' }}
            </span>
          </div>

          <div class="form-grid compact-grid">
            <label class="field field-wide">
              <span>出题重点</span>
              <input v-model="quizFocus" type="text" placeholder="例如：围绕 HTTP 无状态与 Session 协作机制出题" />
            </label>

            <label class="field">
              <span>题目数量</span>
              <input v-model.number="quizQuestionCount" type="number" min="2" max="8" />
            </label>
          </div>

          <div class="action-row">
            <button class="button button-primary" :disabled="!hasTranscriptData || loadingQuiz" @click="generateQuiz">
              {{ loadingQuiz ? '生成中...' : '生成测验' }}
            </button>
            <button class="button button-ghost" :disabled="!quizCopyText" @click="copyText(quizCopyText, '测验')">
              复制题目
            </button>
          </div>

          <p v-if="quizErrorMessage" class="notice notice-error">{{ quizErrorMessage }}</p>
          <p v-else-if="quizStale" class="notice notice-soft">
            课堂内容已更新，重新生成后题目会更贴近最新讲解。
          </p>

          <div v-if="lessonQuiz?.questions.length" class="quiz-stack">
            <article v-for="(item, index) in lessonQuiz.questions" :key="`${item.question}-${index}`" class="quiz-card">
              <div class="quiz-head">
                <strong>第 {{ index + 1 }} 题</strong>
                <span>{{ questionTypeLabel(item.question_type) }}</span>
              </div>
              <p class="quiz-question">{{ item.question }}</p>
              <ul v-if="item.options.length" class="option-list">
                <li v-for="option in item.options" :key="option">{{ option }}</li>
              </ul>
              <p><span class="small-label">答案</span> {{ item.answer }}</p>
              <p><span class="small-label">解析</span> {{ item.explanation }}</p>
            </article>
          </div>

          <p v-else class="placeholder">
            生成后，这里会给出结构化题目、答案和解析，方便你直接复习或导出。
          </p>
        </section>

        <section class="card side-card session-card">
          <div class="section-head">
            <div>
              <p class="section-kicker">课堂快照</p>
              <h2>当前配置</h2>
            </div>
          </div>

          <dl class="snapshot-grid">
            <div>
              <dt>后端</dt>
              <dd>{{ backendBaseUrl }}</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{{ websocketState }}</dd>
            </div>
            <div>
              <dt>主题</dt>
              <dd>{{ subject }}</dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd>{{ modelName }}</dd>
            </div>
            <div>
              <dt>Sample Rate</dt>
              <dd>{{ sessionInfo?.sample_rate || 16000 }}</dd>
            </div>
            <div>
              <dt>Channel</dt>
              <dd>{{ sessionInfo?.channels || 1 }}</dd>
            </div>
          </dl>
        </section>
      </aside>
    </div>

    <details class="debug-drawer">
      <summary>开发调试信息</summary>
      <div class="drawer-grid">
        <section class="card drawer-card">
          <div class="section-head">
            <div>
              <p class="section-kicker">事件流</p>
              <h2>Realtime Events</h2>
            </div>
            <span class="inline-badge">{{ eventLog.length }} 条</span>
          </div>

          <ul v-if="eventLog.length" class="event-list">
            <li v-for="item in eventLog" :key="`${item.seq}-${item.type}`">
              <div class="list-meta">
                <span>{{ item.type || 'event' }}</span>
                <span>#{{ item.seq ?? '-' }}</span>
                <span>{{ formatTimestamp(item.timestamp) }}</span>
              </div>
              <pre>{{ JSON.stringify(item, null, 2) }}</pre>
            </li>
          </ul>
          <p v-else class="placeholder">还没有收到实时事件。</p>
        </section>
      </div>
    </details>
  </main>
</template>

<style scoped>
@reference "tailwindcss";

.study-shell {
  width: min(1480px, calc(100vw - 32px));
  @apply mx-auto pt-7 pb-14;
}

.hero-band {
  @apply mb-5 grid items-stretch gap-5;
  grid-template-columns: 1.3fr 0.7fr;
}

.hero-copy,
.hero-status,
.card {
  @apply rounded-[28px] border;
  background: var(--panel-bg);
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(18px);
  border-color: var(--line-soft);
}

.hero-copy {
  @apply relative overflow-hidden p-9;
}

.hero-copy::after {
  content: '';
  position: absolute;
  inset: auto -10% -35% 40%;
  height: 280px;
  background: radial-gradient(circle, rgba(186, 93, 55, 0.24), transparent 70%);
  pointer-events: none;
}

.hero-kicker,
.section-kicker {
  @apply text-[0.8rem] font-extrabold uppercase tracking-[0.18em];
  color: var(--accent-strong);
}

.hero-copy h1,
.section-head h2 {
  font-family: var(--font-display);
}

.hero-copy h1 {
  @apply mt-3 leading-[0.96] tracking-[-0.04em];
  max-width: 12ch;
  font-size: clamp(2.6rem, 5vw, 4.8rem);
}

.hero-text {
  @apply mt-4 text-[1.04rem];
  max-width: 52rem;
  color: var(--text-muted);
}

.hero-tags,
.metric-pills,
.action-row,
.session-strip,
.hero-metrics,
.query-controls,
.result-grid,
.form-grid,
.term-grid,
.snapshot-grid,
.drawer-grid,
.transcript-layout {
  @apply grid gap-3.5;
}

.hero-tags {
  @apply mt-5 flex flex-wrap;
}

.hero-tags span,
.inline-badge {
  @apply rounded-full border px-3.5 py-2 text-[0.85rem] font-bold;
  background: rgba(255, 255, 255, 0.72);
  color: var(--text-muted);
  border-color: rgba(25, 53, 69, 0.15);
}

.hero-status {
  @apply grid content-between gap-[18px] p-7;
}

.hero-status.is-live {
  background:
    linear-gradient(180deg, rgba(23, 77, 60, 0.92), rgba(18, 48, 38, 0.92)),
    var(--panel-bg);
  color: #f7f3ea;
}

.hero-status.is-live .status-pill,
.hero-status.is-live dt,
.hero-status.is-live dd {
  color: inherit;
}

.hero-status.is-ready {
  border-color: rgba(29, 90, 70, 0.22);
}

.hero-status.is-warning {
  border-color: rgba(180, 72, 54, 0.32);
}

.status-pill {
  @apply inline-flex self-start rounded-[20px] px-[18px] py-4;
  background: rgba(255, 255, 255, 0.1);
  flex-direction: column;
  gap: 6px;
}

.status-pill span,
.hero-metrics dt,
.field span,
.small-label,
.snapshot-grid dt {
  @apply text-[0.78rem] font-bold uppercase tracking-[0.08em];
  color: var(--text-muted);
}

.status-pill strong {
  @apply text-[1.4rem] leading-[1.1];
}

.hero-metrics {
  @apply grid-cols-2;
}

.hero-metrics div,
.session-strip article,
.snapshot-grid div {
  @apply border-t pt-3;
  border-top-color: rgba(255, 255, 255, 0.12);
}

.hero-metrics dd,
.session-strip strong,
.snapshot-grid dd {
  @apply mt-1.5 break-words font-bold;
}

.notice {
  @apply rounded-[18px] px-4 py-3 text-[0.95rem];
}

.notice-soft {
  @apply border;
  background: rgba(255, 251, 244, 0.72);
  color: var(--text-muted);
  border-color: var(--line-soft);
}

.notice-error {
  @apply border;
  background: rgba(250, 237, 231, 0.94);
  color: #8d2f20;
  border-color: rgba(168, 63, 48, 0.18);
}

.workspace-grid {
  @apply grid gap-5;
  grid-template-columns: 1.18fr 0.82fr;
}

.main-column,
.side-column {
  @apply grid gap-5;
}

.card {
  @apply p-[26px];
}

.section-head,
.mini-head,
.list-meta,
.quiz-head {
  @apply flex items-center justify-between gap-3;
}

.section-head {
  @apply mb-[18px];
}

.section-head h2 {
  @apply mt-1.5 text-[1.65rem] leading-[1.05];
}

.card-form .form-grid {
  @apply grid-cols-2;
}

.compact-grid {
  @apply grid-cols-2;
}

.field,
.checkbox-field {
  @apply grid gap-2;
}

.field-wide {
  grid-column: 1 / -1;
}

.field input,
.field textarea,
.field select {
  @apply w-full rounded-[18px] border bg-white/85 px-4 py-3.5 transition-[border-color,box-shadow,transform] duration-150 ease-in-out;
  background: rgba(255, 255, 255, 0.84);
  color: var(--text-main);
  border-color: var(--line-soft);
}

.field textarea {
  @apply resize-y;
  min-height: 118px;
}

.field input:focus,
.field textarea:focus,
.field select:focus {
  @apply outline-none;
  border-color: rgba(25, 53, 69, 0.42);
  box-shadow: 0 0 0 4px rgba(25, 53, 69, 0.08);
}

.advanced-panel {
  @apply mt-[18px] rounded-[22px] border border-dashed px-4 pt-3.5 pb-[18px];
  background: rgba(255, 255, 255, 0.36);
  border-color: var(--line-soft);
}

.advanced-panel summary,
.text-button {
  @apply cursor-pointer font-bold;
  color: var(--accent-strong);
}

.advanced-panel summary {
  list-style: none;
}

.advanced-panel summary::-webkit-details-marker {
  display: none;
}

.advanced-panel .form-grid {
  @apply mt-3.5 grid-cols-2;
}

.action-row {
  @apply mt-[18px] flex flex-wrap;
}

.button,
.text-button {
  border: none;
  background: none;
  font: inherit;
}

.button {
  @apply rounded-full px-[18px] py-3 font-bold;
  transition:
    transform 120ms ease,
    opacity 120ms ease,
    box-shadow 120ms ease;
}

.button:hover:not(:disabled),
.text-button:hover:not(:disabled) {
  transform: translateY(-1px);
}

.button:disabled,
.text-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.button-primary {
  background: linear-gradient(135deg, #173545, #274c63);
  color: #f8f5ef;
  box-shadow: 0 16px 30px rgba(19, 47, 60, 0.18);
}

.button-secondary {
  background: #f1eadc;
  color: #173545;
}

.button-accent {
  background: linear-gradient(135deg, #b85b37, #cf7c4a);
  color: #fff8f1;
}

.button-ghost {
  background: rgba(255, 255, 255, 0.76);
  color: var(--text-main);
}

.session-strip {
  @apply mt-5 grid-cols-4;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.session-strip article {
  border-top-color: var(--line-soft);
}

.session-strip span,
.qa-summary span {
  @apply text-[0.74rem] font-bold uppercase tracking-[0.08em];
  color: var(--text-muted);
}

.transcript-layout {
  grid-template-columns: 1.1fr 0.95fr 0.95fr;
}

.transcript-focus,
.transcript-column,
.subcard,
.study-block,
.quiz-card {
  @apply rounded-[24px] border p-[18px];
  background: rgba(255, 255, 255, 0.58);
  border-color: var(--line-soft);
}

.partial-bubble,
.answer-panel {
  border-radius: 22px;
  background:
    linear-gradient(180deg, rgba(24, 60, 49, 0.96), rgba(14, 36, 29, 0.96)),
    #112a21;
  color: #f8f4ed;
}

.partial-bubble {
  @apply mt-2.5 p-[18px] text-[1.1rem];
}

.answer-panel {
  @apply mt-4 p-[22px];
}

.answer-text {
  @apply mt-2 whitespace-pre-wrap leading-[1.7];
}

.placeholder {
  @apply leading-[1.6];
  color: var(--text-muted);
}

.mini-head {
  @apply mb-3.5;
}

.mini-head h3 {
  @apply text-base;
}

.transcript-list,
.result-list,
.bullet-list,
.option-list,
.event-list,
.quiz-stack {
  @apply grid list-none gap-3;
}

.transcript-list li,
.result-list li,
.event-list li {
  @apply rounded-[18px] p-3.5;
  background: rgba(251, 247, 238, 0.92);
}

.list-meta {
  @apply mb-2 text-[0.82rem];
  color: var(--text-muted);
}

.list-meta span:last-child {
  @apply text-right;
}

.query-controls {
  @apply items-end;
  grid-template-columns: 1fr 160px;
}

.checkbox-field {
  @apply mt-[22px] flex self-center items-center gap-2.5;
  color: var(--text-muted);
}

.checkbox-field input {
  inline-size: 18px;
  block-size: 18px;
  accent-color: #173545;
}

.qa-summary,
.result-grid,
.snapshot-grid,
.term-grid {
  @apply mt-[18px];
}

.qa-summary {
  @apply grid grid-cols-3 gap-3;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.qa-summary div {
  @apply border-t pt-3;
  border-top-color: var(--line-soft);
}

.qa-summary strong {
  @apply mt-1.5 block break-words;
}

.result-grid {
  @apply grid-cols-2;
}

.subcard small {
  color: var(--text-muted);
}

.study-stack {
  @apply mt-4 grid gap-3.5;
}

.bullet-list {
  @apply list-disc pl-[18px];
}

.term-grid {
  @apply grid-cols-2;
}

.term-card {
  @apply rounded-[20px] p-3.5;
  background: rgba(248, 242, 233, 0.92);
}

.term-card p {
  @apply mt-1.5;
  color: var(--text-muted);
}

.badge-warning {
  color: #8d2f20;
  border-color: rgba(168, 63, 48, 0.18);
  background: rgba(250, 237, 231, 0.94);
}

.quiz-stack {
  @apply mt-4;
}

.quiz-card {
  @apply grid gap-3;
}

.quiz-head span {
  @apply text-[0.82rem];
  color: var(--text-muted);
}

.quiz-question {
  @apply text-[1.04rem] font-bold;
}

.option-list {
  @apply list-decimal pl-5;
}

.session-card {
  @apply self-start;
}

.snapshot-grid {
  @apply grid-cols-2;
}

.debug-drawer {
  @apply mt-5 rounded-[26px] border px-4 pt-3 pb-4;
  background: rgba(246, 241, 231, 0.72);
  border-color: var(--line-soft);
}

.debug-drawer summary {
  @apply cursor-pointer font-bold;
}

.drawer-grid {
  @apply mt-3.5;
}

.drawer-card {
  @apply p-5;
}

.event-list pre {
  @apply overflow-auto whitespace-pre-wrap break-words;
  color: var(--text-muted);
}

@media (max-width: 1200px) {
  .hero-band,
  .workspace-grid,
  .transcript-layout,
  .result-grid {
    grid-template-columns: 1fr;
  }

  .session-strip,
  .qa-summary,
  .term-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 780px) {
  .study-shell {
    width: min(100vw - 20px, 100%);
    @apply pt-[18px] pb-9;
  }

  .hero-copy,
  .hero-status,
  .card {
    @apply rounded-[22px] p-5;
  }

  .hero-copy h1 {
    max-width: none;
    font-size: clamp(2.2rem, 11vw, 3.2rem);
  }

  .card-form .form-grid,
  .advanced-panel .form-grid,
  .compact-grid,
  .query-controls,
  .session-strip,
  .snapshot-grid,
  .qa-summary {
    grid-template-columns: 1fr;
  }

  .checkbox-field {
    @apply mt-0;
  }
}
</style>
