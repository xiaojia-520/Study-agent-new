<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'

import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const {
  currentCourseId,
  currentLessonId,
  currentSessionId,
  assetCount,
  assetErrorMessage,
  assetList,
  assetUploading,
  errorMessage,
  microphone,
  microphones,
  model,
  modelOptions,
  recordButtonBusy,
  recording,
  sessionStageLabel,
  subject,
  transcriptCount,
} = storeToRefs(sessionStore)

const assetInputRef = ref<HTMLInputElement | null>(null)

onMounted(() => {
  void sessionStore.fetchMicrophones()
})

function openAssetPicker(): void {
  assetInputRef.value?.click()
}

async function handleAssetSelected(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) {
    return
  }
  await sessionStore.uploadLessonAsset(file)
}

function assetStatusLabel(status: string): string {
  return {
    uploaded: '已上传',
    submitting: '提交中',
    uploading: '上传到 MinerU',
    pending: '排队中',
    running: '解析中',
    converting: '转换中',
    downloading: '下载结果',
    parsed: '解析完成',
    done: '已入库',
    failed: '失败',
    indexing_failed: '入库失败',
  }[status] || status
}

function formatFileSize(size: number): string {
  if (!Number.isFinite(size) || size <= 0) {
    return '0 KB'
  }
  if (size >= 1024 * 1024) {
    return `${(size / 1024 / 1024).toFixed(1)} MB`
  }
  return `${Math.max(1, Math.round(size / 1024))} KB`
}
</script>

