import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import {
  createSession as createSessionRequest,
  defaultBackendBaseUrl,
} from '../api/studyAgent'
import type {
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
import {
  defaultChannels,
  defaultSampleRate,
  sessionClientId,
  sessionModelOptions,
} from './session/constants'
import {
  buildCurrentLessonSnapshot,
  buildLessonConfigSignature,
  buildSessionConfigSignature,
  chooseResumeSnapshot,
  confirmContinueLesson,
  saveLessonSnapshot as persistLessonSnapshot,
} from './session/lessonSnapshots'
import { createMicrophoneActions } from './session/microphones'
import { createRealtimeAudioActions } from './session/realtimeAudio'
import { createTranscriptActions, toMilliseconds } from './session/transcripts'
import type { LessonSnapshot, LessonSnapshotStatus, RefineStatusToast } from './session/types'

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
  const promptBeforeNextStart = ref(false)

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

  let lastSessionConfigSignature = ''
  let lastLessonConfigSignature = ''

  function saveLessonSnapshot(status: LessonSnapshotStatus): void {
    persistLessonSnapshot({
      sessionInfo: sessionInfo.value,
      subject: subject.value,
      model: model.value,
      status,
    })
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

  const { hydrateTranscriptsFromServer } = createTranscriptActions({
    backendBaseUrl,
    sessionInfo,
    transcriptList,
  })

  async function createRealtimeSession(): Promise<SessionInfo> {
    const signature = buildSessionConfigSignature(subject.value, model.value)
    const lessonSignature = buildLessonConfigSignature(subject.value)

    if (sessionInfo.value && lastSessionConfigSignature === signature && !promptBeforeNextStart.value) {
      return sessionInfo.value
    }

    let lessonSnapshot: LessonSnapshot | null = null
    const currentLessonSnapshot = buildCurrentLessonSnapshot({
      sessionInfo: sessionInfo.value,
      subject: subject.value,
      model: model.value,
      recording: recording.value,
    })

    if (promptBeforeNextStart.value && currentLessonSnapshot) {
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
    lastSessionConfigSignature = buildSessionConfigSignature(subject.value, model.value)
    lastLessonConfigSignature = buildLessonConfigSignature(subject.value)
    promptBeforeNextStart.value = false
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

  const { fetchMicrophones } = createMicrophoneActions({
    microphone,
    microphones,
    loadingMicrophones,
    errorMessage,
  })

  const {
    refreshSessionAssets,
    uploadLessonAsset,
  } = createLessonAssetActions({
    backendBaseUrl,
    sessionInfo,
    assetList,
    assetUploading,
    assetErrorMessage,
    ensureSession,
    hydrateTranscriptsFromServer,
  })

  const {
    cleanup,
    startRecording,
    stopRecording,
    toggleRecording,
  } = createRealtimeAudioActions({
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
  })

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
