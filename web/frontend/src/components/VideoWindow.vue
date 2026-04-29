<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import {
  buildApiUrl,
  fetchSessionVideo,
  fetchSessionVideos,
  uploadVisionFrame,
  uploadSessionVideo,
} from '../api/studyAgent'
import { useSessionStore } from '../stores/session'
import type { SessionVideoItem, VideoSubtitleSegment, VisionRegion } from '../types/study'

type VisionRegionKey = 'ppt' | 'blackboard'

const sessionStore = useSessionStore()
const {
  backendBaseUrl,
  camera,
  currentCourseId,
  currentLessonId,
  currentSessionId,
  recording,
  websocketState,
} = storeToRefs(sessionStore)

const videoRef = ref<HTMLVideoElement | null>(null)
const previewHostRef = ref<HTMLElement | null>(null)
const frameRef = ref<HTMLElement | null>(null)
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
const activeRegionTool = ref<VisionRegionKey | null>(null)
const draftVisionRegion = ref<VisionRegion | null>(null)
const visionRegions = ref<Partial<Record<VisionRegionKey, VisionRegion>>>({})
const visionUploading = ref(false)
const visionEnabled = ref(true)
const visionFrameCount = ref(0)
const visionRecordCount = ref(0)
const visionError = ref('')
const visionStatusMessage = ref('')

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

const connectionLabel = computed(() => {
  if (recordingVideo.value) {
    return '视频录制中'
  }
  if (recording.value) {
    return '课堂录音中'
  }
  if (websocketState.value === 'open') {
    return '课堂已连接'
  }
  if (websocketState.value === 'connecting') {
    return '课堂连接中'
  }
  if (cameraEnabled.value) {
    return '摄像头预览'
  }
  return '未连接'
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
let visionCaptureTimer: number | null = null
let visionRecordingStartedAt = 0
let videoRecordingStartedAt = 0
let regionDragStart: { region: VisionRegionKey; x: number; y: number } | null = null
let switchingCamera = false

const visionRegionEntries = computed(() =>
  (Object.entries(visionRegions.value) as [VisionRegionKey, VisionRegion][])
    .filter(([, region]) => Boolean(region)),
)

const visibleVisionRegions = computed(() => {
  const items = visionRegionEntries.value.map(([region, box]) => ({ region, box, draft: false }))
  if (activeRegionTool.value && draftVisionRegion.value) {
    items.push({ region: activeRegionTool.value, box: draftVisionRegion.value, draft: true })
  }
  return items
})

const visionRegionSummary = computed(() => {
  const names = visionRegionEntries.value.map(([region]) => regionLabel(region))
  return names.length ? names.join(' / ') : '未框选'
})

function clearPollTimer(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function clearVisionCaptureTimer(): void {
  if (visionCaptureTimer !== null) {
    window.clearInterval(visionCaptureTimer)
    visionCaptureTimer = null
  }
}

function regionLabel(region: VisionRegionKey): string {
  return region === 'ppt' ? 'PPT区' : '黑板区'
}

function regionStyle(region: VisionRegion): Record<string, string> {
  return {
    left: `${region.x * 100}%`,
    top: `${region.y * 100}%`,
    width: `${region.w * 100}%`,
    height: `${region.h * 100}%`,
  }
}

function selectRegionTool(region: VisionRegionKey): void {
  activeRegionTool.value = activeRegionTool.value === region ? null : region
  draftVisionRegion.value = null
}

function clearVisionRegions(): void {
  activeRegionTool.value = null
  draftVisionRegion.value = null
  regionDragStart = null
  visionRegions.value = {}
  visionStatusMessage.value = ''
  visionError.value = ''
}

function pointerToNormalizedPoint(event: PointerEvent): { x: number; y: number } | null {
  const frame = frameRef.value
  if (!frame) {
    return null
  }

  const bounds = frame.getBoundingClientRect()
  if (bounds.width <= 0 || bounds.height <= 0) {
    return null
  }

  return {
    x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
    y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
  }
}

function buildRegionFromPoints(
  start: { x: number; y: number },
  end: { x: number; y: number },
): VisionRegion {
  const x = Math.min(start.x, end.x)
  const y = Math.min(start.y, end.y)
  return {
    x,
    y,
    w: Math.abs(end.x - start.x),
    h: Math.abs(end.y - start.y),
  }
}

function handleVisionPointerDown(event: PointerEvent): void {
  if (!activeRegionTool.value) {
    return
  }
  const point = pointerToNormalizedPoint(event)
  if (!point) {
    return
  }

  event.preventDefault()
  regionDragStart = { region: activeRegionTool.value, ...point }
  draftVisionRegion.value = { x: point.x, y: point.y, w: 0, h: 0 }
  window.addEventListener('pointermove', handleVisionPointerMove)
  window.addEventListener('pointerup', finishVisionRegionSelection)
}

function handleVisionPointerMove(event: PointerEvent): void {
  if (!regionDragStart) {
    return
  }
  const point = pointerToNormalizedPoint(event)
  if (!point) {
    return
  }
  draftVisionRegion.value = buildRegionFromPoints(regionDragStart, point)
}

function finishVisionRegionSelection(): void {
  window.removeEventListener('pointermove', handleVisionPointerMove)
  window.removeEventListener('pointerup', finishVisionRegionSelection)

  if (!regionDragStart || !draftVisionRegion.value) {
    regionDragStart = null
    draftVisionRegion.value = null
    return
  }

  const region = draftVisionRegion.value
  if (region.w >= 0.03 && region.h >= 0.03) {
    visionRegions.value = {
      ...visionRegions.value,
      [regionDragStart.region]: region,
    }
    visionStatusMessage.value = `${regionLabel(regionDragStart.region)}已框选，录制时会自动解析。`
  }

  regionDragStart = null
  draftVisionRegion.value = null
  activeRegionTool.value = null
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

function startVisionCaptureTimer(startedAtMs = Date.now()): void {
  clearVisionCaptureTimer()
  visionRecordingStartedAt = startedAtMs
  visionStatusMessage.value = visionRegionEntries.value.length
    ? `视觉识别已启动：${visionRegionSummary.value}`
    : '视觉识别等待框选区域。'
  visionCaptureTimer = window.setInterval(() => {
    void captureAndUploadVisionFrame()
  }, 8000)
  window.setTimeout(() => {
    void captureAndUploadVisionFrame()
  }, 1200)
}

async function canvasToBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.82)
  })
}