<template>
  <section
    class="flex h-full min-h-0 flex-col overflow-hidden rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] p-4"
  >
    <div class="flex items-start justify-between gap-4">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.2em] text-[rgb(var(--text-faint))]">
          Session
        </p>
        <h2 class="text-xl font-semibold text-[rgb(var(--text-main))]">语音设置</h2>
      </div>

      <span
        class="rounded-full px-3 py-1 text-sm"
        :class="
          recording
            ? 'bg-[rgba(var(--success),0.16)] text-[rgb(var(--success))]'
            : 'bg-[rgba(var(--line-soft),0.08)] text-[rgb(var(--text-subtle))]'
        "
      >
        {{ sessionStageLabel }}
      </span>
    </div>

    <div class="mt-4 flex-1 overflow-y-auto pr-1">
      <div class="space-y-4">
        <label class="block space-y-2">
          <span class="text-sm font-medium text-[rgb(var(--text-subtle))]">课程名称</span>
          <input
            v-model="subject"
            type="text"
            placeholder="输入课程名称，对应后端 subject"
            class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-2.5 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
          />
        </label>

        <label class="block space-y-2">
          <span class="text-sm font-medium text-[rgb(var(--text-subtle))]">模型选择</span>
          <select
            v-model="model"
            class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-2.5 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
          >
            <option v-for="option in modelOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </option>
          </select>
        </label>

        <label class="block space-y-2">
          <span class="text-sm font-medium text-[rgb(var(--text-subtle))]">麦克风选择</span>
          <select
            v-model="microphone"
            class="w-full rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.12)] bg-[rgb(var(--bg-base))] px-3 py-2.5 outline-none transition focus:border-[rgba(var(--accent),0.45)] focus:ring-2 focus:ring-[rgba(var(--accent),0.18)]"
          >
            <option v-for="item in microphones" :key="item.id" :value="item.id">
              {{ item.label }}
            </option>
          </select>
        </label>

        <div class="rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.82)] p-3 text-sm text-[rgb(var(--text-subtle))]">
          <div class="flex items-center justify-between">
            <span>当前模型</span>
            <strong class="text-[rgb(var(--text-main))]">{{ model }}</strong>
          </div>
          <div class="mt-2 flex items-center justify-between">
            <span>已生成转写</span>
            <strong class="text-[rgb(var(--text-main))]">{{ transcriptCount }}</strong>
          </div>
          <div class="mt-2 flex items-center justify-between">
            <span>课堂素材</span>
            <strong class="text-[rgb(var(--text-main))]">{{ assetCount }}</strong>
          </div>
          <div class="mt-2 flex items-center justify-between">
            <span>Session</span>
            <strong class="text-[rgb(var(--text-main))]">{{ currentSessionId || '未创建' }}</strong>
          </div>
          <div class="mt-2 flex items-center justify-between">
            <span>Course / Lesson</span>
            <strong class="text-right text-[rgb(var(--text-main))]">
              {{ currentCourseId || '未生成' }} / {{ currentLessonId || '未生成' }}
            </strong>
          </div>
        </div>

        <div class="space-y-3 rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.1)] bg-[rgb(var(--bg-base))] p-3">
          <div class="flex items-center justify-between gap-3">
            <div>
              <p class="text-sm font-semibold text-[rgb(var(--text-main))]">课堂素材</p>
              <p class="text-xs text-[rgb(var(--text-faint))]">PDF / PPT / 图片会解析后进入问答检索</p>
            </div>
            <button
              type="button"
              class="shrink-0 rounded-[var(--radius-soft)] bg-[rgba(var(--accent),0.12)] px-3 py-2 text-sm font-semibold text-[rgb(var(--accent))] transition hover:bg-[rgba(var(--accent),0.18)] disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="assetUploading"
              @click="openAssetPicker"
            >
              {{ assetUploading ? '上传中' : '上传' }}
            </button>
            <input
              ref="assetInputRef"
              type="file"
              class="hidden"
              accept=".pdf,.doc,.docx,.ppt,.pptx,.png,.jpg,.jpeg,.jp2,.webp,.gif,.bmp,.html"
              @change="handleAssetSelected"
            />
          </div>

          <p
            v-if="assetErrorMessage"
            class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
          >
            {{ assetErrorMessage }}
          </p>

          <div v-if="assetList.length" class="space-y-2">
            <div
              v-for="asset in assetList"
              :key="asset.asset_id"
              class="rounded-[var(--radius-soft)] bg-[rgba(var(--bg-muted),0.72)] px-3 py-2"
            >
              <div class="flex items-center justify-between gap-3">
                <span class="min-w-0 truncate text-sm font-medium text-[rgb(var(--text-main))]">
                  {{ asset.file_name }}
                </span>
                <span
                  class="shrink-0 rounded-full px-2 py-0.5 text-xs"
                  :class="
                    asset.status === 'done'
                      ? 'bg-[rgba(var(--success),0.16)] text-[rgb(var(--success))]'
                      : asset.status === 'failed' || asset.status === 'indexing_failed'
                        ? 'bg-[rgba(var(--danger),0.14)] text-[rgb(var(--danger))]'
                        : 'bg-[rgba(var(--accent),0.12)] text-[rgb(var(--accent))]'
                  "
                >
                  {{ assetStatusLabel(asset.status) }}
                </span>
              </div>
              <div class="mt-1 flex items-center justify-between gap-3 text-xs text-[rgb(var(--text-faint))]">
                <span>{{ formatFileSize(asset.file_size) }}</span>
                <span v-if="asset.record_count">{{ asset.record_count }} records</span>
              </div>
              <p v-if="asset.error_message" class="mt-1 text-xs text-[rgb(var(--danger))]">
                {{ asset.error_message }}
              </p>
            </div>
          </div>
        </div>

        <p
          v-if="errorMessage"
          class="rounded-[var(--radius-soft)] border border-[rgba(var(--danger),0.18)] bg-[rgba(var(--danger),0.08)] px-3 py-2 text-sm text-[rgb(var(--danger))]"
        >
          {{ errorMessage }}
        </p>
      </div>
    </div>

    <button
      type="button"
      class="mt-4 inline-flex items-center justify-center rounded-[var(--radius-soft)] px-4 py-3 font-semibold text-[rgb(var(--text-inverse))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
      :class="recording ? 'bg-[rgb(var(--danger))]' : 'bg-[rgb(var(--accent))]'"
      :disabled="recordButtonBusy"
      @click="sessionStore.toggleRecording"
    >
      {{ recordButtonBusy ? '准备中...' : recording ? '停止录音' : '开始录音' }}
    </button>
  </section>
</template>
