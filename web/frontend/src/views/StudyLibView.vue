<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'

import {
  fetchLatestLessonNote,
  fetchLessonNote,
  generateLessonNote,
  runLessonCopilotStream,
} from '../api/studyAgent'
import SideBar from '../components/history/SideBar.vue'
import { useSessionStore } from '../stores/session'
import type {
  LessonCopilotStepItem,
  LessonCopilotTimelineItem,
  LessonHistoryItem,
  LessonNoteItem,
} from '../types/study'

const sessionStore = useSessionStore()
const { backendBaseUrl } = storeToRefs(sessionStore)

const selectedLesson = ref<LessonHistoryItem | null>(null)
const note = ref<LessonNoteItem | null>(null)
const loadingLatest = ref(false)
const generating = ref(false)
const focusText = ref('')
const statusMessage = ref('')
const errorMessage = ref('')
const copilotMessage = ref('帮我复习这节课，先看有没有已有笔记，没有就生成，再告诉我这节课最值得复习的重点。')
const copilotSubmittedMessage = ref('')
const copilotAnswer = ref('')
const copilotError = ref('')
const copilotLoading = ref(false)
const copilotRevealing = ref(false)
const copilotSteps = ref<LessonCopilotStepItem[]>([])
const copilotTimelineScrollRef = ref<HTMLElement | null>(null)

let pollTimer: number | null = null
let copilotRevealTimer: number | null = null

const copilotStorageVersion = 1
const copilotStepRevealDelayMs = 420

interface SavedCopilotState {
  version: number
  message: string
  submittedMessage: string
  answer: string
  error: string
  steps: LessonCopilotStepItem[]
  savedAt: number
}

const notePayload = computed(() => note.value?.note ?? {})
const keyPoints = computed(() => notePayload.value.key_points ?? [])
const concepts = computed(() => notePayload.value.concepts ?? [])
const examples = computed(() => notePayload.value.examples ?? [])
const timeline = computed(() => notePayload.value.timeline ?? [])
const reviewItems = computed(() => notePayload.value.review_items ?? [])
const questions = computed(() => notePayload.value.questions ?? [])
const selectedCourseId = computed(() => selectedLesson.value?.course_id || '')
const selectedLessonId = computed(() => selectedLesson.value?.lesson_id || '')
const canGenerate = computed(() => Boolean(selectedCourseId.value && selectedLessonId.value) && !generating.value)
const canRunCopilot = computed(
  () =>
    Boolean(selectedCourseId.value && selectedLessonId.value && copilotMessage.value.trim()) &&
    !copilotLoading.value &&
    !copilotRevealing.value,
)
const canExportMarkdown = computed(() => Boolean(note.value?.markdown?.trim()) && note.value?.status === 'done')
const copilotTimeline = computed<LessonCopilotTimelineItem[]>(() => {
  const items: LessonCopilotTimelineItem[] = []
  const submitted = copilotSubmittedMessage.value.trim()
  if (submitted) {
    items.push({
      kind: 'user',
      key: `user-${submitted}`,
      text: submitted,
    })
  }

  copilotSteps.value.forEach((step, index) => {
    const thought = step.thought?.trim()
    if (thought) {
      items.push({
        kind: 'thought',
        key: `thought-${index}`,
        text: thought,
        step,
      })
    }

    if (step.action === 'tool') {
      items.push({
        kind: 'tool',
        key: `tool-${index}-${step.tool_name || 'unknown'}`,
        step,
      })
      return
    }

    if (step.action === 'final') {
      const answer = step.final_answer?.trim() || copilotAnswer.value.trim()
      if (answer) {
        items.push({
          kind: 'final',
          key: `final-${index}`,
          text: answer,
          step,
        })
      }
      return
    }

    if (step.error?.trim()) {
      items.push({
        kind: 'error',
        key: `error-${index}`,
        text: step.error.trim(),
        step,
      })
    }
  })

  if (!copilotRevealing.value && !copilotSteps.value.length && copilotAnswer.value.trim()) {
    items.push({
      kind: 'final',
      key: 'final-answer-only',
      text: copilotAnswer.value.trim(),
    })
  }

  return items
})
const noteStatusLabel = computed(() => {
  if (!note.value) {
    return '暂无笔记'
  }
  if (note.value.status === 'done') {
    return '已生成'
  }
  if (note.value.status === 'failed') {
    return '生成失败'
  }
  if (note.value.status === 'generating') {
    return '生成中'
  }
  return note.value.status
})

