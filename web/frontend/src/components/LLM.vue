<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useRagChatStore } from '../stores/ragChat'

const ragChatStore = useRagChatStore()
const { chatMessages, currentQuestion, errorMessage, retrievalResults, sending } =
  storeToRefs(ragChatStore)

const scrollContainerRef = ref<HTMLElement | null>(null)

const contextSummary = computed(() =>
  retrievalResults.value.length > 0
    ? `将带入 ${retrievalResults.value.length} 条真实检索片段作为上下文`
    : '当前没有检索上下文，先录音后提问',
)

function formatTimestamp(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function submitQuestion(): Promise<void> {
  await ragChatStore.sendCurrentQuestion()
}

watch(
  () => chatMessages.value.length,
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
          LLM
        </p>
        <h2 class="text-xl font-semibold text-[rgb(var(--text-main))]">大模型问答</h2>
      </div>
      <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-sm text-[rgb(var(--text-subtle))]">
        {{ contextSummary }}
      </span>
    </div>

    <div
      ref="scrollContainerRef"
      class="mt-4 flex-1 overflow-y-auto rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-3"
    >
      <p
        v-if="errorMessage"
        class="mb-3 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
      >
        {{ errorMessage }}
      </p>

      <div class="space-y-3">
        <article
          v-for="item in chatMessages"
          :key="item.id"
          class="max-w-[88%] rounded-[var(--radius-soft)] px-4 py-3"
          :class="
            item.error
              ? 'bg-[rgba(var(--danger),0.08)] text-[rgb(var(--danger))]'
              : item.role === 'user'
                ? 'ml-auto bg-[rgba(var(--accent),0.12)] text-[rgb(var(--text-main))]'
                : 'bg-[rgb(var(--bg-elevated))] text-[rgb(var(--text-main))]'
          "
        >
          <div class="flex items-center justify-between gap-3 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
            <span>{{ item.role === 'user' ? '提问' : '回答' }}</span>
            <span>{{ formatTimestamp(item.createdAt) }}</span>
          </div>

          <p class="mt-2 whitespace-pre-line text-sm leading-6">
            {{ item.text }}
          </p>

          <p v-if="item.relatedSources?.length" class="mt-3 text-xs text-[rgb(var(--text-faint))]">
            Context: {{ item.relatedSources.join(', ') }}
          </p>
        </article>
      </div>
    </div>

    <form class="mt-4 flex shrink-0 gap-3" @submit.prevent="submitQuestion">
      <label class="min-w-0 flex-1">
        <span class="sr-only">输入问题</span>
        <input
          v-model="currentQuestion"
          type="text"
          placeholder="输入问题，右侧会调用真实 /query 接口并返回答案"
          class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-3 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
        />
      </label>

      <button
        type="submit"
        class="inline-flex shrink-0 items-center justify-center rounded-[var(--radius-soft)] bg-[rgb(var(--accent))] px-4 py-3 font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="sending || !currentQuestion.trim()"
      >
        {{ sending ? '发送中...' : '发送' }}
      </button>
    </form>
  </section>
</template>
