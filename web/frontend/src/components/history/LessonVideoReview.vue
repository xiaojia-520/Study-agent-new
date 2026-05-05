<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onBeforeUpdate, ref, watch } from 'vue'
import type { ComponentPublicInstance } from 'vue'
import { storeToRefs } from 'pinia'

import { buildApiUrl, fetchLessonVideos, fetchSessionVideo } from '../../api/studyAgent'
import { useSessionStore } from '../../stores/session'
import type { SessionVideoItem, VideoSubtitleSegment } from '../../types/study'

const props = defineProps<{
  courseId?: string | null
  lessonId?: string | null
}>()

const sessionStore = useSessionStore()
const { backendBaseUrl } = storeToRefs(sessionStore)

const videoRef = ref<HTMLVideoElement | null>(null)
const videos = ref<SessionVideoItem[]>([])
const selectedVideoId = ref('')
const loading = ref(false)
const errorMessage = ref('')
const statusMessage = ref('')
const subtitleTrackUrl = ref('')
const subtitleListRef = ref<HTMLElement | null>(null)
const subtitleItemRefs = ref<HTMLElement[]>([])
const activeSubtitleIndex = ref(-1)
const subtitleAutoScrollEnabled = ref(false)
const firstPlaybackPending = ref(true)
const userRequestedSeek = ref(false)

const selectedVideo = computed(
  () => videos.value.find((item) => item.video_id === selectedVideoId.value) ?? videos.value[0] ?? null,
)

const subtitles = computed(() => selectedVideo.value?.segments ?? [])
const canExportSubtitles = computed(() => subtitles.value.length > 0)

const needsRefinedSubtitleRefresh = (item: SessionVideoItem): boolean =>
  item.status === 'done' && !item.metadata?.subtitle_refined_at

const videoSourceUrl = computed(() => {
  const video = selectedVideo.value
  return video?.video_url ? buildApiUrl(video.video_url, backendBaseUrl.value) : ''
})

const hasPendingVideo = computed(() =>
  videos.value.some(
    (item) => item.status === 'uploaded' || item.status === 'processing' || needsRefinedSubtitleRefresh(item),
  ),
)

let pollTimer: number | null = null

