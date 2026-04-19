<script setup lang="ts">
import { storeToRefs } from 'pinia'

import { useRagChatStore } from '../stores/ragChat'

const ragChatStore = useRagChatStore()
const { errorMessage, retrievalResults } = storeToRefs(ragChatStore)
</script>

<template>
  <section
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
          Retrieval
        </p>
        <h2 class="text-xl font-semibold text-[rgb(var(--text-main))]">RAG 检索结果</h2>
      </div>
      <span class="rounded-full bg-[rgba(var(--bg-muted),0.95)] px-3 py-1 text-sm text-[rgb(var(--text-subtle))]">
        {{ retrievalResults.length }} 条上下文
      </span>
    </div>

    <div class="mt-4 flex-1 overflow-y-auto rounded-[var(--radius-soft)] bg-[rgb(var(--bg-base))] p-3">
      <p
        v-if="errorMessage"
        class="mb-3 rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
      >
        {{ errorMessage }}
      </p>

      <div v-if="retrievalResults.length" class="space-y-3">
        <article
          v-for="item in retrievalResults"
          :key="item.id"
          class="rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-3"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <h3 class="font-medium text-[rgb(var(--text-main))]">{{ item.title }}</h3>
              <p class="mt-1 text-xs uppercase tracking-[0.14em] text-[rgb(var(--text-faint))]">
                {{ item.source }}
              </p>
            </div>
            <span class="rounded-full bg-[rgba(var(--accent),0.12)] px-2.5 py-1 text-xs font-semibold text-[rgb(var(--accent))]">
              {{ item.score === null ? 'n/a' : item.score.toFixed(2) }}
            </span>
          </div>

          <p class="mt-3 text-sm leading-6 text-[rgb(var(--text-main))]">
            {{ item.snippet }}
          </p>

          <p class="mt-3 text-xs text-[rgb(var(--text-faint))]">
            Doc ID: {{ item.docId }}
          </p>
        </article>
      </div>

      <div
        v-else
        class="flex h-full min-h-[180px] items-center justify-center rounded-[var(--radius-soft)] border border-dashed border-[rgba(var(--line-soft),0.12)] px-6 text-center text-sm text-[rgb(var(--text-faint))]"
      >
        暂无检索结果。录音后在右下角输入问题，这里会展示真实 RAG 检索到的片段。
      </div>
    </div>
  </section>
</template>
