import type { Ref } from 'vue'

import { buildWebSocketUrl } from '../../api/studyAgent'
import type {
  RealtimeEvent,
  SessionInfo,
  WebSocketState,
} from '../../types/study'
import { defaultSampleRate } from './constants'
import type { LessonSnapshotStatus, RefineStatusToast } from './types'

export function createRealtimeAudioActions(args: {
  backendBaseUrl: Ref<string>
  sessionInfo: Ref<SessionInfo | null>
  microphone: Ref<string>
  recording: Ref<boolean>
  initializing: Ref<boolean>
  websocketState: Ref<WebSocketState>
  errorMessage: Ref<string>
  audioFrameCount: Ref<number>
  promptBeforeNextStart: Ref<boolean>
  ensureSession: () => Promise<SessionInfo>
  handleRealtimeEvent: (payload: RealtimeEvent) => void
  hydrateTranscriptsFromServer: () => Promise<void>
  saveLessonSnapshot: (status: LessonSnapshotStatus) => void
  showRefineStatusToast: (payload: Omit<RefineStatusToast, 'id' | 'visible'>) => void
}) {
  const {
    backendBaseUrl,
    sessionInfo,
    microphone,
    recording,
    initializing,
    websocketState,
    errorMessage,
    audioFrameCount,
    promptBeforeNextStart,
    ensureSession,
    handleRealtimeEvent,
    hydrateTranscriptsFromServer,
    saveLessonSnapshot,
    showRefineStatusToast,
  } = args

  let websocket: WebSocket | null = null
  let socketConnectPromise: Promise<void> | null = null
  let mediaStream: MediaStream | null = null
  let audioContext: AudioContext | null = null
  let mediaSourceNode: MediaStreamAudioSourceNode | null = null
  let processorNode: ScriptProcessorNode | null = null
  let muteGainNode: GainNode | null = null

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
      promptBeforeNextStart.value = true
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
      promptBeforeNextStart.value = true
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
      promptBeforeNextStart.value = true
    }
    saveLessonSnapshot(wasRecording ? 'interrupted' : 'stopped')
  }

  return {
    cleanup,
    startRecording,
    stopRecording,
    toggleRecording,
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
