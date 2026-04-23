import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  buildWebSocketUrl,
  createSession as createSessionRequest,
  defaultBackendBaseUrl,
  fetchLessonAsset,
  fetchLessonTranscripts,
  fetchSessionAssets,
  fetchSessionTranscripts,
  uploadSessionAsset,
} from '../api/studyAgent'
import type {
  LessonAssetItem,
  MicrophoneOption,
  ModelKey,
  ModelOption,
  RealtimeEvent,
  SessionInfo,
  TranscriptEntry,
  TranscriptRecordItem,
  WebSocketState,
} from '../types/study'

const sessionModelOptions: ModelOption[] = [
  { label: 'paraformer-zh', value: 'paraformer-zh' },
  { label: 'paraformer-zh-streaming', value: 'paraformer-zh-streaming' },
  { label: 'paraformer-zh-streaming-2pass', value: 'paraformer-zh-streaming-2pass' },
]

const sessionClientId = 'web-frontend'
const defaultSampleRate = 16000
const defaultChannels = 1
const lastLessonStorageKey = 'study-agent:last-active-lesson'

type LessonSnapshotStatus = 'active' | 'stopped' | 'interrupted'
type RefineStatusToastKind = 'syncing' | 'processing' | 'error'

interface LessonSnapshot {
  session_id: string
  course_id: string
  lesson_id: string
  subject?: string | null
  model_name?: string | null
  sample_rate: number
  channels: number
  status: LessonSnapshotStatus
  updated_at: number
}

interface RefineStatusToast {
  id: number
  visible: boolean
  kind: RefineStatusToastKind
  title: string
  message: string
  detail?: string
}

function toMilliseconds(timestamp?: number): number {
  if (!timestamp) {
    return Date.now()
  }
  return timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000
}

