import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  buildWebSocketUrl,
  createSession as createSessionRequest,
  defaultBackendBaseUrl,
  fetchSessionTranscripts,
} from '../api/studyAgent'
import type {
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
]

const sessionClientId = 'web-frontend'
const defaultSampleRate = 16000
const defaultChannels = 1

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

  const transcriptCount = computed(() => transcriptList.value.length)
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

  function currentSessionConfigSignature(): string {
    return JSON.stringify({
      subject: subject.value.trim(),
      model: model.value,
      sampleRate: defaultSampleRate,
      channels: defaultChannels,
    })
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

    const response = await fetchSessionTranscripts(sessionInfo.value.session_id, backendBaseUrl.value)
    const mapped = response.items
      .map((item) => mapTranscriptItem(response.session_id, item))
      .filter((item): item is TranscriptEntry => item !== null)
      .sort((left, right) => left.timestamp - right.timestamp)

    transcriptList.value = mapped
  }

  async function createRealtimeSession(): Promise<SessionInfo> {
    const signature = currentSessionConfigSignature()

    if (sessionInfo.value && lastSessionConfigSignature === signature) {
      return sessionInfo.value
    }

    transcriptList.value = []
    partialTranscript.value = ''
    audioFrameCount.value = 0
    audioPeak.value = 0
    audioRms.value = 0

    const response = await createSessionRequest(
      {
        subject: subject.value.trim() || undefined,
        client_id: sessionClientId,
        sample_rate: defaultSampleRate,
        channels: defaultChannels,
        model_name: model.value,
      },
      backendBaseUrl.value,
    )

    sessionInfo.value = response
    lastSessionConfigSignature = signature
    return response
  }

  async function ensureSession(): Promise<SessionInfo> {
    if (recording.value) {
      throw new Error('录音过程中不能重建会话。')
    }

    return createRealtimeSession()
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
      errorMessage.value = error instanceof Error ? error.message : '启动录音失败。'
    } finally {
      initializing.value = false
    }
  }

  async function stopRecording(): Promise<void> {
    recording.value = false
    await releaseAudioResources()
    await disconnectWebSocket()

    try {
      await hydrateTranscriptsFromServer()
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '同步转写记录失败。'
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
    recording.value = false
    await releaseAudioResources()
    await disconnectWebSocket()
  }

  return {
    audioFrameCount,
    audioPeak,
    audioRms,
    backendBaseUrl,
    cleanup,
    currentCourseId,
    currentLessonId,
    currentSessionId,
    errorMessage,
    fetchMicrophones,
    initializing,
    loadingMicrophones,
    microphone,
    microphones,
    model,
    modelOptions,
    partialTranscript,
    recordButtonBusy,
    recording,
    sessionInfo,
    sessionStageLabel,
    startRecording,
    stopRecording,
    subject,
    toggleRecording,
    transcriptCount,
    transcriptList,
    websocketState,
  }
})
