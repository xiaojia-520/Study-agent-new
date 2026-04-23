<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import {
  buildApiUrl,
  fetchSessionVideo,
  fetchSessionVideos,
  uploadSessionVideo,
} from '../api/studyAgent'
import { useSessionStore } from '../stores/session'
import type { SessionVideoItem, VideoSubtitleSegment } from '../types/study'

const sessionStore = useSessionStore()
const {
  backendBaseUrl,
  currentCourseId,
  currentLessonId,
  currentSessionId,
  recording,
  websocketState,
} = storeToRefs(sessionStore)

const videoRef = ref<HTMLVideoElement | null>(null)
const previewHostRef = ref<HTMLElement | null>(null)
const cameraStream = ref<MediaStream | null>(null)
const loadingCamera = ref(false)
const cameraError = ref('')
const recordingVideo = ref(false)
const uploadingVideo = ref(false)
const processingVideo = ref(false)
const loadingHistoryVideo = ref(false)
const selectedVideo = ref<SessionVideoItem | null>(null)
const videoSourceUrl = ref('')
const videoStatusMessage = ref('')

const frameStyle = ref({
  width: '0px',
  height: '0px',
})

let resizeObserver: ResizeObserver | null = null

const subtitles = computed(() => selectedVideo.value?.segments ?? [])
const cameraEnabled = computed(() => cameraStream.value !== null)
const hasPlayableVideo = computed(() => Boolean(videoSourceUrl.value) && !cameraEnabled.value)
const hasVisual = computed(() => cameraEnabled.value || Boolean(videoSourceUrl.value))

const statusLabel = computed(() => {
  if (recordingVideo.value) {
    return '视频录制中'
  }
  if (uploadingVideo.value) {
    return '视频上传中'
  }
  if (processingVideo.value) {
    return '字幕生成中'
  }
  if (subtitles.value.length > 0) {
    return '字幕已生成'
  }
  if (cameraEnabled.value) {
    return '摄像头预览'
  }
  return '等待录制'
})

function updateFrameSize(): void {
  const host = previewHostRef.value
  if (!host) return

  const hostWidth = host.clientWidth
  const hostHeight = host.clientHeight
  const targetRatio = 16 / 9

  let width = hostWidth
  let height = width / targetRatio

  if (height > hostHeight) {
    height = hostHeight
    width = height * targetRatio
  }

  frameStyle.value = {
    width: `${Math.floor(width)}px`,
    height: `${Math.floor(height)}px`,
  }
}

let mediaRecorder: MediaRecorder | null = null
let recordedChunks: BlobPart[] = []
let activeMimeType = ''
let recordingSessionId = ''
let pollTimer: number | null = null
let localVideoObjectUrl = ''

function clearPollTimer(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function revokeLocalVideoUrl(): void {
  if (localVideoObjectUrl) {
    URL.revokeObjectURL(localVideoObjectUrl)
    localVideoObjectUrl = ''
  }
}

function setLocalPlaybackSource(blob: Blob): void {
  revokeLocalVideoUrl()
  localVideoObjectUrl = URL.createObjectURL(blob)
  videoSourceUrl.value = localVideoObjectUrl
  if (videoRef.value) {
    videoRef.value.currentTime = 0
  }
}

function setRemotePlaybackSource(video: SessionVideoItem): void {
  if (!video.video_url) {
    return
  }
  revokeLocalVideoUrl()
  videoSourceUrl.value = buildApiUrl(video.video_url, backendBaseUrl.value)
}

async function attachStream(stream: MediaStream): Promise<void> {
  if (!videoRef.value) {
    return
  }
  videoRef.value.srcObject = stream
  videoRef.value.muted = true
  await videoRef.value.play()
}

function stopCameraStream(): void {
  if (videoRef.value) {
    videoRef.value.pause()
    videoRef.value.srcObject = null
  }
  if (cameraStream.value) {
    cameraStream.value.getTracks().forEach((track) => track.stop())
    cameraStream.value = null
  }
}

async function startCameraPreview(): Promise<void> {
  if (loadingCamera.value || cameraStream.value || recordingVideo.value) {
    return
  }

  loadingCamera.value = true
  cameraError.value = ''

  try {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前浏览器不支持摄像头采集。')
    }

    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: 'user',
      },
    })
    cameraStream.value = stream
    await attachStream(stream)
  } catch (error) {
    cameraError.value = error instanceof Error ? error.message : '开启摄像头失败。'
    stopCameraStream()
  } finally {
    loadingCamera.value = false
  }
}

