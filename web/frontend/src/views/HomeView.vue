<template>
  <main class="debug-page">
    <section class="hero">
      <p class="eyebrow">Realtime Speech Debugger</p>
      <h1>浏览器到后端的语音流联调台</h1>
      <p class="hero-copy">
        先创建会话，再建立 WebSocket，最后开始录音。页面会直接展示后端返回的
        `partial_transcript`、`final_transcript` 和连接事件。
      </p>
    </section>

    <section class="grid">
      <article class="panel controls">
        <h2>连接控制</h2>

        <label class="field">
          <span>HTTP 后端地址</span>
          <input v-model.trim="backendHttpUrl" type="text" placeholder="http://127.0.0.1:8000" />
        </label>

        <label class="field">
          <span>课程 / 主题</span>
          <input v-model.trim="subject" type="text" placeholder="例如：高数复习" />
        </label>

        <label class="field">
          <span>客户端标识</span>
          <input v-model.trim="clientId" type="text" placeholder="例如：chrome-debug" />
        </label>

        <label class="field">
          <span>Model</span>
          <select v-model="modelName" class="select">
            <option v-for="model in modelOptions" :key="model.value" :value="model.value">
              {{ model.label }}
            </option>
          </select>
        </label>

        <label class="field">
          <span>麦克风设备</span>
          <select v-model="selectedInputDeviceId" class="select">
            <option value="">系统默认麦克风</option>
            <option v-for="device in inputDevices" :key="device.deviceId" :value="device.deviceId">
              {{ device.label || `microphone-${device.deviceId.slice(0, 6)}` }}
            </option>
          </select>
        </label>

        <div class="actions">
          <button class="button" @click="loadInputDevices" :disabled="loadingDevices">
            {{ loadingDevices ? '加载设备中...' : '刷新麦克风列表' }}
          </button>
          <button class="button primary" @click="createSession" :disabled="creatingSession">
            {{ creatingSession ? '创建中...' : '创建 Session' }}
          </button>
          <button class="button" @click="connectSocket" :disabled="connectingSocket || !sessionId || isSocketOpen">
            {{ connectingSocket ? '连接中...' : '连接 WebSocket' }}
          </button>
          <button class="button" @click="disconnectSocket" :disabled="!websocket">
            断开连接
          </button>
        </div>

        <div class="actions">
          <button class="button accent" @click="startRecording" :disabled="!isSocketOpen || isRecording">
            开始录音
          </button>
          <button class="button danger" @click="stopRecording" :disabled="!isRecording">
            停止录音
          </button>
          <button class="button" @click="resetView">
            清空面板
          </button>
        </div>

        <dl class="status-list">
          <div>
            <dt>Session ID</dt>
            <dd>{{ sessionId || '未创建' }}</dd>
          </div>
          <div>
            <dt>WebSocket</dt>
            <dd>{{ socketStatus }}</dd>
          </div>
          <div>
            <dt>Model</dt>
            <dd>{{ currentModelName || modelName || 'default' }}</dd>
          </div>
          <div>
            <dt>录音状态</dt>
            <dd>{{ isRecording ? 'recording' : 'stopped' }}</dd>
          </div>
          <div>
            <dt>已发现设备</dt>
            <dd>{{ inputDevices.length }}</dd>
          </div>
          <div>
            <dt>WS 地址</dt>
            <dd class="mono">{{ backendWsUrl }}</dd>
          </div>
        </dl>

        <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
      </article>

      <article class="panel transcript">
        <h2>实时结果</h2>
        <div class="transcript-block">
          <span class="label">Partial</span>
          <p>{{ partialText || '等待后端返回中间转写...' }}</p>
        </div>

        <div class="transcript-block">
          <span class="label">Final</span>
          <ul v-if="finalTexts.length" class="final-list">
            <li v-for="item in finalTexts" :key="item.seq">
              <span class="seq">#{{ item.seq }}</span>
              <span>{{ item.text }}</span>
            </li>
          </ul>
          <p v-else>还没有最终转写。</p>
        </div>
      </article>

      <article class="panel metrics">
        <h2>音频指标</h2>
        <dl class="status-list">
          <div>
            <dt>RMS</dt>
            <dd>{{ audioMetrics.rms ?? '-' }}</dd>
          </div>
          <div>
            <dt>Peak</dt>
            <dd>{{ audioMetrics.peak ?? '-' }}</dd>
          </div>
          <div>
            <dt>事件数</dt>
            <dd>{{ events.length }}</dd>
          </div>
        </dl>
      </article>

      <article class="panel transcript">
        <div class="panel-head">
          <h2>Persisted</h2>
          <button class="button ghost" @click="fetchPersistedTranscripts" :disabled="loadingPersisted || !sessionId">
            {{ loadingPersisted ? 'Loading...' : 'Refresh' }}
          </button>
        </div>
        <ul v-if="persistedTranscripts.length" class="final-list">
          <li v-for="item in persistedTranscripts" :key="item.chunk_id">
            <span class="seq">#{{ item.chunk_id }}</span>
            <span>{{ item.clean_text || item.text }}</span>
          </li>
        </ul>
        <p v-else>{{ sessionId ? 'No persisted transcripts yet.' : 'Create a session first.' }}</p>
      </article>

      <article class="panel events">
        <div class="panel-head">
          <h2>事件流</h2>
          <button class="button ghost" @click="events = []">清空</button>
        </div>
        <ul class="event-list">
          <li v-for="item in events" :key="item.id">
            <div class="event-meta">
              <span class="event-type">{{ item.type }}</span>
              <span class="mono">seq={{ item.seq ?? '-' }}</span>
              <span>{{ item.time }}</span>
            </div>
            <pre>{{ item.payload }}</pre>
          </li>
        </ul>
      </article>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

