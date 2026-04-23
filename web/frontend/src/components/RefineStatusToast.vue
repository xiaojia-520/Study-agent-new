<script setup lang="ts">
import { computed, onBeforeUnmount, watch } from 'vue'
import { storeToRefs } from 'pinia'

import { useSessionStore } from '../stores/session'

const sessionStore = useSessionStore()
const { refineStatusToast } = storeToRefs(sessionStore)

let dismissTimer: number | undefined

const toneClass = computed(() => {
  switch (refineStatusToast.value?.kind) {
    case 'error':
      return 'border-[rgba(var(--danger),0.24)] bg-[rgba(var(--danger),0.08)] text-[rgb(var(--danger))]'
    case 'syncing':
      return 'border-[rgba(var(--accent),0.20)] bg-[rgba(var(--accent),0.08)] text-[rgb(var(--accent))]'
    default:
      return 'border-[rgba(var(--success),0.24)] bg-[rgba(var(--success),0.09)] text-[rgb(var(--success))]'
  }
})

const dotClass = computed(() => {
  switch (refineStatusToast.value?.kind) {
    case 'error':
      return 'bg-[rgb(var(--danger))]'
    case 'syncing':
      return 'bg-[rgb(var(--accent))]'
    default:
      return 'bg-[rgb(var(--success))]'
  }
})

watch(
  () => refineStatusToast.value?.id,
  (nextId) => {
    if (dismissTimer) {
      window.clearTimeout(dismissTimer)
      dismissTimer = undefined
    }
    if (!nextId || !refineStatusToast.value?.visible) {
      return
    }
    dismissTimer = window.setTimeout(() => {
      sessionStore.dismissRefineStatusToast(nextId)
    }, refineStatusToast.value.kind === 'error' ? 9000 : 6500)
  },
)

onBeforeUnmount(() => {
  if (dismissTimer) {
    window.clearTimeout(dismissTimer)
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="refine-toast">
      <aside
        v-if="refineStatusToast?.visible"
        class="fixed bottom-5 right-5 z-50 w-[min(360px,calc(100vw-2rem))] overflow-hidden rounded-[22px] border border-[rgba(var(--line-soft),0.12)] bg-[rgba(var(--bg-elevated),0.94)] p-4 text-[rgb(var(--text-main))] shadow-[0_24px_70px_rgba(34,25,10,0.18)] backdrop-blur-xl"
        role="status"
        aria-live="polite"
      >
        <div class="pointer-events-none absolute -right-8 -top-10 h-24 w-24 rounded-full bg-[rgba(var(--accent),0.14)] blur-2xl" />
        <div class="pointer-events-none absolute -bottom-8 left-4 h-20 w-20 rounded-full bg-[rgba(var(--success),0.12)] blur-2xl" />

        <div class="relative flex items-start gap-3">
          <div
            class="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border"
            :class="toneClass"
          >
            <span class="relative flex h-3 w-3">
              <span
                v-if="refineStatusToast.kind !== 'error'"
                class="absolute inline-flex h-full w-full animate-ping rounded-full opacity-55"
                :class="dotClass"
              />
              <span class="relative inline-flex h-3 w-3 rounded-full" :class="dotClass" />
            </span>
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-sm font-semibold text-[rgb(var(--text-main))]">
                  {{ refineStatusToast.title }}
                </p>
                <p class="mt-1 text-xs leading-5 text-[rgb(var(--text-subtle))]">
                  {{ refineStatusToast.message }}
                </p>
              </div>

              <button
                type="button"
                class="rounded-full px-2 py-0.5 text-sm text-[rgb(var(--text-faint))] transition hover:bg-[rgba(var(--line-soft),0.08)] hover:text-[rgb(var(--text-main))]"
                aria-label="关闭状态提示"
                @click="sessionStore.dismissRefineStatusToast(refineStatusToast.id)"
              >
                ×
              </button>
            </div>

            <p
              v-if="refineStatusToast.detail"
              class="mt-2 truncate rounded-full bg-[rgba(var(--bg-muted),0.72)] px-2.5 py-1 text-[11px] font-medium text-[rgb(var(--text-faint))]"
            >
              {{ refineStatusToast.detail }}
            </p>

            <div
              v-if="refineStatusToast.kind !== 'error'"
              class="mt-3 h-1 overflow-hidden rounded-full bg-[rgba(var(--line-soft),0.10)]"
            >
              <div class="refine-progress h-full rounded-full bg-[rgb(var(--accent))]" />
            </div>
          </div>
        </div>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
.refine-toast-enter-active,
.refine-toast-leave-active {
  transition:
    opacity 240ms ease,
    transform 280ms cubic-bezier(0.2, 0.9, 0.2, 1);
}

.refine-toast-enter-from,
.refine-toast-leave-to {
  opacity: 0;
  transform: translate3d(0, 18px, 0) scale(0.97);
}

.refine-progress {
  animation: refine-progress-slide 1.55s ease-in-out infinite;
  transform-origin: left;
  width: 46%;
}

@keyframes refine-progress-slide {
  0% {
    transform: translateX(-115%) scaleX(0.82);
  }
  48% {
    transform: translateX(70%) scaleX(1.08);
  }
  100% {
    transform: translateX(230%) scaleX(0.86);
  }
}

@media (prefers-reduced-motion: reduce) {
  .refine-toast-enter-active,
  .refine-toast-leave-active,
  .refine-progress {
    animation: none;
    transition: none;
  }
}
</style>