function toggleCameraPreview(): void {
  if (recordingVideo.value) {
    return
  }
  if (cameraStream.value) {
    stopCameraStream()
    return
  }
  void startCameraPreview()
}

function selectSupportedMimeType(): string {
  if (typeof MediaRecorder === 'undefined' || !MediaRecorder.isTypeSupported) {
    return ''
  }

  const candidates = [
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm;codecs=h264,opus',
    'video/webm',
    'video/mp4',
  ]
  return candidates.find((item) => MediaRecorder.isTypeSupported(item)) ?? ''
}

function fileExtensionForMimeType(mimeType: string): string {
  if (mimeType.includes('mp4')) {
    return 'mp4'
  }
  return 'webm'
}

async function startVideoRecording(): Promise<void> {
  if (recordingVideo.value) {
    return
  }
  if (uploadingVideo.value) {
    cameraError.value = '上一段视频还在上传，暂时不能开始新的视频录制。'
    return
  }
  if (!currentSessionId.value) {
    cameraError.value = '还没有课堂 Session，不能录制视频。'
    return
  }
  if (typeof MediaRecorder === 'undefined') {
    cameraError.value = '当前浏览器不支持 MediaRecorder 视频录制。'
    return
  }

  cameraError.value = ''
  videoStatusMessage.value = ''
  clearPollTimer()
  processingVideo.value = false
  recordedChunks = []
  activeMimeType = selectSupportedMimeType()
  recordingSessionId = currentSessionId.value

  try {
    stopCameraStream()
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: {
        width: { ideal: 1280 },
        height: { ideal: 720 },
        facingMode: 'user',
      },
    })

    cameraStream.value = stream
    await attachStream(stream)

    mediaRecorder = new MediaRecorder(
      stream,
      activeMimeType ? { mimeType: activeMimeType } : undefined,
    )
    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        recordedChunks.push(event.data)
      }
    }
    mediaRecorder.onerror = () => {
      cameraError.value = '视频录制失败。'
    }
    mediaRecorder.onstop = () => {
      void handleRecorderStopped()
    }
    mediaRecorder.start(1000)
    recordingVideo.value = true
    selectedVideo.value = null
    videoStatusMessage.value = '视频正在随课堂录音同步录制。'
  } catch (error) {
    recordingVideo.value = false
    mediaRecorder = null
    stopCameraStream()
    cameraError.value = error instanceof Error ? error.message : '启动视频录制失败。'
  }
}

function stopVideoRecording(): void {
  if (!mediaRecorder) {
    recordingVideo.value = false
    stopCameraStream()
    return
  }

  if (mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
    return
  }

  void handleRecorderStopped()
}

async function handleRecorderStopped(): Promise<void> {
  const recorder = mediaRecorder
  mediaRecorder = null
  recordingVideo.value = false
  stopCameraStream()

  const blob = new Blob(recordedChunks, { type: activeMimeType || 'video/webm' })
  recordedChunks = []

  if (!blob.size) {
    cameraError.value = '视频录制结果为空。'
    return
  }

  setLocalPlaybackSource(blob)
  if (!recordingSessionId) {
    cameraError.value = '缺少课堂 Session，无法上传视频。'
    return
  }

  await uploadRecordedVideo(recordingSessionId, blob, recorder?.mimeType || activeMimeType)
}

async function uploadRecordedVideo(
  sessionId: string,
  blob: Blob,
  mimeType: string,
): Promise<void> {
  uploadingVideo.value = true
  processingVideo.value = false
  videoStatusMessage.value = '视频上传中。'
  cameraError.value = ''

  try {
    const effectiveMimeType = mimeType || blob.type || 'video/webm'
    const extension = fileExtensionForMimeType(effectiveMimeType)
    const fileName = `classroom-video-${sessionId}-${Date.now()}.${extension}`
    const file = new File([blob], fileName, { type: effectiveMimeType })
    const response = await uploadSessionVideo(sessionId, file, backendBaseUrl.value)

    selectedVideo.value = response.item
    uploadingVideo.value = false
    processingVideo.value = true
    videoStatusMessage.value = '视频已上传，正在生成字幕。'
    scheduleVideoStatusPoll(response.item.video_id)
  } catch (error) {
    uploadingVideo.value = false
    processingVideo.value = false
    cameraError.value = error instanceof Error ? error.message : '上传视频失败。'
  }
}

