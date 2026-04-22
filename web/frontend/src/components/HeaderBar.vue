<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'

import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const { backendBaseUrl, currentSessionId, recording, subject, transcriptCount, websocketState } =
  storeToRefs(sessionStore)

const sessionLabel = computed(() => subject.value.trim() || '未命名课程')
const recordingLabel = computed(() => (recording.value ? '录音中' : '待录音'))
const sessionCode = computed(() => currentSessionId.value.slice(0, 8) || '未创建')
</script>

<template>
  <header class="border-b border-[rgba(var(--line-soft),0.08)] bg-[#fffaf2]/90 backdrop-blur-md">
    <div class="mx-auto flex h-16 w-full max-w-[1600px] items-center justify-between gap-4 px-4 md:px-6">
      <div class="min-w-0">
        <p class="text-xs font-semibold uppercase tracking-[0.24em] text-[rgb(var(--text-faint))]">
          Study Agent
        </p>
        <h1 class="truncate text-lg font-semibold text-[rgb(var(--text-main))]">
          {{ sessionLabel }}
        </h1>
      </div>

      <div class="flex items-center gap-2 text-sm text-[rgb(var(--text-subtle))]">
        <RouterLink
          to="/history"
          class="rounded-full bg-[rgb(var(--accent))] px-3 py-1.5 font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95"
        >
          历史回顾
        </RouterLink>
        <RouterLink
          to="/workshop"
          class="rounded-full bg-[rgb(var(--accent))] px-3 py-1.5 font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95"
        >
          学习工坊
        </RouterLink>
        <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5">
          {{ transcriptCount }} 条转写
        </span>
        <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5">
          Session {{ sessionCode }}
        </span>
        <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1.5">
          WS {{ websocketState }}
        </span>
        <span
          class="rounded-full px-3 py-1.5"
          :class="
            recording
              ? 'bg-[rgba(var(--success),0.16)] text-[rgb(var(--success))]'
              : 'bg-[rgba(var(--line-soft),0.08)] text-[rgb(var(--text-subtle))]'
          "
        >
          {{ recordingLabel }}
        </span>
      </div>
    </div>
  </header>
</template>
