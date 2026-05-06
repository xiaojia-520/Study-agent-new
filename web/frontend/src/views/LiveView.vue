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
const minimumPaneHeight = 28
const dividerWidthOffset = '0.25rem'
const dividerHeightOffset = '0.25rem'

const workspaceRef = ref<HTMLElement | null>(null)
const rightPaneRef = ref<HTMLElement | null>(null)

const leftWidth = ref(33)
const middleWidth = ref(27)
const topHeight = ref(56)

const rightWidth = computed(() => 100 - leftWidth.value - middleWidth.value)
const bottomHeight = computed(() => 100 - topHeight.value)

const draggingDivider = ref<'left' | 'middle' | 'right' | null>(null)

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
  if (!draggingDivider.value) {
    return
  }

  if (draggingDivider.value === 'right') {
    const container = rightPaneRef.value
    if (!container) {
      return
    }

    const bounds = container.getBoundingClientRect()
    if (bounds.height <= 0) {
      return
    }

    const currentPercent = ((event.clientY - bounds.top) / bounds.height) * 100
    const maxTop = 100 - minimumPaneHeight
    topHeight.value = clamp(currentPercent, minimumPaneHeight, maxTop)
    return
  }

  const container = workspaceRef.value
  if (!container) {
    return
  }

  const bounds = container.getBoundingClientRect()
  if (bounds.width <= 0) {
    return
  }

  const currentPercent = ((event.clientX - bounds.left) / bounds.width) * 100

  if (draggingDivider.value === 'left') {
    const maxLeft = 100 - middleWidth.value - minimumPaneWidth
    leftWidth.value = clamp(currentPercent, minimumPaneWidth, maxLeft)
    return
  }

  if (draggingDivider.value === 'middle') {
    const minTotal = leftWidth.value + minimumPaneWidth
    const maxTotal = 100 - minimumPaneWidth
    const clampedTotal = clamp(currentPercent, minTotal, maxTotal)

    const nextMiddleWidth = clampedTotal - leftWidth.value
    const nextRightWidth = 100 - leftWidth.value - nextMiddleWidth

    if (nextMiddleWidth >= minimumPaneWidth && nextRightWidth >= minimumPaneWidth) {
      middleWidth.value = nextMiddleWidth
    }
  }
}

function startDragging(type: 'left' | 'middle' | 'right', event: MouseEvent): void {
  event.preventDefault()
  draggingDivider.value = type
  document.body.style.userSelect = 'none'
  document.body.style.cursor = type === 'right' ? 'row-resize' : 'col-resize'
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
        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${leftWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="min-h-0 flex-1">
            <Session class="h-full" />
          </div>
        </div>

        <button
          type="button"
          aria-label="调整左侧和中间区域宽度"
          class="mx-2 h-full w-2 shrink-0 cursor-col-resize rounded-full bg-gray-200 transition hover:bg-gray-500 active:bg-gray-800"
          @mousedown="startDragging('left', $event)"
        />

        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${middleWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="min-h-0 flex-1">
            <TranscriptOutput class="h-full" />
          </div>
        </div>

        <button
          type="button"
          aria-label="调整中间和右侧区域宽度"
          class="mx-2 h-full w-2 shrink-0 cursor-col-resize rounded-full bg-gray-200 transition hover:bg-gray-500 active:bg-gray-800"
          @mousedown="startDragging('middle', $event)"
        />

        <div
          ref="rightPaneRef"
          class="flex min-h-0 flex-col overflow-hidden"
          :style="{ width: `calc(${rightWidth}% - ${dividerWidthOffset})` }"
        >
          <div
            class="min-h-0"
            :style="{ height: `calc(${topHeight}% - ${dividerHeightOffset})` }"
          >
            <VideoWindow class="h-full" />
          </div>

          <button
            type="button"
            aria-label="调整视频窗口和问答区域高度"
            class="my-2 h-2 w-full shrink-0 cursor-row-resize rounded-full bg-gray-200 transition hover:bg-gray-500 active:bg-gray-800"
            @mousedown="startDragging('right', $event)"
          />

          <div
            class="min-h-0 flex-1"
            :style="{ height: `calc(${bottomHeight}% - ${dividerHeightOffset})` }"
          >
            <LLM class="h-full" />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
