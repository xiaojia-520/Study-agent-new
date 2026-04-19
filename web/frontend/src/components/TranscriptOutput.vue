<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const { partialTranscript, transcriptList } = storeToRefs(sessionStore)

const scrollContainerRef = ref<HTMLElement | null>(null)

function formatTimestamp(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

watch(
  () => transcriptList.value.length,
  async () => {
    await nextTick()
    const container = scrollContainerRef.value
    if (!container) {
      return
    }
    container.scrollTop = container.scrollHeight
  },
  { flush: 'post' },
)
</script>

<template>
  <section
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
          Transcript
        </p>
        <h2 class="text-xl font-semibold text-[rgb(var(--text-main))]">实时转写输出</h2>
      </div>
      <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-sm text-[rgb(var(--text-subtle))]">
        {{ transcriptList.length }} 条
      </span>
    </div>

    <div
      ref="scrollContainerRef"
      class="mt-4 flex-1 overflow-y-auto rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-3"
    >
      <article
        v-if="partialTranscript"
        class="mb-3 rounded-[var(--radius-soft)] border border-[rgba(var(--accent),0.12)] bg-[rgba(var(--accent),0.08)] p-3"
      >
        <p class="text-xs font-medium uppercase tracking-[0.16em] text-[rgb(var(--text-faint))]">
          partial
        </p>
        <p class="mt-2 text-sm leading-6 text-[rgb(var(--text-main))]">
          {{ partialTranscript }}
        </p>
      </article>

      <div v-if="transcriptList.length" class="space-y-3">
        <article
          v-for="item in transcriptList"
          :key="item.id"
          class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-3"
        >
          <p class="text-xs font-medium uppercase tracking-[0.16em] text-[rgb(var(--text-faint))]">
            {{ formatTimestamp(item.timestamp) }}
          </p>
          <p class="mt-2 text-sm leading-6 text-[rgb(var(--text-main))]">
            {{ item.text }}
          </p>
        </article>
      </div>

      <div
        v-else
        class="flex h-full min-h-[220px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.12)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
      >
        当前还没有转写内容。点击左上角“开始录音”后，这里会显示真实后端返回的实时转写。
      </div>
    </div>
  </section>
</template>
