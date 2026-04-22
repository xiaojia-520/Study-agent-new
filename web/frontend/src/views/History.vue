<script setup lang="ts">
import { ref } from 'vue'
import { RouterLink } from 'vue-router'

import SideBar from '../components/history/SideBar.vue'
import type { LessonHistoryItem } from '../types/study'

const selectedLesson = ref<LessonHistoryItem | null>(null)

function selectLesson(item: LessonHistoryItem): void {
  selectedLesson.value = item
}

function formatDateTime(timestamp?: number): string {
  if (!timestamp) {
    return '-'
  }
  return new Date(timestamp * 1000).toLocaleString('zh-CN', { hour12: false })
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
          class="min-h-0 overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-5"
        >
          <template v-if="selectedLesson">
            <div class="flex items-start justify-between gap-4">
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

              <span class="rounded-full bg-[rgba(var(--accent),0.12)] px-3 py-1.5 text-sm font-semibold text-[rgb(var(--accent))]">
                {{ selectedLesson.message_count }} 条问答
              </span>
            </div>

            <div class="mt-6 grid gap-3 md:grid-cols-3">
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

            <div
              class="mt-6 rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.16)] bg-[rgb(var(--bg-base))] p-6 text-sm leading-6 text-[rgb(var(--text-subtle))]"
            >
              这里后续可以接入问答消息列表和转写列表。当前已经选中了 lesson，父页面可以用
              <code class="rounded bg-[rgba(var(--bg-muted),0.9)] px-1.5 py-0.5">
                course_id + lesson_id
              </code>
              调用历史问答和转写接口。
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