function scheduleVideoStatusPoll(videoId: string, startedAt = Date.now()): void {
  clearPollTimer()
  pollTimer = window.setTimeout(() => {
    void pollVideoStatus(videoId, startedAt)
  }, 2500)
}

async function pollVideoStatus(videoId: string, startedAt: number): Promise<void> {
  clearPollTimer()
  if (Date.now() - startedAt > 60 * 60 * 1000) {
    processingVideo.value = false
    cameraError.value = '字幕生成超时，请稍后刷新查看结果。'
    return
  }

  try {
    const response = await fetchSessionVideo(videoId, backendBaseUrl.value)
    selectedVideo.value = response.item

    if (response.item.status === 'done') {
      processingVideo.value = false
      videoStatusMessage.value = `字幕已生成，共 ${response.item.segment_count} 段。`
      return
    }

    if (response.item.status === 'failed') {
      processingVideo.value = false
      cameraError.value = response.item.error_message || '字幕生成失败。'
      return
    }

    processingVideo.value = true
    videoStatusMessage.value = '字幕仍在生成中。'
    scheduleVideoStatusPoll(videoId, startedAt)
  } catch (error) {
    processingVideo.value = false
    cameraError.value = error instanceof Error ? error.message : '获取字幕状态失败。'
  }
}

async function loadLatestVideoForSession(sessionId: string): Promise<void> {
  if (!sessionId || recordingVideo.value || uploadingVideo.value) {
    return
  }

  loadingHistoryVideo.value = true
  try {
    const response = await fetchSessionVideos(sessionId, backendBaseUrl.value)
    const latestVideo = response.items[0]
    if (!latestVideo) {
      selectedVideo.value = null
      videoSourceUrl.value = ''
      videoStatusMessage.value = ''
      return
    }

    selectedVideo.value = latestVideo
    setRemotePlaybackSource(latestVideo)
    processingVideo.value = latestVideo.status === 'uploaded' || latestVideo.status === 'processing'
    if (processingVideo.value) {
      videoStatusMessage.value = '检测到已有视频任务，正在等待字幕生成。'
      scheduleVideoStatusPoll(latestVideo.video_id)
    } else if (latestVideo.status === 'done') {
      videoStatusMessage.value = `已加载最近一次课堂视频，共 ${latestVideo.segment_count} 段字幕。`
    } else if (latestVideo.status === 'failed') {
      cameraError.value = latestVideo.error_message || '最近一次视频字幕生成失败。'
    }
  } catch (error) {
    cameraError.value = error instanceof Error ? error.message : '加载课堂视频失败。'
  } finally {
    loadingHistoryVideo.value = false
  }
}

function seekToSubtitle(segment: VideoSubtitleSegment): void {
  if (!videoRef.value || !videoSourceUrl.value) {
    return
  }
  videoRef.value.currentTime = Math.max(0, segment.start_ms / 1000)
  void videoRef.value.play()
}

function formatTime(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const minuteText = String(minutes).padStart(2, '0')
  const secondText = String(seconds).padStart(2, '0')
  if (hours > 0) {
    return `${hours}:${minuteText}:${secondText}`
  }
  return `${minuteText}:${secondText}`
}

watch(
  recording,
  (isRecording, wasRecording) => {
    if (isRecording) {
      void startVideoRecording()
      return
    }
    if (wasRecording) {
      stopVideoRecording()
    }
  },
  { immediate: true },
)

watch(
  currentSessionId,
  (sessionId) => {
    clearPollTimer()
    if (!sessionId) {
      selectedVideo.value = null
      processingVideo.value = false
      videoStatusMessage.value = ''
      videoSourceUrl.value = ''
      return
    }
    void loadLatestVideoForSession(sessionId)
  },
  { immediate: true },
)