type BackendEvent = {
  type: string
  session_id?: string
  seq?: number
  text?: string
  rms?: number
  peak?: number
  [key: string]: unknown
}

type EventLogItem = {
  id: string
  type: string
  seq?: number
  time: string
  payload: string
}

type InputDeviceOption = {
  deviceId: string
  label: string
}

type PersistedTranscriptItem = {
  chunk_id: number
  text: string
  clean_text: string
}

type ModelOption = {
  value: string
  label: string
}

const modelOptions: ModelOption[] = [
  { value: 'paraformer-zh', label: 'paraformer-zh' },
  { value: 'paraformer-zh-streaming', label: 'paraformer-zh-streaming' },
]

const backendHttpUrl = ref('http://127.0.0.1:8000')
const subject = ref('语音联调')
const clientId = ref('browser-debug')
const modelName = ref('paraformer-zh')

const sessionId = ref('')
const currentModelName = ref('')
const socketStatus = ref('idle')
const partialText = ref('')
const finalTexts = ref<Array<{ seq: number; text: string }>>([])
const events = ref<EventLogItem[]>([])
const errorMessage = ref('')
const creatingSession = ref(false)
const connectingSocket = ref(false)
const isRecording = ref(false)
const loadingDevices = ref(false)
const audioMetrics = ref<{ rms?: string; peak?: string }>({})
const inputDevices = ref<InputDeviceOption[]>([])
const selectedInputDeviceId = ref('')
const persistedTranscripts = ref<PersistedTranscriptItem[]>([])
const loadingPersisted = ref(false)

let websocket: WebSocket | null = null
let mediaStream: MediaStream | null = null
let audioContext: AudioContext | null = null
let sourceNode: MediaStreamAudioSourceNode | null = null
let processorNode: ScriptProcessorNode | null = null

const isSocketOpen = computed(() => socketStatus.value === 'open')

const backendWsUrl = computed(() => {
  try {
    const url = new URL(backendHttpUrl.value)
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
    url.pathname = sessionId.value ? `/ws/audio/${sessionId.value}` : '/ws/audio/{session_id}'
    url.search = ''
    url.hash = ''
    return url.toString()
  } catch {
    return 'ws://invalid-url/ws/audio/{session_id}'
  }
})

function pushEvent(event: BackendEvent | Record<string, unknown>) {
  const normalized = event as BackendEvent
  events.value.unshift({
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    type: normalized.type ?? 'unknown',
    seq: normalized.seq,
    time: new Date().toLocaleTimeString(),
    payload: JSON.stringify(event, null, 2),
  })
}

