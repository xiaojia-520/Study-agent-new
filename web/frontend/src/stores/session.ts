import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createSession as createSessionRequest,
  defaultBackendBaseUrl,
} from '../api/studyAgent'
import type {
  CameraOption,
  LessonAssetItem,
  MicrophoneOption,
  ModelKey,
  ModelOption,
  RealtimeEvent,
  SessionInfo,
  TranscriptEntry,
  WebSocketState,
} from '../types/study'
import { createLessonAssetActions } from './session/assets'
import { createCameraActions } from './session/cameras'
import {
  defaultChannels,
  defaultSampleRate,
  sessionClientId,
  sessionModelOptions,
} from './session/constants'
import { createMicrophoneActions } from './session/microphones'
import {
  confirmRecordingResumeSnapshot,
  saveRecordingResumeSnapshot,
} from './session/recordingResumeSnapshots'
import { createRealtimeAudioActions } from './session/realtimeAudio'
import { createTranscriptActions, toMilliseconds } from './session/transcripts'
import type {
  RecordingResumeSnapshotStatus,
  RefineStatusToast,
} from './session/types'

function buildSessionConfigSignature(subject: string, model: ModelKey): string {
  return JSON.stringify({
    subject: subject.trim(),
    model,
    sampleRate: defaultSampleRate,
    channels: defaultChannels,
  })
}

export const useSessionStore = defineStore('session', () => {
  const backendBaseUrl = ref(defaultBackendBaseUrl)
  const subject = ref('Web 开发课堂')
  const model = ref<ModelKey>('paraformer-zh-streaming')
  const modelOptions = ref<ModelOption[]>([...sessionModelOptions])
  const microphone = ref('default')
  const microphones = ref<MicrophoneOption[]>([{ id: 'default', label: '默认麦克风' }])
  const camera = ref('default')
  const cameras = ref<CameraOption[]>([{ id: 'default', label: '默认摄像头' }])
  const recording = ref(false)
  const initializing = ref(false)
  const switchingMicrophone = ref(false)
  const loadingMicrophones = ref(false)
  const loadingCameras = ref(false)
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
  const sessionNeedsFreshStart = ref(false)

  const transcriptCount = computed(() => transcriptList.value.length)
  const assetCount = computed(() => assetList.value.length)
  const currentSessionId = computed(() => sessionInfo.value?.session_id || '')
  const currentCourseId = computed(() => sessionInfo.value?.course_id || '')
  const currentLessonId = computed(() => sessionInfo.value?.lesson_id || '')
  const recordButtonBusy = computed(
    () => initializing.value || websocketState.value === 'connecting',
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

  let lastSessionConfigSignature = ''

  function resetSessionPanels(): void {
    transcriptList.value = []
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

  const { hydrateTranscriptsFromServer } = createTranscriptActions({
    backendBaseUrl,
    sessionInfo,
    transcriptList,
  })

  function saveRecordingSnapshot(status: RecordingResumeSnapshotStatus): void {
    saveRecordingResumeSnapshot({
      sessionInfo: sessionInfo.value,
      subject: subject.value,
      status,
    })
  }

  async function createRealtimeSession(): Promise<SessionInfo> {
    const signature = buildSessionConfigSignature(subject.value, model.value)

    if (sessionInfo.value && lastSessionConfigSignature === signature && !sessionNeedsFreshStart.value) {
      return sessionInfo.value
    }

    const resumeSnapshot = confirmRecordingResumeSnapshot(subject.value)
    if (!resumeSnapshot) {
      resetSessionPanels()
    }

    const response = await createSessionRequest(
      {
        course_id: resumeSnapshot?.course_id,
        lesson_id: resumeSnapshot?.lesson_id,
        subject: subject.value.trim() || undefined,
        client_id: sessionClientId,
        sample_rate: defaultSampleRate,
        channels: defaultChannels,
        model_name: model.value,
      },
      backendBaseUrl.value,
    )

    sessionInfo.value = response
    lastSessionConfigSignature = buildSessionConfigSignature(subject.value, model.value)
    sessionNeedsFreshStart.value = false
    saveRecordingSnapshot('active')
    if (resumeSnapshot) {
      await hydrateTranscriptsFromServer()
    }
    await refreshLessonAssets()
    return response
  }

  async function ensureSession(): Promise<SessionInfo> {
    if (recording.value) {
      throw new Error('录音过程中不能重建会话。')
    }

    return createRealtimeSession()
  }

  const { fetchMicrophones } = createMicrophoneActions({
    microphone,
    microphones,
    loadingMicrophones,
    errorMessage,
  })

  const { fetchCameras } = createCameraActions({
    camera,
    cameras,
    loadingCameras,
    errorMessage,
  })

  const {
    refreshLessonAssets,
    uploadLessonAsset,
  } = createLessonAssetActions({
    backendBaseUrl,
    subject,
    recording,
    assetList,
    assetUploading,
    assetErrorMessage,
  })

  const {
    cleanup,
    startRecording,
    stopRecording,
    switchMicrophone,
    toggleRecording,
  } = createRealtimeAudioActions({
    backendBaseUrl,
    sessionInfo,
    microphone,
    switchingMicrophone,
    recording,
    initializing,
    websocketState,
    errorMessage,
    audioFrameCount,
    sessionNeedsFreshStart,
    ensureSession,
    handleRealtimeEvent,
    hydrateTranscriptsFromServer,
    saveRecordingSnapshot,
    showRefineStatusToast,
  })

  async function selectMicrophone(nextMicrophoneId: string): Promise<void> {
    await switchMicrophone(nextMicrophoneId)
  }

  if (typeof window !== 'undefined') {
    window.addEventListener('beforeunload', () => {
      saveRecordingSnapshot(recording.value ? 'interrupted' : 'stopped')
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
    camera,
    cameras,
    cleanup,
    currentCourseId,
    currentLessonId,
    currentSessionId,
    dismissRefineStatusToast,
    errorMessage,
    ensureSession,
    fetchCameras,
    fetchMicrophones,
    refreshLessonAssets,
    initializing,
    loadingCameras,
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
    selectMicrophone,
    startRecording,
    stopRecording,
    switchingMicrophone,
    subject,
    toggleRecording,
    transcriptCount,
    transcriptList,
    uploadLessonAsset,
    websocketState,
  }
})
