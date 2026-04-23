<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'

import {
  createSession,
  fetchLessonMessages,
  fetchLessonTranscripts,
  fetchRefinedLessonTranscripts,
  querySession,
} from '../api/studyAgent'
import LessonVideoReview from '../components/history/LessonVideoReview.vue'
import SideBar from '../components/history/SideBar.vue'
import { useSessionStore } from '../stores/session'
import type {
  LessonHistoryItem,
  LessonMessageItem,
  QueryResponse,
  RefinedTranscriptRecordItem,
  SessionInfo,
  TranscriptRecordItem,
} from '../types/study'

const sessionStore = useSessionStore()
const { backendBaseUrl } = storeToRefs(sessionStore)

const selectedLesson = ref<LessonHistoryItem | null>(null)
const messages = ref<LessonMessageItem[]>([])
const transcripts = ref<TranscriptRecordItem[]>([])
const refinedTranscripts = ref<RefinedTranscriptRecordItem[]>([])
const transcriptViewMode = ref<'raw' | 'refined'>('raw')
const loadingMessages = ref(false)
const loadingTranscripts = ref(false)
const loadingRefinedTranscripts = ref(false)
const reviewSession = ref<SessionInfo | null>(null)
const followUpQuestion = ref('')
const sendingFollowUp = ref(false)
const messageError = ref('')
const transcriptError = ref('')
const refinedTranscriptError = ref('')
const followUpError = ref('')

const activeTranscriptCount = computed(() =>
  transcriptViewMode.value === 'refined' ? refinedTranscripts.value.length : transcripts.value.length,
)
const activeTranscriptLoading = computed(() =>
  transcriptViewMode.value === 'refined' ? loadingRefinedTranscripts.value : loadingTranscripts.value,
)
const activeTranscriptError = computed(() =>
  transcriptViewMode.value === 'refined' ? refinedTranscriptError.value : transcriptError.value,
)
const activeTranscriptEmpty = computed(() =>
  transcriptViewMode.value === 'refined' ? refinedTranscripts.value.length === 0 : transcripts.value.length === 0,
)

async function selectLesson(item: LessonHistoryItem): Promise<void> {
  selectedLesson.value = item
  messages.value = []
  transcripts.value = []
  refinedTranscripts.value = []
  transcriptViewMode.value = 'raw'
  reviewSession.value = null
  followUpQuestion.value = ''
  messageError.value = ''
  transcriptError.value = ''
  refinedTranscriptError.value = ''
  followUpError.value = ''

  if (!item.course_id || !item.lesson_id) {
    const message = '这节课缺少 course_id 或 lesson_id，无法加载历史记录。'
    messageError.value = message
    transcriptError.value = message
    refinedTranscriptError.value = message
    return
  }

  await Promise.all([
    loadLessonMessages(item.course_id, item.lesson_id),
    loadLessonTranscripts(item.course_id, item.lesson_id),
    loadRefinedLessonTranscripts(item.course_id, item.lesson_id),
  ])
}

async function loadLessonMessages(courseId: string, lessonId: string): Promise<void> {
  loadingMessages.value = true
  try {
    const response = await fetchLessonMessages(courseId, lessonId, backendBaseUrl.value)
    messages.value = response.items
  } catch (error) {
    messageError.value = error instanceof Error ? error.message : '获取历史问答失败。'
  } finally {
    loadingMessages.value = false
  }
}

async function loadLessonTranscripts(courseId: string, lessonId: string): Promise<void> {
  loadingTranscripts.value = true
  try {
    const response = await fetchLessonTranscripts(courseId, lessonId, backendBaseUrl.value)
    transcripts.value = response.items
  } catch (error) {
    transcriptError.value = error instanceof Error ? error.message : '获取语音转写失败。'
  } finally {
    loadingTranscripts.value = false
  }
}

async function loadRefinedLessonTranscripts(courseId: string, lessonId: string): Promise<void> {
  loadingRefinedTranscripts.value = true
  try {
    const response = await fetchRefinedLessonTranscripts(courseId, lessonId, backendBaseUrl.value)
    refinedTranscripts.value = response.items
  } catch (error) {
    refinedTranscriptError.value = error instanceof Error ? error.message : 'Fetch refined transcripts failed.'
  } finally {
    loadingRefinedTranscripts.value = false
  }
}

function shouldRetryWithoutLlm(message: string): boolean {
  const normalized = message.toLowerCase()
  return (
    normalized.includes('llm is not enabled') ||
    normalized.includes('openai-compatible llm support') ||
    normalized.includes('rag_llm_api_key')
  )
}

