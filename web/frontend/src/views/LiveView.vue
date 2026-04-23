<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'

import HeaderBar from '../components/HeaderBar.vue'
import LLM from '../components/LLM.vue'
import RefineStatusToast from '../components/RefineStatusToast.vue'
import Retrieval from '../components/Retrieval.vue'
import Session from '../components/Session.vue'
import TranscriptOutput from '../components/TranscriptOutput.vue'
import { useRagChatStore } from '../stores/ragChat'
import { useSessionStore } from '../stores/session'

const minimumPaneWidth = 30
const maximumPaneWidth = 70
const dividerWidthOffset = '0.25rem'

const workspaceRef = ref<HTMLElement | null>(null)
const leftWidth = ref(55)

const sessionStore = useSessionStore()
const ragChatStore = useRagChatStore()
const { currentSessionId } = storeToRefs(sessionStore)

function clampWidth(nextWidth: number): number {
  return Math.min(maximumPaneWidth, Math.max(minimumPaneWidth, nextWidth))
}

function stopDragging(): void {
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
  window.removeEventListener('mousemove', onMouseMove)
  window.removeEventListener('mouseup', stopDragging)
}

function onMouseMove(event: MouseEvent): void {
  const container = workspaceRef.value
  if (!container) {
    return
  }

  const bounds = container.getBoundingClientRect()
  if (bounds.width <= 0) {
    return
  }

  const nextWidth = ((event.clientX - bounds.left) / bounds.width) * 100
  leftWidth.value = clampWidth(nextWidth)
}

function startDragging(event: MouseEvent): void {
  event.preventDefault()
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
        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${leftWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="basis-[50%] min-h-0">
            <TranscriptOutput class="h-full" />
          </div>

          <div class="min-h-0 flex-1">
            <Session class="h-full" />
          </div>
        </div>

        <button
          type="button"
          aria-label="调整左右分栏宽度"
          class="mx-2 h-full w-2 shrink-0 cursor-col-resize rounded-full
          bg-gray-200
          hover:bg-gray-500
          active:bg-gray-800
          transition"
          @mousedown="startDragging"
        />

        <div
          class="flex min-h-0 flex-col gap-3 overflow-hidden"
          :style="{ width: `calc(${100 - leftWidth}% - ${dividerWidthOffset})` }"
        >
          <div class="basis-[42%] min-h-0">
            <Retrieval class="h-full" />
          </div>

          <div class="min-h-0 flex-1">
            <LLM class="h-full" />
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