async function loadInputDevices() {
  errorMessage.value = ''
  loadingDevices.value = true

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((track) => track.stop())

    const devices = await navigator.mediaDevices.enumerateDevices()
    inputDevices.value = devices
      .filter((device) => device.kind === 'audioinput')
      .map((device) => ({
        deviceId: device.deviceId,
        label: device.label,
      }))

    if (
      selectedInputDeviceId.value &&
      !inputDevices.value.some((device) => device.deviceId === selectedInputDeviceId.value)
    ) {
      selectedInputDeviceId.value = ''
    }

    pushEvent({
      type: 'input_devices_loaded',
      count: inputDevices.value.length,
      selected_device_id: selectedInputDeviceId.value || null,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'load input devices failed'
  } finally {
    loadingDevices.value = false
  }
}

async function createSession() {
  errorMessage.value = ''
  creatingSession.value = true
  try {
    const response = await fetch(`${backendHttpUrl.value}/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        subject: subject.value || null,
        client_id: clientId.value || null,
        sample_rate: 16000,
        channels: 1,
        model_name: modelName.value || null,
      }),
    })

    if (!response.ok) {
      throw new Error(`create session failed: ${response.status}`)
    }

    const data = (await response.json()) as { session_id: string; model_name?: string | null }
    sessionId.value = data.session_id
    currentModelName.value = data.model_name ?? ''
    persistedTranscripts.value = []
    pushEvent({ type: 'session_created', ...data })
    await fetchPersistedTranscripts()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'create session failed'
  } finally {
    creatingSession.value = false
  }
}

async function fetchPersistedTranscripts() {
  if (!sessionId.value) {
    persistedTranscripts.value = []
    return
  }

  loadingPersisted.value = true
  try {
    const response = await fetch(`${backendHttpUrl.value}/sessions/${sessionId.value}/transcripts`)
    if (!response.ok) {
      throw new Error(`fetch transcripts failed: ${response.status}`)
    }

    const data = (await response.json()) as { items?: PersistedTranscriptItem[] }
    persistedTranscripts.value = Array.isArray(data.items) ? data.items.slice().reverse() : []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'fetch transcripts failed'
  } finally {
    loadingPersisted.value = false
  }
}

async function connectSocket() {
  errorMessage.value = ''
  if (!sessionId.value) {
    await createSession()
  }
  if (!sessionId.value || websocket) {
    return
  }

  connectingSocket.value = true
  socketStatus.value = 'connecting'

  try {
    websocket = new WebSocket(backendWsUrl.value)

    websocket.onopen = () => {
      socketStatus.value = 'open'
      connectingSocket.value = false
      pushEvent({ type: 'socket_open', session_id: sessionId.value })
    }

    websocket.onmessage = (event) => {
      const payload = JSON.parse(event.data) as BackendEvent
      pushEvent(payload)

      if (payload.type === 'partial_transcript') {
        partialText.value = payload.text ?? ''
      }

      if (payload.type === 'final_transcript' && payload.text) {
        finalTexts.value.unshift({
          seq: payload.seq ?? finalTexts.value.length + 1,
          text: payload.text,
        })
        partialText.value = ''
        void fetchPersistedTranscripts()
      }

      if (payload.type === 'audio_metrics') {
        audioMetrics.value = {
          rms: typeof payload.rms === 'number' ? payload.rms.toFixed(4) : '-',
          peak: typeof payload.peak === 'number' ? payload.peak.toFixed(4) : '-',
        }
      }
    }

    websocket.onerror = () => {
      errorMessage.value = 'websocket error'
      socketStatus.value = 'error'
    }

    websocket.onclose = () => {
      socketStatus.value = 'closed'
      websocket = null
      connectingSocket.value = false
      stopRecording()
      pushEvent({ type: 'socket_closed', session_id: sessionId.value })
    }
  } catch (error) {
    connectingSocket.value = false
    socketStatus.value = 'error'
    websocket = null
    errorMessage.value = error instanceof Error ? error.message : 'connect websocket failed'
  }
}

function disconnectSocket() {
  stopRecording()
  websocket?.close()
  websocket = null
  socketStatus.value = 'closed'
}

function resetView() {
  partialText.value = ''
  finalTexts.value = []
  persistedTranscripts.value = []
  events.value = []
  errorMessage.value = ''
  audioMetrics.value = {}
}

function downsampleBuffer(buffer: Float32Array, inputRate: number, outputRate: number) {
  if (outputRate === inputRate) {
    return buffer
  }

  const ratio = inputRate / outputRate
  const outputLength = Math.round(buffer.length / ratio)
  const result = new Float32Array(outputLength)

  let offsetResult = 0
  let offsetBuffer = 0

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * ratio)
    let accum = 0
    let count = 0

    for (let index = offsetBuffer; index < nextOffsetBuffer && index < buffer.length; index += 1) {
      accum += buffer[index] ?? 0
      count += 1
    }

    result[offsetResult] = count > 0 ? accum / count : 0
    offsetResult += 1
    offsetBuffer = nextOffsetBuffer
  }

  return result
}

async function startRecording() {
  errorMessage.value = ''

  if (!isSocketOpen.value) {
    errorMessage.value = 'websocket 未连接'
    return
  }

  if (isRecording.value) {
    return
  }

  try {
    if (!inputDevices.value.length) {
      await loadInputDevices()
    }

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        deviceId: selectedInputDeviceId.value ? { exact: selectedInputDeviceId.value } : undefined,
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
    })

    audioContext = new AudioContext()
    sourceNode = audioContext.createMediaStreamSource(mediaStream)
    processorNode = audioContext.createScriptProcessor(4096, 1, 1)

    processorNode.onaudioprocess = (event) => {
      if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        return
      }
      const channelData = event.inputBuffer.getChannelData(0)
      const copied = new Float32Array(channelData)
      const downsampled = downsampleBuffer(copied, audioContext?.sampleRate ?? 48000, 16000)
      websocket.send(downsampled.buffer)
    }

    sourceNode.connect(processorNode)
    processorNode.connect(audioContext.destination)
    isRecording.value = true
    pushEvent({
      type: 'recording_started',
      selected_device_id: selectedInputDeviceId.value || null,
    })
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'start recording failed'
    stopRecording()
  }
}

function stopRecording() {
  if (processorNode) {
    processorNode.disconnect()
    processorNode.onaudioprocess = null
    processorNode = null
  }
  if (sourceNode) {
    sourceNode.disconnect()
    sourceNode = null
  }
  if (mediaStream) {
    mediaStream.getTracks().forEach((track) => track.stop())
    mediaStream = null
  }
  if (audioContext) {
    void audioContext.close()
    audioContext = null
  }
  if (isRecording.value) {
    pushEvent({ type: 'recording_stopped' })
  }
  isRecording.value = false
}

onBeforeUnmount(() => {
  stopRecording()
  disconnectSocket()
})
</script>
