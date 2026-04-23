<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import HeaderBar from '../components/HeaderBar.vue'
import LLM from '../components/LLM.vue'
import RefineStatusToast from '../components/RefineStatusToast.vue'
import Session from '../components/Session.vue'
import TranscriptOutput from '../components/TranscriptOutput.vue'
import VideoWindow from '../components/VideoWindow.vue'
import { useRagChatStore } from '../stores/ragChat'
import { useSessionStore } from '../stores/session'

const minimumPaneWidth = 15
const dividerWidthOffset = '0.25rem'

const workspaceRef = ref<HTMLElement | null>(null)

// 三列宽度：左、中、右（右边自动算）
const leftWidth = ref(33)
const middleWidth = ref(27)
const rightWidth = computed(() => 100 - leftWidth.value - middleWidth.value)

// 当前拖动的是哪一个分隔条
const draggingDivider = ref<'left' | 'middle' | null>(null)

const sessionStore = useSessionStore()
const ragChatStore = useRagChatStore()
const { currentSessionId } = storeToRefs(sessionStore)

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function stopDragging(): void {
  draggingDivider.value = null
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', stopDragging)
}

function onMouseMove(event: MouseEvent): void {
  const container = workspaceRef.value
  if (!container || !draggingDivider.value) {
    return
  }

  const bounds = container.getBoundingClientRect()
  if (bounds.width <= 0) {
    return
  }

  const currentPercent = ((event.clientX - bounds.left) / bounds.width) * 100

  if (draggingDivider.value === 'left') {
    // 第一个分隔条：调整左栏宽度
    // 左栏最小 minimumPaneWidth
    // 中栏和右栏至少都保留 minimumPaneWidth
    const maxLeft = 100 - middleWidth.value - minimumPaneWidth
    leftWidth.value = clamp(currentPercent, minimumPaneWidth, maxLeft)
    return
  }

  if (draggingDivider.value === 'middle') {
    // 第二个分隔条的位置，是“左栏 + 中栏”的总宽度
    const minTotal = leftWidth.value + minimumPaneWidth
    const maxTotal = 100 - minimumPaneWidth
    const clampedTotal = clamp(currentPercent, minTotal, maxTotal)

    const nextMiddleWidth = clampedTotal - leftWidth.value
    const nextRightWidth = 100 - leftWidth.value - nextMiddleWidth

    if (
      nextMiddleWidth >= minimumPaneWidth &&
      nextRightWidth >= minimumPaneWidth
    ) {
      middleWidth.value = nextMiddleWidth
    }
  }
}

function startDragging(type: 'left' | 'middle', event: MouseEvent): void {
  event.preventDefault()
  draggingDivider.value = type
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
  window.addEventListener('mousemove', onMouseMove)
  window.addEventListener('mouseup', stopDragging)
}

watch(currentSessionId, (nextId, previousId) => {
  if (nextId && nextId !== previousId) {
    ragChatStore.resetForSession()
  }
})

onBeforeUnmount(() => {
  stopDragging()
  void sessionStore.cleanup()
})
</script>

<template>
  <div class="flex h-screen flex-col overflow-hidden bg-[rgb(var(--bg-base))]">
    <HeaderBar class="shrink-0" />
    <RefineStatusToast />

    <main class="flex-1 overflow-hidden">
      <div
        ref="workspaceRef"
        class="flex h-full overflow-hidden bg-[rgba(var(--bg-panel),0.78)] p-3 shadow-[var(--shadow-soft)] backdrop-blur-sm"
      >
        <!-- 左栏 -->
        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${leftWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="min-h-0 flex-1">
            <Session class="h-full" />
          </div>
        </div>

        <!-- 分隔条 1：左 / 中 -->
        <button
          type="button"
          aria-label="调整左栏和中栏宽度"
          class="mx-2 h-full w-2 shrink-0 cursor-col-resize rounded-full bg-gray-200 transition hover:bg-gray-500 active:bg-gray-800"
          @mousedown="startDragging('left', $event)"
        />

        <!-- 中栏 -->
        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${middleWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="min-h-0 flex-1">
            <TranscriptOutput class="h-full" />
          </div>
        </div>

        <!-- 分隔条 2：中 / 右 -->
        <button
          type="button"
          aria-label="调整中栏和右栏宽度"
          class="mx-2 h-full w-2 shrink-0 cursor-col-resize rounded-full bg-gray-200 transition hover:bg-gray-500 active:bg-gray-800"
          @mousedown="startDragging('middle', $event)"
        />

        <!-- 右栏 -->
        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${rightWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="basis-[42%] min-h-0">
            <VideoWindow class="h-full" />
          </div>

          <div class="min-h-0 flex-1">
            <LLM class="h-full" />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