function clearPollTimer(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function schedulePoll(): void {
  clearPollTimer()

  if (!hasPendingVideo.value) {
    return
  }

  pollTimer = window.setTimeout(() => {
    void refreshPendingVideos()
  }, 3000)
}

async function loadLessonVideos(): Promise<void> {
  clearPollTimer()

  videos.value = []
  selectedVideoId.value = ''
  statusMessage.value = ''
  errorMessage.value = ''

  if (!props.courseId || !props.lessonId) {
    return
  }

  resetPlaybackState(false)
  loading.value = true

  try {
    const response = await fetchLessonVideos(props.courseId, props.lessonId, backendBaseUrl.value)

    videos.value = response.items
    selectedVideoId.value = response.items[0]?.video_id ?? ''

    resetPlaybackState(false)
    updateStatusMessage()
    schedulePoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '加载课堂视频失败。'
  } finally {
    loading.value = false
  }
}

async function refreshPendingVideos(): Promise<void> {
  const pending = videos.value.filter((item) => item.status === 'uploaded' || item.status === 'processing')
  const refining = videos.value.filter(needsRefinedSubtitleRefresh)

  const refreshTargets = [...pending, ...refining]
  const uniqueTargets = Array.from(new Map(refreshTargets.map((item) => [item.video_id, item])).values())

  if (uniqueTargets.length === 0) {
    clearPollTimer()
    return
  }

  try {
    const updates = await Promise.all(
      uniqueTargets.map((item) => fetchSessionVideo(item.video_id, backendBaseUrl.value)),
    )

    const byId = new Map(updates.map((item) => [item.item.video_id, item.item]))

    videos.value = videos.value.map((item) => byId.get(item.video_id) ?? item)

    updateStatusMessage()
    schedulePoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新字幕状态失败。'
    clearPollTimer()
  }
}

function updateStatusMessage(): void {
  const video = selectedVideo.value

  if (!video) {
    statusMessage.value = ''
    return
  }

  if (video.status === 'done') {
    statusMessage.value = needsRefinedSubtitleRefresh(video)
      ? `字幕已生成，正在精修中，共 ${video.segment_count} 段。`
      : `字幕已生成，共 ${video.segment_count} 段。`
    return
  }

  if (video.status === 'failed') {
    statusMessage.value = video.error_message || '字幕生成失败。'
    return
  }

  statusMessage.value = '视频已录制，字幕还在后台生成。'
}

function selectVideo(video: SessionVideoItem): void {
  selectedVideoId.value = video.video_id
  resetPlaybackState(true)
  updateStatusMessage()
}

function exportSubtitles(format: 'srt' | 'txt'): void {
  if (!canExportSubtitles.value) {
    return
  }

  const fileName = `${buildSubtitleExportBaseName()}.${format}`
  const content = format === 'srt' ? buildSrt(subtitles.value) : buildTxt(subtitles.value)

  if (!content.trim()) {
    return
  }

  downloadTextFile(fileName, content, format === 'srt' ? 'application/x-subrip' : 'text/plain')
}

function seekToSubtitle(segment: VideoSubtitleSegment): void {
  const video = videoRef.value

  if (!video || !videoSourceUrl.value) {
    return
  }

  const index = subtitles.value.indexOf(segment)
  const targetSeconds = Math.max(0, segment.start_ms / 1000)

  firstPlaybackPending.value = false
  userRequestedSeek.value = true
  subtitleAutoScrollEnabled.value = true
  activeSubtitleIndex.value = index

  setVideoCurrentTime(targetSeconds)

  void video.play()

  void nextTick(() => {
    if (index >= 0) {
      scrollActiveSubtitleIntoView(index, 'smooth')
    }
  })
}

function setVideoCurrentTime(seconds: number): void {
  const video = videoRef.value

  if (!video) {
    return
  }

  try {
    video.currentTime = Math.max(0, seconds)
  } catch {
    // 某些浏览器在 metadata 未加载完成前可能拒绝修改 currentTime。
  }
}

function handleVideoLoadedMetadata(): void {
  resetPlaybackState(true)
}

function handleVideoPlaybackStart(): void {
  subtitleAutoScrollEnabled.value = false

  if (firstPlaybackPending.value && !userRequestedSeek.value) {
    firstPlaybackPending.value = false
    activeSubtitleIndex.value = -1

    void nextTick(() => {
      subtitleListRef.value?.scrollTo({ top: 0, behavior: 'auto' })
    })

    window.setTimeout(() => {
      subtitleAutoScrollEnabled.value = true
      syncActiveSubtitleFromVideoTime()
    }, 300)

    return
  }

  subtitleAutoScrollEnabled.value = true
  firstPlaybackPending.value = false
  syncActiveSubtitleFromVideoTime()
}

function handleVideoPlaying(): void {
  subtitleAutoScrollEnabled.value = true

  if (firstPlaybackPending.value && !userRequestedSeek.value) {
    firstPlaybackPending.value = false
    activeSubtitleIndex.value = -1
    return
  }

  firstPlaybackPending.value = false
  syncActiveSubtitleFromVideoTime()
}

function handleVideoSeeking(): void {
  userRequestedSeek.value = true
}

function handleVideoSeeked(): void {
  syncActiveSubtitleFromVideoTime()
  scrollCurrentSubtitleIntoView()
}

function handleVideoPlaybackStop(): void {
  syncActiveSubtitleFromVideoTime()
  subtitleAutoScrollEnabled.value = false
}

function resetPlaybackState(resetVideoElement: boolean): void {
  subtitleAutoScrollEnabled.value = false
  firstPlaybackPending.value = true
  userRequestedSeek.value = false
  activeSubtitleIndex.value = -1

  if (resetVideoElement && videoRef.value) {
    setVideoCurrentTime(0)
  }

  void nextTick(() => {
    subtitleListRef.value?.scrollTo({ top: 0, behavior: 'auto' })

    window.requestAnimationFrame(() => {
      subtitleListRef.value?.scrollTo({ top: 0, behavior: 'auto' })
    })
  })
}

function syncActiveSubtitleFromVideoTime(): void {
  const index = findActiveSubtitleIndexByCurrentTime()
  activeSubtitleIndex.value = index
}

function findActiveSubtitleIndexByCurrentTime(): number {
  const video = videoRef.value

  if (!video) {
    return -1
  }

  const currentMs = video.currentTime * 1000
  const items = subtitles.value

  if (items.length === 0) {
    return -1
  }

  const firstItem = items[0]

  if (!firstItem || currentMs < firstItem.start_ms) {
    return -1
  }

  for (let index = 0; index < items.length; index += 1) {
    const current = items[index]
    const next = items[index + 1]

    if (!current) {
      continue
    }

    const currentStartMs = Math.max(0, current.start_ms)
    const nextStartMs = next ? Math.max(0, next.start_ms) : Number.POSITIVE_INFINITY

    if (currentMs >= currentStartMs && currentMs < nextStartMs) {
      return index
    }
  }

  return items.length - 1
}

function setSubtitleItemRef(el: Element | ComponentPublicInstance | null, index: number): void {
  if (el instanceof HTMLElement) {
    subtitleItemRefs.value[index] = el
  }
}

function scrollActiveSubtitleIntoView(index: number, behavior: ScrollBehavior = 'smooth'): void {
  const container = subtitleListRef.value
  const item = subtitleItemRefs.value[index]

  if (!container || !item) {
    return
  }

  const containerRect = container.getBoundingClientRect()
  const itemRect = item.getBoundingClientRect()

  const itemTopInContainer = itemRect.top - containerRect.top + container.scrollTop
  const itemCenterInContainer = itemTopInContainer + itemRect.height / 2

  const targetTop = itemCenterInContainer - container.clientHeight / 2

  container.scrollTo({
    top: Math.max(0, targetTop),
    behavior,
  })
}

function scrollCurrentSubtitleIntoView(behavior: ScrollBehavior = 'smooth'): void {
  const index = activeSubtitleIndex.value

  if (index < 0) {
    return
  }

  void nextTick(() => {
    scrollActiveSubtitleIntoView(index, behavior)
  })
}
function rebuildSubtitleTrack(): void {
  revokeSubtitleTrackUrl()

  if (subtitles.value.length === 0) {
    return
  }

  const content = buildWebVtt(subtitles.value)

  if (!content.trim()) {
    return
  }

  const blob = new Blob([content], { type: 'text/vtt;charset=utf-8' })
  subtitleTrackUrl.value = URL.createObjectURL(blob)
}

function revokeSubtitleTrackUrl(): void {
  if (subtitleTrackUrl.value) {
    URL.revokeObjectURL(subtitleTrackUrl.value)
    subtitleTrackUrl.value = ''
  }
}

function buildWebVtt(items: VideoSubtitleSegment[]): string {
  const lines = ['WEBVTT', '']

  for (const [index, segment] of items.entries()) {
    const text = normalizeCueText(segment.text)

    if (!text) {
      continue
    }

    const startMs = Math.max(0, segment.start_ms)
    const endMs = Math.max(startMs + 200, segment.end_ms)

    lines.push(`subtitle-${index}`)
    lines.push(`${formatVttTime(startMs)} --> ${formatVttTime(endMs)}`)
    lines.push(text)
    lines.push('')
  }

  return lines.join('\n')
}

function buildSrt(items: VideoSubtitleSegment[]): string {
  const lines: string[] = []
  let sequence = 1

  for (const segment of items) {
    const text = normalizeCueText(segment.text)

    if (!text) {
      continue
    }

    const startMs = Math.max(0, segment.start_ms)
    const endMs = Math.max(startMs + 200, segment.end_ms)

    lines.push(String(sequence))
    lines.push(`${formatSrtTime(startMs)} --> ${formatSrtTime(endMs)}`)
    lines.push(text)
    lines.push('')
    sequence += 1
  }

  return lines.join('\n')
}

function buildTxt(items: VideoSubtitleSegment[]): string {
  const lines: string[] = []

  for (const segment of items) {
    const text = normalizeCueText(segment.text)

    if (!text) {
      continue
    }

    const timeLabel = formatTime(segment.start_ms)
    const normalizedText = text.replace(/\n+/g, ' ')
    lines.push(`[${timeLabel}] ${normalizedText}`)
  }

  return lines.join('\n')
}

function buildSubtitleExportBaseName(): string {
  const lessonPart = sanitizeFileName(props.lessonId || props.courseId || 'lesson')
  const videoName = selectedVideo.value?.file_name || selectedVideo.value?.video_id || 'subtitles'
  const videoPart = sanitizeFileName(videoName.replace(/\.[^./\\]+$/, ''))
  return `${lessonPart}_${videoPart}`
}

function normalizeCueText(text: string): string {
  return String(text || '')
    .replace(/\r\n?/g, '\n')
    .replace(/-->/g, '->')
    .trim()
}

function formatVttTime(ms: number): string {
  const safeMs = Math.max(0, Math.floor(ms))
  const hours = Math.floor(safeMs / 3_600_000)
  const minutes = Math.floor((safeMs % 3_600_000) / 60_000)
  const seconds = Math.floor((safeMs % 60_000) / 1000)
  const milliseconds = safeMs % 1000

  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(milliseconds).padStart(3, '0')}`
}

function formatSrtTime(ms: number): string {
  return formatVttTime(ms).replace('.', ',')
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

function formatVideoTime(timestamp?: number): string {
  if (!timestamp) {
    return '-'
  }

  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function sanitizeFileName(value: string): string {
  return String(value || '')
    .trim()
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, '-')
    .replace(/\s+/g, '_')
    .replace(/-+/g, '-')
    .replace(/_+/g, '_')
    .replace(/^[-_.]+|[-_.]+$/g, '')
    .slice(0, 120) || 'subtitles'
}

function downloadTextFile(fileName: string, content: string, mimeType: string): void {
  const blob = new Blob(['\uFEFF', content], { type: `${mimeType};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = fileName
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  window.setTimeout(() => {
    URL.revokeObjectURL(url)
  }, 0)
}

