<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useRagChatStore } from '../stores/ragChat'
import { useSessionStore } from '../stores/session'
import RichMarkdown from './RichMarkdown.vue'

const ragChatStore = useRagChatStore()
const sessionStore = useSessionStore()
const {
  chatMessages,
  currentQuestion,
  errorMessage,
  includeRagContext,
  retrievalResults,
  selectedAssetIds,
  sending,
} = storeToRefs(ragChatStore)
const { assetList } = storeToRefs(sessionStore)

const scrollContainerRef = ref<HTMLElement | null>(null)
const showAssetPicker = ref(false)

const readyAssets = computed(() => assetList.value.filter((asset) => asset.status === 'done'))
const selectedAssetCount = computed(() => selectedAssetIds.value.length)

const contextSummary = computed(() =>
  selectedAssetCount.value > 0
    ? `资料 RAG · 已选 ${selectedAssetCount.value} 个文件`
    : includeRagContext.value
      ? retrievalResults.value.length > 0
        ? `课堂 RAG · ${retrievalResults.value.length} 条检索结果`
        : '课堂 RAG · 等待检索结果'
    : '纯 LLM 模式',
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

function isAssetSelected(assetId: string): boolean {
  return selectedAssetIds.value.includes(assetId)
}

onMounted(() => {
  void sessionStore.refreshLessonAssets()
})

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

    <label class="mt-3 inline-flex items-center gap-2 text-sm text-[rgb(var(--text-subtle))]">
      <input
        v-model="includeRagContext"
        type="checkbox"
        class="h-4 w-4 rounded border-[rgba(var(--line-soft),0.2)] text-[rgb(var(--accent))] focus:ring-[rgba(var(--accent),0.2)]"
      />
      <span>RAG 检索加入 prompt</span>
    </label>

    <div class="mt-3 rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.1)] bg-[rgb(var(--bg-base))] p-3">
      <div class="flex items-center justify-between gap-3">
        <div>
          <p class="text-sm font-semibold text-[rgb(var(--text-main))]">资料 RAG</p>
          <p class="text-xs text-[rgb(var(--text-faint))]">
            {{ selectedAssetCount ? `已选择 ${selectedAssetCount} 个文件` : '选择已入库资料参与问答' }}
          </p>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-[var(--radius-soft)] bg-[rgba(var(--accent),0.12)] px-3 py-2 text-sm font-semibold text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.18)]"
          @click="showAssetPicker = !showAssetPicker"
        >
          {{ showAssetPicker ? '收起' : '选择资料' }}
        </button>
      </div>

      <div v-if="showAssetPicker" class="mt-3 max-h-36 space-y-2 overflow-y-auto pr-1">
        <label
          v-for="asset in readyAssets"
          :key="asset.asset_id"
          class="flex cursor-pointer items-start gap-2 rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.68)] px-3 py-2 text-sm"
        >
          <input
            type="checkbox"
            class="mt-1 h-4 w-4 rounded border-[rgba(var(--line-soft),0.2)] text-[rgb(var(--accent))] focus:ring-[rgba(var(--accent),0.2)]"
            :checked="isAssetSelected(asset.asset_id)"
            @change="ragChatStore.toggleSelectedAsset(asset.asset_id)"
          />
          <span class="min-w-0">
            <span class="block truncate font-medium text-[rgb(var(--text-main))]">{{ asset.file_name }}</span>
            <span class="text-xs text-[rgb(var(--text-faint))]">{{ asset.record_count }} records</span>
          </span>
        </label>
        <p v-if="!readyAssets.length" class="text-sm text-[rgb(var(--text-faint))]">
          暂无已入库资料。先在左侧上传资料，解析完成后可选择。
        </p>
      </div>
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

          <RichMarkdown
            v-if="item.role === 'assistant'"
            class="mt-2 text-sm leading-6"
            :text="item.text"
          />
          <p v-else class="mt-2 whitespace-pre-line text-sm leading-6">
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
          placeholder="输入问题，默认走 LLM；勾选 RAG 后会把检索结果加入 prompt。"
          class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-3 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
        />
      </label>

      <button
        type="submit"
        class="inline-flex shrink-0 items-center justify-center rounded-[var(--radius-soft)] bg-[rgb(var(--accent))] px-4 py-3 font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
        :disabled="sending || !currentQuestion.trim()"
      >
        {{ sending ? '发送中...' : '提问' }}
      </button>
    </form>
  </section>
</template>