function clearPollTimer(): void {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

function clearCopilotRevealTimer(): void {
  if (copilotRevealTimer !== null) {
    window.clearTimeout(copilotRevealTimer)
    copilotRevealTimer = null
  }
}

function buildCopilotStorageKey(courseId = selectedCourseId.value, lessonId = selectedLessonId.value): string | null {
  if (!courseId || !lessonId) {
    return null
  }
  return `study-agent:lesson-copilot:${courseId}:${lessonId}`
}

function loadSavedCopilotState(courseId: string, lessonId: string): boolean {
  if (typeof window === 'undefined') {
    return false
  }

  const key = buildCopilotStorageKey(courseId, lessonId)
  if (!key) {
    return false
  }

  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) {
      return false
    }

    const payload = JSON.parse(raw) as Partial<SavedCopilotState>
    if (payload.version !== copilotStorageVersion) {
      return false
    }

    copilotMessage.value = typeof payload.message === 'string' ? payload.message : copilotMessage.value
    copilotSubmittedMessage.value = typeof payload.submittedMessage === 'string' ? payload.submittedMessage : ''
    copilotAnswer.value = typeof payload.answer === 'string' ? payload.answer : ''
    copilotError.value = typeof payload.error === 'string' ? payload.error : ''
    copilotSteps.value = Array.isArray(payload.steps) ? payload.steps : []
    copilotLoading.value = false
    copilotRevealing.value = false
    return true
  } catch {
    return false
  }
}

function removeSavedCopilotState(courseId = selectedCourseId.value, lessonId = selectedLessonId.value): void {
  if (typeof window === 'undefined') {
    return
  }

  const key = buildCopilotStorageKey(courseId, lessonId)
  if (!key) {
    return
  }

  window.localStorage.removeItem(key)
}

function persistCopilotState(): void {
  if (typeof window === 'undefined' || copilotLoading.value) {
    return
  }

  const key = buildCopilotStorageKey()
  if (!key) {
    return
  }

  const hasCopilotRecord =
    Boolean(copilotSubmittedMessage.value.trim()) ||
    Boolean(copilotAnswer.value.trim()) ||
    Boolean(copilotError.value.trim()) ||
    copilotSteps.value.length > 0

  if (!hasCopilotRecord) {
    window.localStorage.removeItem(key)
    return
  }

  const payload: SavedCopilotState = {
    version: copilotStorageVersion,
    message: copilotMessage.value,
    submittedMessage: copilotSubmittedMessage.value,
    answer: copilotAnswer.value,
    error: copilotError.value,
    steps: copilotSteps.value,
    savedAt: Date.now(),
  }
  window.localStorage.setItem(key, JSON.stringify(payload))
}

async function scrollCopilotTimelineToBottom(): Promise<void> {
  await nextTick()
  const container = copilotTimelineScrollRef.value
  if (!container) {
    return
  }
  container.scrollTop = container.scrollHeight
  container.scrollIntoView({ block: 'end' })
}

async function selectLesson(item: LessonHistoryItem): Promise<void> {
  clearPollTimer()
  clearCopilotRevealTimer()
  selectedLesson.value = item
  note.value = null
  statusMessage.value = ''
  errorMessage.value = ''
  focusText.value = ''

  if (!item.course_id || !item.lesson_id) {
    resetCopilotState()
    errorMessage.value = '这节课缺少 course_id 或 lesson_id。'
    return
  }

  if (!loadSavedCopilotState(item.course_id, item.lesson_id)) {
    resetCopilotState()
  }

  await loadLatestNote(item.course_id, item.lesson_id)
}