watch(
  () => [props.courseId, props.lessonId],
  () => {
    void loadLessonVideos()
  },
  { immediate: true },
)

watch(
  subtitles,
  () => {
    rebuildSubtitleTrack()
  },
  { immediate: true },
)

watch(activeSubtitleIndex, (index, oldIndex) => {
  if (index < 0 || index === oldIndex || !subtitleAutoScrollEnabled.value) {
    return
  }

  void nextTick(() => {
    scrollActiveSubtitleIntoView(index, 'smooth')
  })
})

onBeforeUpdate(() => {
  subtitleItemRefs.value = []
})

onBeforeUnmount(() => {
  clearPollTimer()
  revokeSubtitleTrackUrl()
})
</script>

<template>
  <article class="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))]">
    <div class="flex shrink-0 items-center justify-between gap-4 border-b border-[rgba(var(--line-soft),0.08)] px-4 py-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.16em] text-[rgb(var(--text-faint))]">
          Video Review
        </p>
        <h3 class="text-base font-semibold text-[rgb(var(--text-main))]">课堂视频复习</h3>
      </div>

      <button
        type="button"
        class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="loading || !courseId || !lessonId"
        @click="loadLessonVideos"
      >
        {{ loading ? '刷新中' : '刷新视频' }}
      </button>
    </div>

    <div class="grid min-h-0 flex-1 gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
      <section class="flex min-h-0 flex-col overflow-hidden">
        <div class="relative min-h-0 flex-1 overflow-hidden rounded-[var(--radius-soft)] bg-[#111827]">
          <video
            v-if="videoSourceUrl"
            :key="selectedVideoId"
            ref="videoRef"
            class="h-full w-full object-contain"
            :src="videoSourceUrl"
            controls
            crossorigin="anonymous"
            playsinline
            @loadedmetadata="handleVideoLoadedMetadata"
            @seeking="handleVideoSeeking"
            @seeked="handleVideoSeeked"
            @play="handleVideoPlaybackStart"
            @playing="handleVideoPlaying"
            @pause="handleVideoPlaybackStop"
            @ended="handleVideoPlaybackStop"
            @timeupdate="syncActiveSubtitleFromVideoTime"
          >
            <track
              v-if="subtitleTrackUrl"
              :key="subtitleTrackUrl"
              :src="subtitleTrackUrl"
              kind="subtitles"
              srclang="zh-CN"
              label="课堂字幕"
              default
            />
          </video>

          <div
            v-else
            class="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center"
          >
            <div class="rounded-full border border-white/12 bg-white/8 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-white/60">
              Review Player
            </div>
            <p class="max-w-[28rem] text-sm leading-6 text-white/72">
              这节课还没有可回放的视频。录制并完成上传后，这里会显示视频和字幕。
            </p>
          </div>
        </div>

        <div
          v-if="videos.length > 1"
          class="flex gap-2 overflow-x-auto pb-1"
        >
          <button
            v-for="video in videos"
            :key="video.video_id"
            type="button"
            class="shrink-0 rounded-full px-3 py-1.5 text-xs font-semibold transition"
            :class="
              selectedVideoId === video.video_id
                ? 'bg-[rgb(var(--accent))] text-[rgb(var(--text-inverse))]'
                : 'bg-[rgba(var(--bg-muted),0.95)] text-[rgb(var(--text-subtle))] hover:brightness-95'
            "
            @click="selectVideo(video)"
          >
            {{ formatVideoTime(video.created_at) }} / {{ video.status }}
          </button>
        </div>
      </section>

      <section class="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))]">
        <div class="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[rgba(var(--line-soft),0.08)] px-3 py-2">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
              Subtitles
            </p>
            <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">点击字幕跳转</h4>
          </div>

          <div class="flex flex-wrap items-center justify-end gap-1.5">
            <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-2.5 py-1 text-xs font-semibold text-[rgb(var(--text-subtle))]">
              {{ subtitles.length }} 段
            </span>
            <button
              type="button"
              class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-xs font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="!canExportSubtitles"
              @click="exportSubtitles('srt')"
            >
              导出 SRT
            </button>
            <button
              type="button"
              class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-xs font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="!canExportSubtitles"
              @click="exportSubtitles('txt')"
            >
              导出 TXT
            </button>
          </div>
        </div>

        <div ref="subtitleListRef" class="relative min-h-0 flex-1 overflow-y-auto p-2">
          <div
            v-if="loading"
            class="space-y-2"
          >
            <div
              v-for="index in 6"
              :key="index"
              class="h-14 animate-pulse rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.9)]"
            />
          </div>

          <p
            v-else-if="errorMessage"
            class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
          >
            {{ errorMessage }}
          </p>

          <div
            v-else-if="subtitles.length === 0"
            class="flex h-full min-h-[180px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-5 text-center text-sm leading-6 text-[rgb(var(--text-faint))]"
          >
            {{ selectedVideo?.status === 'failed' ? '字幕生成失败，请稍后重试。' : '暂无字幕。' }}
          </div>

          <button
            v-for="(segment, index) in subtitles"
            v-else
            :key="`${segment.start_ms}-${segment.end_ms}-${segment.text}`"
            :ref="(el) => setSubtitleItemRef(el, index)"
            type="button"
            class="mb-2 flex w-full gap-3 rounded-[var(--radius-soft)] px-3 py-2 text-left transition-all duration-300 hover:bg-[rgba(var(--accent),0.08)]"
            :class="
              activeSubtitleIndex === index
                ? 'scale-[1.01] bg-[rgba(var(--accent),0.18)] shadow-sm ring-2 ring-[rgba(var(--accent),0.35)]'
                : 'bg-transparent'
            "
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

        <div
          v-if="statusMessage"
          class="shrink-0 border-t border-[rgba(var(--line-soft),0.08)] px-3 py-2 text-xs text-[rgb(var(--text-faint))]"
        >
          {{ statusMessage }}
        </div>
      </section>
    </div>
  </article>
</template>