onMounted(() => {
  updateFrameSize()

  if (previewHostRef.value) {
    resizeObserver = new ResizeObserver(() => {
      updateFrameSize()
    })
    resizeObserver.observe(previewHostRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  clearPollTimer()
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop()
  }
  stopCameraStream()
  revokeLocalVideoUrl()
})
</script>

<template>
  <section
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
          Video
        </p>
        <h2 class="text-xl font-semibold text-[rgb(var(--text-main))]">课堂视频窗口</h2>
      </div>

      <span
        class="rounded-full px-3 py-1 text-sm"
        :class="
          recordingVideo
            ? 'bg-[rgba(var(--danger),0.12)] text-[rgb(var(--danger))]'
            : subtitles.length > 0
              ? 'bg-[rgba(var(--success),0.14)] text-[rgb(var(--success))]'
              : 'bg-[rgba(var(--bg-muted),0.95)] text-[rgb(var(--text-subtle))]'
        "
      >
        {{ statusLabel }}
      </span>
    </div>

    <div class="mt-4 flex min-h-0 flex-1 flex-col gap-3">
      <div
        ref="previewHostRef"
        class="flex min-h-[220px] flex-1 items-center justify-center overflow-hidden"
      >
        <div
          class="relative flex-none overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.1)] bg-[#111827]"
          :style="frameStyle"
        >
          <video
            ref="videoRef"
            class="absolute inset-0 h-full w-full object-contain"
            :src="cameraEnabled ? undefined : videoSourceUrl || undefined"
            :autoplay="cameraEnabled"
            :controls="hasPlayableVideo"
            :muted="cameraEnabled"
            playsinline
          />

          <div
            v-if="!hasVisual"
            class="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center"
          >
            <div class="rounded-full border border-white/12 bg-white/8 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-white/60">
              Camera Preview
            </div>
          </div>

          <div class="pointer-events-none absolute left-3 top-3 flex items-center gap-2">
            <span
              class="h-2.5 w-2.5 rounded-full"
              :class="recordingVideo ? 'animate-pulse bg-[rgb(var(--danger))]' : 'bg-white/40'"
            />
            <span class="rounded-full bg-black/45 px-3 py-1 text-xs font-semibold text-white/82 backdrop-blur">
              {{ connectionLabel }}
            </span>
          </div>
        </div>
      </div>

      <p
        v-if="cameraError"
        class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
      >
        {{ cameraError }}
      </p>

      <p
        v-else-if="videoStatusMessage"
        class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.1)] bg-[rgba(var(--bg-muted),0.72)] px-3 py-2 text-sm text-[rgb(var(--text-subtle))]"
      >
        {{ videoStatusMessage }}
      </p>
      <div
        v-if="subtitles.length > 0"
        class="min-h-[120px] overflow-auto rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgba(var(--bg-muted),0.45)] p-2"
      >
        <button
          v-for="segment in subtitles"
          :key="`${segment.start_ms}-${segment.end_ms}-${segment.text}`"
          type="button"
          class="mb-2 flex w-full gap-3 rounded-[var(--radius-soft)] px-3 py-2 text-left transition hover:bg-[rgba(var(--accent),0.08)]"
          @click="seekToSubtitle(segment)"
        >
          <span class="shrink-0 font-mono text-xs text-[rgb(var(--text-faint))]">
            {{ formatTime(segment.start_ms) }}
          </span>
          <span class="text-sm leading-6 text-[rgb(var(--text-main))]">
            {{ segment.text }}
          </span>
        </button>
      </div>
    </div>

    <button
      type="button"
      class="mt-4 inline-flex shrink-0 items-center justify-center rounded-[var(--radius-soft)] px-4 py-3 font-semibold transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
      :class="
        cameraEnabled
          ? 'bg-[rgba(var(--line-soft),0.1)] text-[rgb(var(--text-main))]'
          : 'bg-[rgb(var(--accent))] text-[rgb(var(--text-inverse))]'
      "
      :disabled="loadingCamera || recordingVideo"
      @click="toggleCameraPreview"
    >
      {{
        recordingVideo
          ? '正在录制视频'
          : loadingCamera
            ? '开启中...'
            : cameraEnabled
              ? '关闭视频预览'
              : '开启视频预览'
      }}
    </button>
  </section>
</template>