async function captureAndUploadVisionFrame(): Promise<void> {
  if (!visionEnabled.value || visionUploading.value || !recordingVideo.value) {
    return
  }
  if (!currentSessionId.value || !cameraEnabled.value || visionRegionEntries.value.length === 0) {
    return
  }

  const capturedAtMs = Date.now()
  const video = videoRef.value
  if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) {
    return
  }

  const canvas = document.createElement('canvas')
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  const context = canvas.getContext('2d')
  if (!context) {
    return
  }
  context.drawImage(video, 0, 0, canvas.width, canvas.height)
  const blob = await canvasToBlob(canvas)
  if (!blob) {
    return
  }

  visionUploading.value = true
  visionError.value = ''
  try {
    const regions = Object.fromEntries(visionRegionEntries.value) as Partial<
      Record<VisionRegionKey, VisionRegion>
    >
    const timestampMs = Math.max(0, capturedAtMs - visionRecordingStartedAt)
    const response = await uploadVisionFrame(
      currentSessionId.value,
      blob,
      regions,
      timestampMs,
      capturedAtMs,
      backendBaseUrl.value,
    )
    visionFrameCount.value += 1
    visionRecordCount.value += response.record_count

    const indexedRegions = response.results
      .filter((item) => item.status === 'indexed')
      .map((item) => regionLabel(item.region as VisionRegionKey))
    const failedRegions = response.results
      .filter((item) => item.status === 'failed')
      .map((item) => `${regionLabel(item.region as VisionRegionKey)}：${item.error_message || '失败'}`)

    if (failedRegions.length > 0) {
      visionError.value = failedRegions.join('；')
    }
    visionStatusMessage.value = indexedRegions.length
      ? `已入库 ${indexedRegions.join('、')}，累计 ${visionRecordCount.value} 条视觉记录。`
      : `已分析第 ${visionFrameCount.value} 帧，暂无新增内容。`
  } catch (error) {
    visionError.value = error instanceof Error ? error.message : '上传视觉帧失败。'
  } finally {
    visionUploading.value = false
  }
}

async function attachStream(stream: MediaStream): Promise<void> {
  if (!videoRef.value) {
    return
  }
  videoRef.value.srcObject = stream
  videoRef.value.muted = true
  await videoRef.value.play()
}

function buildVideoConstraints(): MediaTrackConstraints {
  const base: MediaTrackConstraints = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
  }
  if (camera.value && camera.value !== 'default') {
    return {
      ...base,
      deviceId: { exact: camera.value },
    }
  }
  return {
    ...base,
    facingMode: 'user',
  }
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
      video: buildVideoConstraints(),
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