function mapTranscriptItem(sessionId: string, item: TranscriptRecordItem): TranscriptEntry | null {
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

export const useSessionStore = defineStore('session', () => {
  const backendBaseUrl = ref(defaultBackendBaseUrl)
  const subject = ref('Web 开发课堂')
  const model = ref<ModelKey>('paraformer-zh')
  const modelOptions = ref<ModelOption[]>([...sessionModelOptions])
  const microphone = ref('default')
  const microphones = ref<MicrophoneOption[]>([{ id: 'default', label: '默认麦克风' }])
  const recording = ref(false)
  const initializing = ref(false)
  const loadingMicrophones = ref(false)
  const websocketState = ref<WebSocketState>('closed')
  const errorMessage = ref('')
  const partialTranscript = ref('')
  const transcriptList = ref<TranscriptEntry[]>([])
  const sessionInfo = ref<SessionInfo | null>(null)
  const audioFrameCount = ref(0)
  const audioPeak = ref(0)
  const audioRms = ref(0)
  const refineStatusToast = ref<RefineStatusToast | null>(null)
  const assetList = ref<LessonAssetItem[]>([])
  const assetUploading = ref(false)
  const assetErrorMessage = ref('')

  const transcriptCount = computed(() => transcriptList.value.length)
  const assetCount = computed(() => assetList.value.length)
  const currentSessionId = computed(() => sessionInfo.value?.session_id || '')
  const currentCourseId = computed(() => sessionInfo.value?.course_id || '')
  const currentLessonId = computed(() => sessionInfo.value?.lesson_id || '')
  const recordButtonBusy = computed(
    () => initializing.value || loadingMicrophones.value || websocketState.value === 'connecting',
  )
  const sessionStageLabel = computed(() => {
    if (recording.value) {
      return '录音中'
    }
    if (websocketState.value === 'open' || websocketState.value === 'connecting') {
      return '连接中'
    }
    if (sessionInfo.value) {
      return '已创建会话'
    }
    return '待启动'
  })

  let websocket: WebSocket | null = null
  let socketConnectPromise: Promise<void> | null = null
  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let mediaSourceNode: MediaStreamAudioSourceNode | null = null
  let processorNode: ScriptProcessorNode | null = null
  let muteGainNode: GainNode | null = null
  let lastSessionConfigSignature = ''
  let lastLessonConfigSignature = ''
  let promptBeforeNextStart = false

  function currentSessionConfigSignature(): string {
    return JSON.stringify({
      subject: subject.value.trim(),
      model: model.value,
      sampleRate: defaultSampleRate,
      channels: defaultChannels,
    })
  }

  function currentLessonConfigSignature(): string {
    return JSON.stringify({
      subject: subject.value.trim(),
      sampleRate: defaultSampleRate,
      channels: defaultChannels,
    })
  }

  function loadLastLessonSnapshot(): LessonSnapshot | null {
    if (typeof window === 'undefined') {
      return null
    }

    const raw = window.localStorage.getItem(lastLessonStorageKey)
    if (!raw) {
      return null
    }

    try {
      const payload = JSON.parse(raw) as Partial<LessonSnapshot>
      if (!payload.course_id || !payload.lesson_id || !payload.session_id) {
        return null
      }
      return {
        session_id: String(payload.session_id),
        course_id: String(payload.course_id),
        lesson_id: String(payload.lesson_id),
        subject: payload.subject ? String(payload.subject) : null,
        model_name: payload.model_name ? String(payload.model_name) : null,
        sample_rate: Number(payload.sample_rate || defaultSampleRate),
        channels: Number(payload.channels || defaultChannels),
        status: payload.status || 'stopped',
        updated_at: Number(payload.updated_at || Date.now()),
      }
    } catch {
      return null
    }
  }

  function saveLessonSnapshot(status: LessonSnapshotStatus): void {
    if (typeof window === 'undefined' || !sessionInfo.value) {
      return
    }

    const snapshot: LessonSnapshot = {
      session_id: sessionInfo.value.session_id,
      course_id: sessionInfo.value.course_id,
      lesson_id: sessionInfo.value.lesson_id,
      subject: sessionInfo.value.subject || subject.value.trim() || null,
      model_name: sessionInfo.value.model_name || model.value,
      sample_rate: sessionInfo.value.sample_rate || defaultSampleRate,
      channels: sessionInfo.value.channels || defaultChannels,
      status,
      updated_at: Date.now(),
    }
    window.localStorage.setItem(lastLessonStorageKey, JSON.stringify(snapshot))
  }

  function buildCurrentLessonSnapshot(): LessonSnapshot | null {
    if (!sessionInfo.value) {
      return null
    }
    return {
      session_id: sessionInfo.value.session_id,
      course_id: sessionInfo.value.course_id,
      lesson_id: sessionInfo.value.lesson_id,
      subject: sessionInfo.value.subject || subject.value.trim() || null,
      model_name: sessionInfo.value.model_name || model.value,
      sample_rate: sessionInfo.value.sample_rate || defaultSampleRate,
      channels: sessionInfo.value.channels || defaultChannels,
      status: recording.value ? 'active' : 'stopped',
      updated_at: Date.now(),
    }
  }

  function confirmContinueLesson(snapshot: LessonSnapshot): boolean {
    if (!snapshot) {
      return false
    }

    if (typeof window === 'undefined' || typeof window.confirm !== 'function') {
      return true
    }

    const updatedAt = new Date(snapshot.updated_at).toLocaleString('zh-CN', { hour12: false })
    const title = snapshot.subject || snapshot.course_id
    return window.confirm(
      [
        `检测到上一次课程：${title}`,
        `Lesson: ${snapshot.lesson_id}`,
        `最后记录时间：${updatedAt}`,
        '',
        '是否继续上一次课程？',
        '确定：继续同一节课；取消：开始新一节课。',
      ].join('\n'),
    )
  }

  function chooseResumeSnapshot(): LessonSnapshot | null {
    const snapshot = loadLastLessonSnapshot()
    if (!snapshot) {
      return null
    }
    return confirmContinueLesson(snapshot) ? snapshot : null
  }

  function applyResumeSnapshot(snapshot: LessonSnapshot): void {
    if (snapshot.subject?.trim()) {
      subject.value = snapshot.subject.trim()
    }
  }

  function resetSessionPanels(): void {
    transcriptList.value = []
    assetList.value = []
    assetErrorMessage.value = ''
    partialTranscript.value = ''
    audioFrameCount.value = 0
    audioPeak.value = 0
    audioRms.value = 0
  }

  function showRefineStatusToast(payload: Omit<RefineStatusToast, 'id' | 'visible'>): void {
    refineStatusToast.value = {
      id: Date.now(),
      visible: true,
      ...payload,
    }
  }

  function dismissRefineStatusToast(id?: number): void {
    if (!refineStatusToast.value) {
      return
    }
    if (id !== undefined && refineStatusToast.value.id !== id) {
      return
    }
    refineStatusToast.value = {
      ...refineStatusToast.value,
      visible: false,
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
    saveLessonSnapshot(recording.value ? 'active' : 'stopped')
  }

  function appendTranscriptEntry(entry: TranscriptEntry): void {
    transcriptList.value = [...transcriptList.value, entry]
  }

  function handleRealtimeEvent(payload: RealtimeEvent): void {
    updateSessionFromEvent(payload)

    switch (payload.type) {
      case 'partial_transcript':
        partialTranscript.value = typeof payload.text === 'string' ? payload.text.trim() : ''
        break
      case 'final_transcript':
        if (typeof payload.text === 'string' && payload.text.trim()) {
          partialTranscript.value = ''
          appendTranscriptEntry({
            id: `live-${payload.seq ?? Date.now()}`,
            timestamp: toMilliseconds(payload.timestamp),
            text: payload.text.trim(),
            sourceType: 'realtime',
          })
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
        errorMessage.value =
          typeof payload.error === 'string' && payload.error.trim()
            ? payload.error
            : '实时语音服务出现异常。'
        break
      default:
        break
    }
  }

  async function fetchMicrophones(): Promise<void> {
    loadingMicrophones.value = true
    try {
      if (!navigator.mediaDevices?.enumerateDevices) {
        microphones.value = [{ id: 'default', label: '当前浏览器不支持设备枚举' }]
        microphone.value = 'default'
        return
      }

      try {
        const permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        permissionStream.getTracks().forEach((track) => track.stop())
      } catch {
        // 即使没有拿到权限，也继续尝试列出设备。
      }

      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs = devices
        .filter((device) => device.kind === 'audioinput')
        .map((device, index) => ({
          id: device.deviceId || `microphone-${index + 1}`,
          label: device.label || `麦克风 ${index + 1}`,
        }))

      microphones.value = inputs.length > 0 ? inputs : [{ id: 'default', label: '默认麦克风' }]
      if (!microphones.value.some((item) => item.id === microphone.value)) {
        microphone.value = microphones.value[0]?.id || 'default'
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '获取麦克风列表失败。'
    } finally {
      loadingMicrophones.value = false
    }
  }

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
    const mapped = response.items
      .map((item) => mapTranscriptItem(item.session_id || response.session_id || sessionInfo.value?.session_id || '', item))
      .filter((item): item is TranscriptEntry => item !== null)
      .sort((left, right) => left.timestamp - right.timestamp)

    transcriptList.value = mapped
  }

  async function createRealtimeSession(): Promise<SessionInfo> {
    const signature = currentSessionConfigSignature()
    const lessonSignature = currentLessonConfigSignature()

    if (sessionInfo.value && lastSessionConfigSignature === signature && !promptBeforeNextStart) {
      return sessionInfo.value
    }

    let lessonSnapshot: LessonSnapshot | null = null
    const currentLessonSnapshot = buildCurrentLessonSnapshot()

    if (promptBeforeNextStart && currentLessonSnapshot) {
      lessonSnapshot = confirmContinueLesson(currentLessonSnapshot) ? currentLessonSnapshot : null
    } else if (
      sessionInfo.value &&
      currentLessonSnapshot &&
      lastLessonConfigSignature === lessonSignature
    ) {
      // Model changes create a fresh ASR session but keep the lesson boundary.
      lessonSnapshot = currentLessonSnapshot
    } else {
      lessonSnapshot = chooseResumeSnapshot()
      if (lessonSnapshot) {
        applyResumeSnapshot(lessonSnapshot)
      }
    }

    if (!lessonSnapshot) {
      resetSessionPanels()
    }

    const response = await createSessionRequest(
      {
        subject: subject.value.trim() || undefined,
        course_id: lessonSnapshot?.course_id,
        lesson_id: lessonSnapshot?.lesson_id,
        client_id: sessionClientId,
        sample_rate: defaultSampleRate,
        channels: defaultChannels,
        model_name: model.value,
      },
      backendBaseUrl.value,
    )

    sessionInfo.value = response
    lastSessionConfigSignature = currentSessionConfigSignature()
    lastLessonConfigSignature = currentLessonConfigSignature()
    promptBeforeNextStart = false
    saveLessonSnapshot('active')
    if (lessonSnapshot) {
      await hydrateTranscriptsFromServer()
    }
    await refreshSessionAssets()
    return response
  }

  async function ensureSession(): Promise<SessionInfo> {
    if (recording.value) {
      throw new Error('录音过程中不能重建会话。')
    }

    return createRealtimeSession()
  }

  function upsertAsset(asset: LessonAssetItem): void {
    const next = [...assetList.value]
    const index = next.findIndex((item) => item.asset_id === asset.asset_id)
    if (index >= 0) {
      next[index] = asset
    } else {
      next.unshift(asset)
    }
    assetList.value = next
  }

  async function refreshSessionAssets(): Promise<void> {
    if (!sessionInfo.value) {
      assetList.value = []
      return
    }
    const response = await fetchSessionAssets(sessionInfo.value.session_id, backendBaseUrl.value)
    assetList.value = response.items
  }

  async function pollAssetStatus(assetId: string): Promise<void> {
    const startedAt = Date.now()
    const timeoutMs = 10 * 60 * 1000
    const finalStatuses = new Set(['done', 'failed', 'indexing_failed'])

    while (Date.now() - startedAt < timeoutMs) {
      const response = await fetchLessonAsset(assetId, backendBaseUrl.value)
      upsertAsset(response.item)
      if (finalStatuses.has(response.item.status)) {
        if (response.item.status === 'done') {
          await hydrateTranscriptsFromServer()
        }
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 3000))
    }
  }

  async function uploadLessonAsset(file: File): Promise<void> {
    assetUploading.value = true
    assetErrorMessage.value = ''
    try {
      const activeSession = await ensureSession()
      const response = await uploadSessionAsset(activeSession.session_id, file, backendBaseUrl.value)
      upsertAsset(response.item)
      void pollAssetStatus(response.item.asset_id)
    } catch (error) {
      assetErrorMessage.value = error instanceof Error ? error.message : '上传课堂素材失败。'
    } finally {
      assetUploading.value = false
    }
  }

  function downsampleBuffer(
    source: Float32Array,
    sourceRate: number,
    targetRate: number,
  ): Float32Array {
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

  async function disconnectWebSocket(): Promise<void> {
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
    websocketState.value = 'connecting'

    const currentSocket = new WebSocket(
      buildWebSocketUrl(sessionInfo.value.session_id, backendBaseUrl.value),
    )
    websocket = currentSocket

    socketConnectPromise = new Promise<void>((resolve, reject) => {
      let handshakeCompleted = false

      currentSocket.onopen = () => {
        handshakeCompleted = true
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
          // 忽略后端发来的非 JSON 文本。
        }
      }

      currentSocket.onerror = () => {
        errorMessage.value = 'WebSocket 连接失败。'
        if (!handshakeCompleted) {
          websocketState.value = 'closed'
          websocket = null
          socketConnectPromise = null
          reject(new Error('WebSocket 连接失败。'))
        }
      }

      currentSocket.onclose = (event) => {
        if (websocket === currentSocket) {
          websocket = null
        }
        websocketState.value = 'closed'
        socketConnectPromise = null
        if (!handshakeCompleted) {
          reject(new Error(event.reason || 'WebSocket 已关闭。'))
        }
      }
    })

    return socketConnectPromise
  }

  async function startRecording(): Promise<void> {
    if (recording.value || initializing.value) {
      return
    }

    initializing.value = true
    errorMessage.value = ''

    try {
      const activeSession = await ensureSession()
      await connectWebSocket()
      await releaseAudioResources()

      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          deviceId:
            microphone.value && microphone.value !== 'default'
              ? { exact: microphone.value }
              : undefined,
          channelCount: 1,
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
        video: false,
      })

      const targetSampleRate = activeSession.sample_rate || defaultSampleRate
      audioContext = new AudioContext({ sampleRate: targetSampleRate })
      await audioContext.resume()

      mediaSourceNode = audioContext.createMediaStreamSource(mediaStream)
      processorNode = audioContext.createScriptProcessor(4096, 1, 1)
      muteGainNode = audioContext.createGain()
      muteGainNode.gain.value = 0
      recording.value = true
      saveLessonSnapshot('active')

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
          errorMessage.value = error instanceof Error ? error.message : '发送音频数据失败。'
        }
      }

      mediaSourceNode.connect(processorNode)
      processorNode.connect(muteGainNode)
      muteGainNode.connect(audioContext.destination)
    } catch (error) {
      recording.value = false
      await releaseAudioResources()
      await disconnectWebSocket()
      promptBeforeNextStart = true
      saveLessonSnapshot('interrupted')
      errorMessage.value = error instanceof Error ? error.message : '启动录音失败。'
    } finally {
      initializing.value = false
    }
  }

  async function stopRecording(): Promise<void> {
    const stoppedSession = sessionInfo.value
    if (stoppedSession) {
      showRefineStatusToast({
        kind: 'syncing',
        title: '正在收尾录音',
        message: '正在同步最后几段转写，随后会交给 DeepSeek 后台精修。',
        detail: `${stoppedSession.course_id} / ${stoppedSession.lesson_id}`,
      })
    }

    recording.value = false
    await releaseAudioResources()
    await disconnectWebSocket()

    try {
      await hydrateTranscriptsFromServer()
      if (stoppedSession) {
        showRefineStatusToast({
          kind: 'processing',
          title: '转写精修已开始',
          message: 'DeepSeek 正在后台整理本节转写，稍后可在历史回顾里查看 LLM 精修结果。',
          detail: `${stoppedSession.course_id} / ${stoppedSession.lesson_id}`,
        })
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '同步转写记录失败。'
      if (stoppedSession) {
        showRefineStatusToast({
          kind: 'error',
          title: '转写同步失败',
          message: '录音已停止，但前端同步转写失败；后台精修可能仍在继续。',
          detail: error instanceof Error ? error.message : undefined,
        })
      }
    } finally {
      promptBeforeNextStart = true
      saveLessonSnapshot('stopped')
    }
  }

  async function toggleRecording(): Promise<void> {
    if (recording.value) {
      await stopRecording()
      return
    }
    await startRecording()
  }

  async function cleanup(): Promise<void> {
    const wasRecording = recording.value
    recording.value = false
    await releaseAudioResources()
    await disconnectWebSocket()
    if (sessionInfo.value) {
      promptBeforeNextStart = true
    }
    saveLessonSnapshot(wasRecording ? 'interrupted' : 'stopped')
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', () => {
      saveLessonSnapshot(recording.value ? 'interrupted' : 'stopped')
    })
  }

  return {
    assetCount,
    assetErrorMessage,
    assetList,
    assetUploading,
    audioFrameCount,
    audioPeak,
    audioRms,
    backendBaseUrl,
    cleanup,
    currentCourseId,
    currentLessonId,
    currentSessionId,
    dismissRefineStatusToast,
    errorMessage,
    fetchMicrophones,
    refreshSessionAssets,
    initializing,
    loadingMicrophones,
    microphone,
    microphones,
    model,
    modelOptions,
    partialTranscript,
    recordButtonBusy,
    recording,
    refineStatusToast,
    sessionInfo,
    sessionStageLabel,
    startRecording,
    stopRecording,
    subject,
    toggleRecording,
    transcriptCount,
    transcriptList,
    uploadLessonAsset,
    websocketState,
  }
})