async function loadLatestNote(courseId: string, lessonId: string): Promise<void> {
  loadingLatest.value = true
  errorMessage.value = ''

  try {
    const response = await fetchLatestLessonNote(courseId, lessonId, backendBaseUrl.value)
    note.value = response.item
    updateStatusFromNote(response.item)
    if (response.item.status === 'generating') {
      schedulePoll(response.item.note_id)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : '获取课后笔记失败。'
    if (message.includes('not found')) {
      note.value = null
      removeSavedCopilotState(courseId, lessonId)
      resetCopilotState()
      statusMessage.value = '这节课还没有生成过课后笔记。'
    } else {
      errorMessage.value = message
    }
  } finally {
    loadingLatest.value = false
  }
}

async function refreshLatestNote(): Promise<void> {
  if (!selectedCourseId.value || !selectedLessonId.value) {
    return
  }
  await loadLatestNote(selectedCourseId.value, selectedLessonId.value)
}

async function requestGenerate(force = false): Promise<void> {
  if (!canGenerate.value) {
    return
  }

  generating.value = true
  errorMessage.value = ''
  statusMessage.value = ''
  clearPollTimer()

  try {
    const response = await generateLessonNote(
      selectedCourseId.value,
      selectedLessonId.value,
      {
        focus: focusText.value.trim() || undefined,
        force,
      },
      backendBaseUrl.value,
    )
    note.value = response.item
    updateStatusFromNote(response.item)
    if (response.item.status === 'generating' || response.queued) {
      schedulePoll(response.item.note_id)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '生成课后笔记失败。'
  } finally {
    generating.value = false
  }
}

function schedulePoll(noteId: string): void {
  clearPollTimer()
  pollTimer = window.setTimeout(() => {
    void pollNote(noteId)
  }, 2500)
}

async function pollNote(noteId: string): Promise<void> {
  clearPollTimer()
  try {
    const response = await fetchLessonNote(noteId, backendBaseUrl.value)
    note.value = response.item
    updateStatusFromNote(response.item)
    if (response.item.status === 'generating') {
      schedulePoll(noteId)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新课后笔记状态失败。'
  }
}

function updateStatusFromNote(item: LessonNoteItem): void {
  if (item.status === 'done') {
    statusMessage.value = `已基于 ${item.source_record_count} 条课堂记录生成。`
    return
  }
  if (item.status === 'failed') {
    statusMessage.value = item.error_message || '课后笔记生成失败。'
    return
  }
  statusMessage.value = '课后笔记正在生成。'
}

function resetCopilotState(): void {
  clearCopilotRevealTimer()
  copilotSubmittedMessage.value = ''
  copilotAnswer.value = ''
  copilotError.value = ''
  copilotLoading.value = false
  copilotRevealing.value = false
  copilotSteps.value = []
}

function revealCopilotSteps(steps: LessonCopilotStepItem[]): void {
  clearCopilotRevealTimer()
  copilotSteps.value = []
  copilotRevealing.value = steps.length > 0

  let index = 0
  const revealNext = () => {
    if (index >= steps.length) {
      copilotRevealTimer = null
      copilotRevealing.value = false
      persistCopilotState()
      void scrollCopilotTimelineToBottom()
      return
    }

    const step = steps[index]
    if (!step) {
      copilotRevealTimer = null
      copilotRevealing.value = false
      persistCopilotState()
      return
    }

    copilotSteps.value = [...copilotSteps.value, step]
    index += 1
    void scrollCopilotTimelineToBottom()
    copilotRevealTimer = window.setTimeout(revealNext, copilotStepRevealDelayMs)
  }

  copilotRevealTimer = window.setTimeout(revealNext, 120)
}

async function askCopilot(): Promise<void> {
  if (!canRunCopilot.value) {
    return
  }

  copilotLoading.value = true
  copilotRevealing.value = false
  copilotError.value = ''
  copilotAnswer.value = ''
  copilotSteps.value = []
  copilotSubmittedMessage.value = copilotMessage.value.trim()
  clearCopilotRevealTimer()

  try {
    let streamedStepCount = 0
    const response = await runLessonCopilotStream(
      selectedCourseId.value,
      selectedLessonId.value,
      {
        message: copilotMessage.value.trim(),
        session_id: selectedLesson.value?.last_session_id || undefined,
      },
      {
        onStep: (step) => {
          streamedStepCount += 1
          copilotSteps.value = [...copilotSteps.value, step]
          void scrollCopilotTimelineToBottom()
        },
        onError: (message) => {
          copilotError.value = message
        },
      },
      backendBaseUrl.value,
    )
    copilotAnswer.value = response.answer
    if (streamedStepCount === 0) {
      revealCopilotSteps(response.steps)
    } else {
      copilotSteps.value = response.steps
    }
    if (response.steps.some((step) => step.tool_name === 'generate_lesson_note' && step.tool_ok)) {
      await refreshLatestNote()
    }
  } catch (error) {
    copilotError.value = error instanceof Error ? error.message : 'Lesson copilot request failed.'
    persistCopilotState()
  } finally {
    copilotLoading.value = false
    persistCopilotState()
  }
}

function formatCopilotStepLabel(step: LessonCopilotStepItem): string {
  if (step.action === 'tool') {
    return step.tool_name || 'tool'
  }
  if (step.action === 'final') {
    return 'final'
  }
  return step.action || 'step'
}

function formatToolStatus(step: LessonCopilotStepItem): string {
  if (step.tool_ok === true) {
    return 'success'
  }
  if (step.tool_ok === false) {
    return 'failed'
  }
  return 'pending'
}

function formatJson(value: unknown): string {
  if (value == null) {
    return ''
  }
  if (typeof value === 'string') {
    return value
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatDateTime(timestamp?: number): string {
  if (!timestamp) {
    return '-'
  }
  return new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false })
}

function exportMarkdown(): void {
  const markdown = note.value?.markdown?.trim()
  if (!markdown || !selectedCourseId.value || !selectedLessonId.value) {
    return
  }

  const fileName = `${selectedCourseId.value}-${selectedLessonId.value}-lesson-note.md`
    .replace(/[\\/:*?"<>|]+/g, '-')
    .replace(/\s+/g, '-')
  const blob = new Blob([`${markdown}\n`], { type: 'text/markdown;charset=utf-8' })
  const objectUrl = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = objectUrl
  anchor.download = fileName
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(objectUrl)
}

watch(
  () => [copilotTimeline.value.length, copilotLoading.value, copilotRevealing.value],
  () => {
    void scrollCopilotTimelineToBottom()
  },
  { flush: 'post' },
)

watch(
  () => copilotMessage.value,
  () => {
    persistCopilotState()
  },
)

onBeforeUnmount(() => {
  clearPollTimer()
  clearCopilotRevealTimer()
  persistCopilotState()
})
</script>

<template>
  <div class="flex h-screen min-h-0 flex-col overflow-hidden bg-[rgb(var(--bg-base))]">
    <header class="border-b border-[rgba(var(--line-soft),0.08)] bg-[#fffaf2]/90 backdrop-blur-md">
      <div class="mx-auto flex h-16 w-full max-w-[1600px] items-center justify-between gap-4 px-4 md:px-6">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.24em] text-[rgb(var(--text-faint))]">
            Study Agent
          </p>
          <h1 class="text-lg font-semibold text-[rgb(var(--text-main))]">学习资料库</h1>
        </div>

        <div class="flex items-center gap-2">
          <RouterLink
            to="/history"
            class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-4 py-2 text-sm font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95"
          >
            历史回顾
          </RouterLink>
          <RouterLink
            to="/"
            class="rounded-full bg-[rgb(var(--accent))] px-4 py-2 text-sm font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95"
          >
            返回课堂
          </RouterLink>
        </div>
      </div>
    </header>

    <main class="min-h-0 flex-1 overflow-hidden p-3">
      <div class="grid h-full min-h-0 gap-3 lg:grid-cols-[360px_1fr]">
        <SideBar class="min-h-0" @select="selectLesson" />

        <section class="flex min-h-0 flex-col overflow-y-auto rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))]">
          <template v-if="selectedLesson">
            <div class="shrink-0 border-b border-[rgba(var(--line-soft),0.08)] p-5">
              <div class="flex flex-wrap items-start justify-between gap-4">
                <div class="min-w-0">
                  <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
                    Lesson Notes
                  </p>
                  <h2 class="mt-2 truncate text-2xl font-semibold text-[rgb(var(--text-main))]">
                    {{ selectedLesson.course_id || '未命名课程' }}
                  </h2>
                  <p class="mt-1 truncate text-sm text-[rgb(var(--text-subtle))]">
                    {{ selectedLesson.lesson_id || '未知课时' }}
                  </p>
                </div>

                <div class="flex flex-wrap items-center justify-end gap-2">
                  <span class="rounded-full bg-[rgba(var(--accent),0.12)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--accent))]">
                    {{ noteStatusLabel }}
                  </span>
                  <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--text-subtle))]">
                    {{ selectedLesson.transcript_count || 0 }} 条记录
                  </span>
                </div>
              </div>

              <div class="mt-4 grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto_auto_auto]">
                <input
                  v-model="focusText"
                  type="text"
                  placeholder="聚焦方向"
                  class="min-w-0 rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-2.5 text-sm outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
                />
                <button
                  type="button"
                  class="rounded-[var(--radius-soft)] bg-[rgb(var(--accent))] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  :disabled="!canGenerate"
                  @click="requestGenerate(false)"
                >
                  {{ generating || note?.status === 'generating' ? '生成中' : '生成笔记' }}
                </button>
                <button
                  type="button"
                  class="rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.95)] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  :disabled="!canGenerate"
                  @click="requestGenerate(true)"
                >
                  重新生成
                </button>
                <button
                  type="button"
                  class="rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.95)] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  :disabled="!canExportMarkdown"
                  @click="exportMarkdown"
                >
                  导出 Markdown
                </button>
              </div>

              <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-[rgb(var(--text-faint))]">
                <button
                  type="button"
                  class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5 font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  :disabled="loadingLatest"
                  @click="refreshLatestNote"
                >
                  {{ loadingLatest ? '刷新中' : '刷新' }}
                </button>
                <span v-if="note">更新时间 {{ formatDateTime(note.updated_at) }}</span>
                <span v-if="note?.model_name">模型 {{ note.model_name }}</span>
                <span v-if="statusMessage">{{ statusMessage }}</span>
              </div>

              <p
                v-if="errorMessage"
                class="mt-3 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
              >
                {{ errorMessage }}
              </p>

              <div class="mt-4 rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-base))] p-4">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p class="text-xs font-semibold uppercase tracking-[0.18em] text-[rgb(var(--text-faint))]">
                      Lesson Copilot
                    </p>
                    <p class="mt-1 text-sm text-[rgb(var(--text-subtle))]">
                      Ask DeepSeek to decide whether to reuse an existing note or generate one first.
                    </p>
                  </div>
                  <button
                    type="button"
                    class="rounded-[var(--radius-soft)] bg-[rgb(var(--accent))] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                    :disabled="!canRunCopilot"
                    @click="askCopilot"
                  >
                    {{ copilotLoading ? 'Running…' : 'Ask Copilot' }}
                  </button>
                </div>

                <textarea
                  v-model="copilotMessage"
                  rows="3"
                  class="mt-3 w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-elevated))] px-3 py-2.5 text-sm leading-6 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
                  placeholder="Ask for a review plan, note generation, or a quick lesson summary."
                />

                <p
                  v-if="copilotError"
                  class="mt-3 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
                >
                  {{ copilotError }}
                </p>

                <div
                  v-if="copilotLoading || copilotRevealing || copilotTimeline.length"
                  class="mt-4 rounded-[var(--radius-soft)] bg-[rgb(var(--bg-elevated))] p-4"
                >
                  <p class="text-xs font-semibold uppercase tracking-[0.18em] text-[rgb(var(--text-faint))]">
                    Copilot Timeline
                  </p>

                  <div ref="copilotTimelineScrollRef" class="mt-3 space-y-3 pr-1">
                    <article
                      v-for="item in copilotTimeline"
                      :key="item.key"
                      class="rounded-[var(--radius-soft)] border px-4 py-3"
                      :class="
                        item.kind === 'user'
                          ? 'ml-auto max-w-[88%] border-[rgba(var(--accent),0.16)] bg-[rgba(var(--accent),0.08)]'
                          : item.kind === 'error'
                            ? 'border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)]'
                            : item.kind === 'final'
                              ? 'border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-base))]'
                              : 'border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-base))]'
                      "
                    >
                      <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                        <span v-if="item.kind === 'user'">User</span>
                        <span v-else-if="item.kind === 'thought'">Thinking</span>
                        <span v-else-if="item.kind === 'tool'">Tool Call</span>
                        <span v-else-if="item.kind === 'final'">Final</span>
                        <span v-else>Error</span>
                        <span v-if="item.step && item.kind !== 'thought'">/</span>
                        <span v-if="item.step && item.kind !== 'thought'">{{ formatCopilotStepLabel(item.step) }}</span>
                        <span v-if="item.kind === 'tool' && item.step">/</span>
                        <span
                          v-if="item.kind === 'tool' && item.step"
                          class="rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-[0.08em]"
                          :class="
                            formatToolStatus(item.step) === 'success'
                              ? 'bg-[rgba(var(--accent),0.12)] text-[rgb(var(--accent))]'
                              : 'bg-[rgba(var(--danger),0.12)] text-[rgb(var(--danger))]'
                          "
                        >
                          {{ formatToolStatus(item.step) }}
                        </span>
                      </div>

                      <p
                        v-if="item.text"
                        class="mt-2 whitespace-pre-wrap text-sm leading-7"
                        :class="item.kind === 'error' ? 'text-[rgb(var(--danger))]' : 'text-[rgb(var(--text-main))]'"
                      >
                        {{ item.text }}
                      </p>

                      <div v-if="item.kind === 'tool' && item.step" class="mt-3 space-y-2">
                        <details
                          v-if="item.step.arguments && Object.keys(item.step.arguments).length"
                          class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-elevated))] px-3 py-2"
                        >
                          <summary class="cursor-pointer select-none text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                            Arguments
                          </summary>
                          <pre class="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap text-xs leading-5 text-[rgb(var(--text-subtle))]">{{ formatJson(item.step.arguments) }}</pre>
                        </details>
                        <details
                          v-if="item.step.tool_result"
                          class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-elevated))] px-3 py-2"
                        >
                          <summary class="cursor-pointer select-none text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                            Result
                          </summary>
                          <pre class="mt-2 max-h-[220px] overflow-auto whitespace-pre-wrap text-xs leading-5 text-[rgb(var(--text-subtle))]">{{ formatJson(item.step.tool_result) }}</pre>
                        </details>
                        <p v-if="item.step.error" class="text-xs text-[rgb(var(--danger))]">
                          {{ item.step.error }}
                        </p>
                      </div>
                    </article>

                    <article
                      v-if="copilotLoading || copilotRevealing"
                      class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-base))] px-4 py-3"
                    >
                      <div class="flex items-center gap-2 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                        <span>Thinking</span>
                      </div>
                      <p class="mt-2 text-sm leading-7 text-[rgb(var(--text-subtle))]">
                        正在决定下一步操作并整理结果。
                      </p>
                    </article>
                  </div>
                </div>
              </div>
            </div>

            <div class="shrink-0 p-5">
              <div v-if="loadingLatest && !note" class="space-y-3">
                <div
                  v-for="index in 6"
                  :key="index"
                  class="h-20 animate-pulse rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.9)]"
                />
              </div>

              <div
                v-else-if="!note"
                class="flex h-full min-h-[280px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
              >
                当前课节暂无课后笔记。
              </div>

              <div
                v-else-if="note.status === 'generating'"
                class="flex h-full min-h-[280px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
              >
                课后笔记正在生成。
              </div>

              <div
                v-else-if="note.status === 'failed'"
                class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] p-4 text-sm text-[rgb(var(--danger))]"
              >
                {{ note.error_message || '课后笔记生成失败。' }}
              </div>

              <div v-else class="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
                <article class="min-w-0 rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-5">
                  <p class="text-xs font-semibold uppercase tracking-[0.18em] text-[rgb(var(--text-faint))]">
                    Generated Note
                  </p>
                  <h3 class="mt-2 text-2xl font-semibold text-[rgb(var(--text-main))]">
                    {{ note.title || notePayload.title || '课后笔记' }}
                  </h3>
                  <p class="mt-3 whitespace-pre-wrap text-sm leading-7 text-[rgb(var(--text-subtle))]">
                    {{ note.summary || notePayload.overview }}
                  </p>

                  <section v-if="keyPoints.length" class="mt-6">
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">核心知识点</h4>
                    <ul class="mt-3 space-y-2">
                      <li
                        v-for="item in keyPoints"
                        :key="item"
                        class="rounded-[var(--radius-soft)] bg-[rgba(var(--accent),0.08)] px-3 py-2 text-sm leading-6 text-[rgb(var(--text-main))]"
                      >
                        {{ item }}
                      </li>
                    </ul>
                  </section>

                  <section v-if="concepts.length" class="mt-6">
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">概念</h4>
                    <div class="mt-3 grid gap-2 md:grid-cols-2">
                      <div
                        v-for="item in concepts"
                        :key="item.term"
                        class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-3"
                      >
                        <strong class="text-sm text-[rgb(var(--text-main))]">{{ item.term }}</strong>
                        <p class="mt-1 text-sm leading-6 text-[rgb(var(--text-subtle))]">
                          {{ item.explanation }}
                        </p>
                      </div>
                    </div>
                  </section>

                  <section v-if="examples.length" class="mt-6">
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">例子</h4>
                    <ul class="mt-3 space-y-2 text-sm leading-6 text-[rgb(var(--text-subtle))]">
                      <li v-for="item in examples" :key="item">- {{ item }}</li>
                    </ul>
                  </section>
                </article>

                <aside class="min-w-0 space-y-4">
                  <section
                    v-if="timeline.length"
                    class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4"
                  >
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">时间线</h4>
                    <div class="mt-3 space-y-3">
                      <div
                        v-for="item in timeline"
                        :key="`${item.time}-${item.content}`"
                        class="flex gap-3 text-sm leading-6"
                      >
                        <span class="shrink-0 font-mono text-xs text-[rgb(var(--text-faint))]">{{ item.time || '--:--' }}</span>
                        <span class="text-[rgb(var(--text-subtle))]">{{ item.content }}</span>
                      </div>
                    </div>
                  </section>

                  <section
                    v-if="reviewItems.length"
                    class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4"
                  >
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">复习重点</h4>
                    <ul class="mt-3 space-y-2 text-sm leading-6 text-[rgb(var(--text-subtle))]">
                      <li v-for="item in reviewItems" :key="item">- {{ item }}</li>
                    </ul>
                  </section>

                  <section
                    v-if="questions.length"
                    class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4"
                  >
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">自测问题</h4>
                    <ul class="mt-3 space-y-2 text-sm leading-6 text-[rgb(var(--text-subtle))]">
                      <li v-for="item in questions" :key="item">- {{ item }}</li>
                    </ul>
                  </section>

                  <section class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4">
                    <h4 class="text-sm font-semibold text-[rgb(var(--text-main))]">Markdown</h4>
                    <pre class="mt-3 max-h-[360px] overflow-auto whitespace-pre-wrap rounded-[var(--radius-soft)] bg-[rgb(var(--bg-elevated))] p-3 text-xs leading-5 text-[rgb(var(--text-subtle))]">{{ note.markdown }}</pre>
                  </section>
                </aside>
              </div>
            </div>
          </template>

          <div
            v-else
            class="flex h-full min-h-[280px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] m-5 px-6 text-center text-sm text-[rgb(var(--text-faint))]"
          >
            从左侧选择一节课。
          </div>
        </section>
      </div>
    </main>
  </div>
</template>