async function ensureReviewSession(): Promise<SessionInfo> {
  if (reviewSession.value) {
    return reviewSession.value
  }

  const lesson = selectedLesson.value
  if (!lesson?.course_id || !lesson.lesson_id) {
    throw new Error('请先选择一节有效的历史课程。')
  }

  const session = await createSession(
    {
      course_id: lesson.course_id,
      lesson_id: lesson.lesson_id,
      subject: lesson.course_id,
      client_id: 'history-review',
    },
    backendBaseUrl.value,
  )
  reviewSession.value = session
  return session
}

function buildAssistantAnswer(response: QueryResponse): string {
  if (response.answer?.trim()) {
    return response.answer.trim()
  }
  if (response.results.length > 0) {
    return response.results
      .slice(0, 3)
      .map((item, index) => `${index + 1}. ${item.content}`)
      .join('\n\n')
  }
  return '当前没有检索到足够相关的历史内容。'
}

async function refreshLessonMessages(): Promise<void> {
  const lesson = selectedLesson.value
  if (!lesson?.course_id || !lesson.lesson_id) {
    return
  }
  await loadLessonMessages(lesson.course_id, lesson.lesson_id)
}

async function sendFollowUpQuestion(): Promise<void> {
  const question = followUpQuestion.value.trim()
  if (!question || sendingFollowUp.value) {
    return
  }

  sendingFollowUp.value = true
  followUpError.value = ''

  try {
    const session = await ensureReviewSession()
    let response: QueryResponse

    try {
      response = await querySession(
        session.session_id,
        {
          query: question,
          scope: 'auto',
          top_k: 5,
          with_llm: true,
        },
        backendBaseUrl.value,
      )
    } catch (error) {
      const message = error instanceof Error ? error.message : '历史追问失败。'
      if (!shouldRetryWithoutLlm(message)) {
        throw error
      }
      response = await querySession(
        session.session_id,
        {
          query: question,
          scope: 'auto',
          top_k: 5,
          with_llm: false,
        },
        backendBaseUrl.value,
      )
    }

    const now = Math.floor(Date.now() / 1000)
    messages.value = [
      ...messages.value,
      {
        id: now * 1000,
        session_id: session.session_id,
        course_id: session.course_id,
        lesson_id: session.lesson_id,
        role: 'user',
        content: question,
        created_at: now,
        metadata: {},
      },
      {
        id: now * 1000 + 1,
        session_id: session.session_id,
        course_id: session.course_id,
        lesson_id: session.lesson_id,
        role: 'assistant',
        content: buildAssistantAnswer(response),
        created_at: now,
        metadata: response.metadata,
      },
    ]
    followUpQuestion.value = ''
    await refreshLessonMessages()
  } catch (error) {
    followUpError.value = error instanceof Error ? error.message : '历史追问失败。'
  } finally {
    sendingFollowUp.value = false
  }
}

function formatDateTime(timestamp?: number): string {
  if (!timestamp) {
    return '-'
  }
  return new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false })
}

