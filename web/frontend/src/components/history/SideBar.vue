<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { fetchLessonHistory } from '../../api/studyAgent'
import { useSessionStore } from '../../stores/session'
import type { LessonHistoryItem } from '../../types/study'

const emit = defineEmits<{
  select: [item: LessonHistoryItem]
}>()

const sessionStore = useSessionStore()
const { backendBaseUrl } = storeToRefs(sessionStore)

const loading = ref(false)
const errorMessage = ref('')
const searchText = ref('')
const historyItems = ref<LessonHistoryItem[]>([])
const selectedKey = ref('')

const filteredItems = computed(() => {
  const keyword = searchText.value.trim().toLowerCase()
  if (!keyword) {
    return historyItems.value
  }

  return historyItems.value.filter((item) => {
    const haystack = [
      item.course_id || '',
      item.lesson_id || '',
      item.last_session_id || '',
      formatDateTime(item.last_at),
    ]
      .join(' ')
      .toLowerCase()
    return haystack.includes(keyword)
  })
})

async function loadHistory(): Promise<void> {
  loading.value = true
  errorMessage.value = ''

  try {
    const response = await fetchLessonHistory(80, backendBaseUrl.value)
    historyItems.value = response.items
    const firstItem = response.items[0]
    if (!selectedKey.value && firstItem) {
      selectLesson(firstItem)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '获取历史课程失败。'
  } finally {
    loading.value = false
  }
}

function lessonKey(item: LessonHistoryItem): string {
  return `${item.course_id || '-'}::${item.lesson_id || '-'}`
}

function selectLesson(item: LessonHistoryItem): void {
  selectedKey.value = lessonKey(item)
  emit('select', item)
}

function formatDateTime(timestamp: number): string {
  if (!timestamp) {
    return '未知时间'
  }

  return new Date(timestamp * 1000).toLocaleString('zh-CN', {
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortId(value?: string | null): string {
  return value?.slice(0, 8) || '-'
}

defineExpose({
  refresh: loadHistory,
})

onMounted(() => {
  void loadHistory()
})
</script>

<template>
  <aside
    class="flex h-full min-h-0 w-full flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
          History
        </p>
        <h2 class="mt-1 text-xl font-semibold text-[rgb(var(--text-main))]">历史课程</h2>
      </div>

      <button
        type="button"
        class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--text-subtle))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="loading"
        @click="loadHistory"
      >
        {{ loading ? '刷新中' : '刷新' }}
      </button>
    </div>

    <label class="mt-4 block">
      <span class="sr-only">搜索历史课程</span>
      <input
        v-model="searchText"
        type="search"
        placeholder="搜索 course / lesson / session"
        class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-2.5 text-sm outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
      />
    </label>

    <div class="mt-3 flex items-center justify-between text-xs text-[rgb(var(--text-faint))]">
      <span>{{ filteredItems.length }} 节课</span>
      <span>按最近问答排序</span>
    </div>

    <p
      v-if="errorMessage"
      class="mt-3 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
    >
      {{ errorMessage }}
    </p>

    <div class="mt-3 min-h-0 flex-1 overflow-y-auto pr-1">
      <div v-if="loading && historyItems.length === 0" class="space-y-3">
        <div
          v-for="index in 5"
          :key="index"
          class="h-28 animate-pulse rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.9)]"
        />
      </div>

      <div
        v-else-if="filteredItems.length === 0"
        class="flex h-full min-h-[220px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.14)] px-5 text-center text-sm leading-6 text-[rgb(var(--text-faint))]"
      >
        暂时没有历史问答记录。完成一次 RAG 问答后，这里会按课程和课时显示历史。
      </div>

      <ul v-else class="space-y-3">
        <li v-for="item in filteredItems" :key="lessonKey(item)">
          <button
            type="button"
            class="group w-full rounded-[var(--radius-soft)] border p-3 text-left transition hover:-translate-y-0.5 hover:shadow-sm"
            :class="
              selectedKey === lessonKey(item)
                ? 'border-[rgba(var(--accent),0.34)] bg-[rgba(var(--accent),0.1)]'
                : 'border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-base))]'
            "
            @click="selectLesson(item)"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold text-[rgb(var(--text-main))]">
                  {{ item.course_id || '未命名课程' }}
                </p>
                <p class="mt-1 truncate text-xs text-[rgb(var(--text-faint))]">
                  {{ item.lesson_id || '未知课时' }}
                </p>
              </div>

              <span
                class="shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold"
                :class="
                  selectedKey === lessonKey(item)
                    ? 'bg-[rgb(var(--accent))] text-[rgb(var(--text-inverse))]'
                    : 'bg-[rgba(var(--bg-muted),0.95)] text-[rgb(var(--text-subtle))]'
                "
              >
                {{ item.message_count }} 条
              </span>
            </div>

            <div class="mt-3 grid grid-cols-2 gap-2 text-xs text-[rgb(var(--text-subtle))]">
              <div class="rounded-[14px] bg-[rgba(var(--bg-muted),0.7)] px-2.5 py-2">
                <span class="block text-[rgb(var(--text-faint))]">最近</span>
                <strong class="mt-1 block font-semibold text-[rgb(var(--text-main))]">
                  {{ formatDateTime(item.last_at) }}
                </strong>
              </div>
              <div class="rounded-[14px] bg-[rgba(var(--bg-muted),0.7)] px-2.5 py-2">
                <span class="block text-[rgb(var(--text-faint))]">录音段</span>
                <strong class="mt-1 block font-semibold text-[rgb(var(--text-main))]">
                  {{ item.session_count }} 次
                </strong>
              </div>
            </div>

            <p class="mt-3 truncate text-xs text-[rgb(var(--text-faint))]">
              Last session: {{ shortId(item.last_session_id) }}
            </p>
          </button>
        </li>
      </ul>
    </div>
  </aside>
</template>

<style scoped>
</style>
