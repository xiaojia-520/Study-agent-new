<script setup lang="ts">
import { onMounted } from 'vue'
import { storeToRefs } from 'pinia'

import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const {
  currentCourseId,
  currentLessonId,
  currentSessionId,
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

onMounted(() => {
  void sessionStore.fetchMicrophones()
})
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

    <button
      type="button"
      class="mt-2 inline-flex items-center justify-center rounded-[var(--radius-soft)] border border-[rgba(var(--line-soft),0.14)] bg-[rgb(var(--bg-muted))] px-4 py-2.5 text-sm font-semibold text-[rgb(var(--text-main))] transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
      :disabled="recordButtonBusy"
      @click="sessionStore.startNewLesson"
    >
      新建一节课
    </button>
  </section>
</template>