function formatTimelineTime(timestamp?: number): string {
  if (!timestamp) {
    return '--:--:--'
  }
  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<template>
  <div class="flex h-screen min-h-0 flex-col overflow-hidden bg-[rgb(var(--bg-base))]">
    <header class="border-b border-[rgba(var(--line-soft),0.08)] bg-[#fffaf2]/90 backdrop-blur-md">
      <div class="mx-auto flex h-16 w-full max-w-[1600px] items-center justify-between gap-4 px-4 md:px-6">
        <div>
          <p class="text-xs font-semibold uppercase tracking-[0.24em] text-[rgb(var(--text-faint))]">
            Study Agent
          </p>
          <h1 class="text-lg font-semibold text-[rgb(var(--text-main))]">历史回顾</h1>
        </div>

        <RouterLink
          to="/"
          class="rounded-full bg-[rgb(var(--accent))] px-4 py-2 text-sm font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95"
        >
          返回课堂
        </RouterLink>
      </div>
    </header>

    <main class="min-h-0 flex-1 overflow-hidden p-3">
      <div class="grid h-full min-h-0 gap-3 lg:grid-cols-[360px_1fr]">
        <SideBar class="min-h-0" @select="selectLesson" />

        <section
          class="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-5"
        >
          <template v-if="selectedLesson">
            <div class="flex shrink-0 items-start justify-between gap-4">
              <div class="min-w-0">
                <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
                  Selected Lesson
                </p>
                <h2 class="mt-2 truncate text-2xl font-semibold text-[rgb(var(--text-main))]">
                  {{ selectedLesson.course_id || '未命名课程' }}
                </h2>
                <p class="mt-1 truncate text-sm text-[rgb(var(--text-subtle))]">
                  {{ selectedLesson.lesson_id || '未知课时' }}
                </p>
              </div>

              <div class="flex shrink-0 flex-wrap justify-end gap-2">
                <span class="rounded-full bg-[rgba(var(--accent),0.12)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--accent))]">
                  {{ selectedLesson.message_count }} 条问答
                </span>
                <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--text-subtle))]">
                  {{ selectedLesson.transcript_count || 0 }} 条转写
                </span>
              </div>
            </div>

            <div class="mt-4 grid shrink-0 gap-3 md:grid-cols-3">
              <article class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4">
                <p class="text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">首次记录</p>
                <strong class="mt-2 block text-[rgb(var(--text-main))]">
                  {{ formatDateTime(selectedLesson.first_at) }}
                </strong>
              </article>
              <article class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4">
                <p class="text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">最近记录</p>
                <strong class="mt-2 block text-[rgb(var(--text-main))]">
                  {{ formatDateTime(selectedLesson.last_at) }}
                </strong>
              </article>
              <article class="rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-4">
                <p class="text-xs font-semibold uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">录音段数</p>
                <strong class="mt-2 block text-[rgb(var(--text-main))]">
                  {{ selectedLesson.session_count }} 次
                </strong>
              </article>
            </div>

            <LessonVideoReview
              class="mt-4 shrink-0"
              :course-id="selectedLesson.course_id"
              :lesson-id="selectedLesson.lesson_id"
            />

            <div class="mt-5 grid min-h-0 flex-1 gap-4 lg:grid-cols-2">
              <article class="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))]">
                <div class="flex shrink-0 items-center justify-between border-b border-[rgba(var(--line-soft),0.08)] px-4 py-3">
                  <div>
                    <p class="text-xs font-semibold uppercase tracking-[0.16em] text-[rgb(var(--text-faint))]">
                      QA Timeline
                    </p>
                    <h3 class="text-base font-semibold text-[rgb(var(--text-main))]">历史问答记录</h3>
                  </div>
                  <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-sm text-[rgb(var(--text-subtle))]">
                    {{ messages.length }} 条
                  </span>
                </div>

                <div class="min-h-0 flex-1 overflow-y-auto p-4">
                  <p
                    v-if="messageError"
                    class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
                  >
                    {{ messageError }}
                  </p>

                  <div v-else-if="loadingMessages" class="space-y-3">
                    <div
                      v-for="index in 5"
                      :key="index"
                      class="h-24 animate-pulse rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.9)]"
                    />
                  </div>

                  <div
                    v-else-if="messages.length === 0"
                    class="flex h-full min-h-[240px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
                  >
                    这节课还没有历史问答。
                  </div>

                  <div v-else class="space-y-3">
                    <section
                      v-for="item in messages"
                      :key="item.id"
                      class="rounded-[var(--radius-soft)] border p-4"
                      :class="
                        item.role === 'user'
                          ? 'border-[rgba(var(--accent),0.14)] bg-[rgba(var(--accent),0.08)]'
                          : 'border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))]'
                      "
                    >
                      <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                        <span>{{ formatTimelineTime(item.created_at) }}</span>
                        <span>/</span>
                        <span>{{ item.role === 'user' ? '提问' : '回答' }}</span>
                        <span>/</span>
                        <span>Session {{ item.session_id.slice(0, 8) }}</span>
                      </div>
                      <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-[rgb(var(--text-main))]">
                        {{ item.content }}
                      </p>
                    </section>
                  </div>
                </div>

                <form
                  class="shrink-0 border-t border-[rgba(var(--line-soft),0.08)] p-3"
                  @submit.prevent="sendFollowUpQuestion"
                >
                  <p
                    v-if="followUpError"
                    class="mb-2 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
                  >
                    {{ followUpError }}
                  </p>

                  <div class="flex gap-2">
                    <input
                      v-model="followUpQuestion"
                      type="text"
                      placeholder="继续追问这节课的内容..."
                      class="min-w-0 flex-1 rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-elevated))] px-3 py-2.5 text-sm outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
                    />
                    <button
                      type="submit"
                      class="shrink-0 rounded-[var(--radius-soft)] bg-[rgb(var(--accent))] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                      :disabled="sendingFollowUp || !followUpQuestion.trim()"
                    >
                      {{ sendingFollowUp ? '发送中' : '追问' }}
                    </button>
                  </div>

                  <p class="mt-2 text-xs text-[rgb(var(--text-faint))]">
                    {{ reviewSession ? `Review session ${reviewSession.session_id.slice(0, 8)}` : '发送时会自动创建 review session' }}
                  </p>
                </form>
              </article>

              <article class="flex min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))]">
                <div class="flex shrink-0 items-center justify-between border-b border-[rgba(var(--line-soft),0.08)] px-4 py-3">
                  <div>
                    <p class="text-xs font-semibold uppercase tracking-[0.16em] text-[rgb(var(--text-faint))]">
                      Voice Timeline
                    </p>
                    <h3 class="text-base font-semibold text-[rgb(var(--text-main))]">语音转写记录</h3>
                  </div>
                  <div class="flex items-center gap-2">
                    <div class="rounded-full bg-[rgba(var(--bg-muted),0.95)] p-1 text-xs font-semibold text-[rgb(var(--text-subtle))]">
                      <button
                        type="button"
                        class="rounded-full px-3 py-1 transition"
                        :class="transcriptViewMode === 'raw' ? 'bg-[rgb(var(--accent))] text-[rgb(var(--text-inverse))]' : 'hover:bg-[rgba(var(--line-soft),0.08)]'"
                        @click="transcriptViewMode = 'raw'"
                      >
                        原始
                      </button>
                      <button
                        type="button"
                        class="rounded-full px-3 py-1 transition"
                        :class="transcriptViewMode === 'refined' ? 'bg-[rgb(var(--accent))] text-[rgb(var(--text-inverse))]' : 'hover:bg-[rgba(var(--line-soft),0.08)]'"
                        @click="transcriptViewMode = 'refined'"
                      >
                        LLM 精修
                      </button>
                    </div>
                    <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-sm text-[rgb(var(--text-subtle))]">
                      {{ activeTranscriptCount }} 条
                    </span>
                  </div>
                </div>

                <div class="min-h-0 flex-1 overflow-y-auto p-4">
                  <p
                    v-if="activeTranscriptError"
                    class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
                  >
                    {{ activeTranscriptError }}
                  </p>

                  <div v-else-if="activeTranscriptLoading" class="space-y-3">
                    <div
                      v-for="index in 5"
                      :key="index"
                      class="h-20 animate-pulse rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.9)]"
                    />
                  </div>

                  <div
                    v-else-if="activeTranscriptEmpty"
                    class="flex h-full min-h-[240px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
                  >
                    {{ transcriptViewMode === 'refined' ? '暂无 LLM 精修结果，停止录音后会在后台生成。' : '这节课还没有语音转写记录。' }}
                  </div>

                  <div v-else class="space-y-3">
                    <template v-if="transcriptViewMode === 'refined'">
                      <section
                        v-for="item in refinedTranscripts"
                        :key="`refined-${item.id}`"
                        class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
                      >
                        <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                          <span>{{ formatTimelineTime(item.created_at) }}</span>
                          <span>/</span>
                          <span>chunk {{ item.chunk_id ?? '-' }}</span>
                          <span>/</span>
                          <span>Session {{ item.session_id?.slice(0, 8) || '-' }}</span>
                          <span>/</span>
                          <span>{{ item.model_name || 'LLM' }}</span>
                        </div>
                        <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-[rgb(var(--text-main))]">
                          {{ item.refined_text }}
                        </p>
                        <details class="mt-3 text-xs text-[rgb(var(--text-faint))]">
                          <summary class="cursor-pointer select-none font-semibold">原始转写</summary>
                          <p class="mt-2 whitespace-pre-wrap leading-5">{{ item.original_text }}</p>
                        </details>
                      </section>
                    </template>
                    <template v-else>
                      <section
                        v-for="item in transcripts"
                        :key="`${item.session_id}-${item.chunk_id}`"
                        class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
                      >
                        <div class="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                          <span>{{ formatTimelineTime(item.created_at) }}</span>
                          <span>/</span>
                          <span>chunk {{ item.chunk_id ?? '-' }}</span>
                          <span>/</span>
                          <span>Session {{ item.session_id?.slice(0, 8) || '-' }}</span>
                        </div>
                        <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-[rgb(var(--text-main))]">
                          {{ item.clean_text || item.text }}
                        </p>
                      </section>
                    </template>
                  </div>
                </div>
              </article>
            </div>
          </template>

          <div
            v-else
            class="flex h-full min-h-[280px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
          >
            从左侧选择一节历史课程。
          </div>
        </section>
      </div>
    </main>
  </div>
</template>