watch(camera, async (nextDevice, previousDevice) => {
  if (!nextDevice || nextDevice === previousDevice || recordingVideo.value || !cameraEnabled.value) {
    return
  }
  if (switchingCamera) {
    return
  }

  switchingCamera = true
  try {
    stopCameraStream()
    await startCameraPreview()
  } finally {
    switchingCamera = false
  }
})

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
  videoRecordingStartedAt = 0

  try {
    stopCameraStream()
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: buildVideoConstraints(),
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
    videoRecordingStartedAt = Date.now()
    mediaRecorder.start(1000)
    recordingVideo.value = true
    selectedVideo.value = null
    videoStatusMessage.value = '视频正在随课堂录音同步录制。'
    startVisionCaptureTimer(videoRecordingStartedAt)
  } catch (error) {
    recordingVideo.value = false
    videoRecordingStartedAt = 0
    mediaRecorder = null
    clearVisionCaptureTimer()
    stopCameraStream()
    cameraError.value = error instanceof Error ? error.message : '启动视频录制失败。'
  }
}

function stopVideoRecording(): void {
  clearVisionCaptureTimer()
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
    const response = await uploadSessionVideo(sessionId, file, backendBaseUrl.value, {
      recordingStartedAtMs: videoRecordingStartedAt || undefined,
      recordingEndedAtMs: Date.now(),
    })

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
    visionError.value = ''
    visionStatusMessage.value = ''
    visionFrameCount.value = 0
    visionRecordCount.value = 0
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
  clearVisionCaptureTimer()
  window.removeEventListener('pointermove', handleVisionPointerMove)
  window.removeEventListener('pointerup', finishVisionRegionSelection)
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
        class="flex flex-1 items-center justify-center overflow-hidden"
      >
        <div
          ref="frameRef"
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

          <div
            class="absolute inset-0"
            :class="activeRegionTool ? 'pointer-events-auto cursor-crosshair' : 'pointer-events-none'"
            @pointerdown="handleVisionPointerDown"
          >
            <div
              v-for="item in visibleVisionRegions"
              :key="`${item.region}-${item.draft ? 'draft' : 'saved'}`"
              class="absolute rounded-sm border-2"
              :class="[
                item.region === 'ppt' ? 'border-sky-300 bg-sky-300/10' : 'border-emerald-300 bg-emerald-300/10',
                item.draft ? 'border-dashed' : 'border-solid',
              ]"
              :style="regionStyle(item.box)"
            >
              <span
                class="absolute left-1 top-1 rounded bg-black/55 px-2 py-0.5 text-[11px] font-semibold text-white"
              >
                {{ regionLabel(item.region) }}
              </span>
            </div>
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

      <div class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgba(var(--bg-muted),0.45)] p-3">
        <div class="flex flex-wrap items-center gap-2">
          <button
            type="button"
            class="rounded-[var(--radius-soft)] px-3 py-1.5 text-xs font-semibold transition"
            :class="activeRegionTool === 'ppt' ? 'bg-sky-500 text-white' : 'bg-sky-500/10 text-sky-700 hover:bg-sky-500/20'"
            @click="selectRegionTool('ppt')"
          >
            框选PPT区
          </button>
          <button
            type="button"
            class="rounded-[var(--radius-soft)] px-3 py-1.5 text-xs font-semibold transition"
            :class="activeRegionTool === 'blackboard' ? 'bg-emerald-600 text-white' : 'bg-emerald-600/10 text-emerald-700 hover:bg-emerald-600/20'"
            @click="selectRegionTool('blackboard')"
          >
            框选黑板区
          </button>
          <button
            type="button"
            class="rounded-[var(--radius-soft)] bg-[rgba(var(--line-soft),0.08)] px-3 py-1.5 text-xs font-semibold text-[rgb(var(--text-subtle))] transition hover:bg-[rgba(var(--line-soft),0.12)]"
            @click="clearVisionRegions"
          >
            清除框选
          </button>
          <label class="ml-auto flex items-center gap-2 text-xs font-semibold text-[rgb(var(--text-subtle))]">
            <input v-model="visionEnabled" type="checkbox" class="h-4 w-4 rounded border-[rgba(var(--line-soft),0.18)]" />
            视觉入库
          </label>
        </div>

        <div class="mt-2 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--text-faint))]">
          <span>区域：{{ visionRegionSummary }}</span>
          <span>/</span>
          <span>{{ visionUploading ? '视觉帧解析中' : `已分析 ${visionFrameCount} 帧` }}</span>
          <span>/</span>
          <span>入库 {{ visionRecordCount }} 条</span>
        </div>
        <p v-if="activeRegionTool" class="mt-2 text-xs text-[rgb(var(--accent))]">
          在视频画面上拖动鼠标框选{{ regionLabel(activeRegionTool) }}。
        </p>
        <p v-if="visionStatusMessage" class="mt-2 text-xs text-[rgb(var(--text-subtle))]">
          {{ visionStatusMessage }}
        </p>
        <p v-if="visionError" class="mt-2 text-xs text-[rgb(var(--danger))]">
          {{ visionError }}
        </p>
      </div>

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
