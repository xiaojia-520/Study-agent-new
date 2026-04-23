<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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

const selectedVideo = computed(
  () => videos.value.find((item) => item.video_id === selectedVideoId.value) ?? videos.value[0] ?? null,
)
const subtitles = computed(() => selectedVideo.value?.segments ?? [])
const videoSourceUrl = computed(() => {
  const video = selectedVideo.value
  return video?.video_url ? buildApiUrl(video.video_url, backendBaseUrl.value) : ''
})
const hasPendingVideo = computed(() =>
  videos.value.some((item) => item.status === 'uploaded' || item.status === 'processing'),
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

  loading.value = true
  try {
    const response = await fetchLessonVideos(props.courseId, props.lessonId, backendBaseUrl.value)
    videos.value = response.items
    selectedVideoId.value = response.items[0]?.video_id ?? ''
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
  if (pending.length === 0) {
    clearPollTimer()
    return
  }

  try {
    const updates = await Promise.all(
      pending.map((item) => fetchSessionVideo(item.video_id, backendBaseUrl.value)),
    )
    const byId = new Map(updates.map((item) => [item.item.video_id, item.item]))
    videos.value = videos.value.map((item) => byId.get(item.video_id) ?? item)
    updateStatusMessage()
    schedulePoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新视频字幕状态失败。'
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
    statusMessage.value = `字幕已生成，共 ${video.segment_count} 段。`
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
  updateStatusMessage()
  if (videoRef.value) {
    videoRef.value.currentTime = 0
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

watch(
  () => [props.courseId, props.lessonId],
  () => {
    void loadLessonVideos()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  clearPollTimer()
})
</script>

<template>
  <article class="flex min-h-[360px] flex-col overflow-hidden rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))]">
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

    <div class="grid min-h-0 flex-1 gap-3 p-4 lg:grid-cols-[minmax(0,1.15fr)_minmax(320px,0.85fr)]">
      <section class="flex min-h-0 flex-col gap-3">
        <div class="relative min-h-[260px] overflow-hidden rounded-[var(--radius-soft)] bg-[#111827]">
          <video
            v-if="videoSourceUrl"
            ref="videoRef"
            class="h-full w-full object-contain"
            :src="videoSourceUrl"
            controls
            playsinline
          />

          <div
            v-else
            class="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center"
          >
            <div class="rounded-full border border-white/12 bg-white/8 px-4 py-2 text-xs font-semibold uppercase tracking-[0.24em] text-white/60">
              Review Player
            </div>
            <p class="max-w-[28rem] text-sm leading-6 text-white/72">
              这节课还没有可回放的视频。录制课堂并完成上传后，这里会显示视频和字幕。
            </p>
          </div>
        </div>

        <p
          v-if="errorMessage"
          class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
        >
          {{ errorMessage }}
        </p>

        <p
          v-else-if="statusMessage"
          class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.1)] bg-[rgba(var(--bg-muted),0.72)] px-3 py-2 text-sm text-[rgb(var(--text-subtle))]"
        >
          {{ statusMessage }}
        </p>

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
        <div class="flex shrink-0 items-center justify-between border-b border-[rgba(var(--line-soft),0.08)] px-3 py-2">
          <div>
            <p class="text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
              Subtitles
            </p>
            <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">点击字幕跳转</h4>
          </div>
          <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-2.5 py-1 text-xs font-semibold text-[rgb(var(--text-subtle))]">
            {{ subtitles.length }} 段
          </span>
        </div>

        <div class="min-h-0 flex-1 overflow-y-auto p-2">
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

          <div
            v-else-if="subtitles.length === 0"
            class="flex h-full min-h-[180px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-5 text-center text-sm leading-6 text-[rgb(var(--text-faint))]"
          >
            {{ selectedVideo?.status === 'failed' ? '字幕生成失败，请回课堂页重新录制或后续做重试。' : '暂无字幕。视频处理完成后会出现在这里。' }}
          </div>

          <button
            v-for="segment in subtitles"
            v-else
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
      </section>
    </div>
  </article>
</template>
