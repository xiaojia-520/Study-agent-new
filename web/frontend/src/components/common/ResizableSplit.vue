<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'

type SplitDirection = 'horizontal' | 'vertical'

const dividerSize = '1rem'
const dividerOffset = '0.5rem'

const props = withDefaults(
  defineProps<{
    modelValue: number
    direction?: SplitDirection
    min?: number
    max?: number
  }>(),
  {
    direction: 'horizontal',
    min: 20,
    max: 80,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: number]
}>()

const containerRef = ref<HTMLElement | null>(null)
const dragging = ref(false)

let moveListener: ((event: PointerEvent) => void) | null = null
let upListener: (() => void) | null = null

function clamp(value: number): number {
  return Math.min(props.max, Math.max(props.min, value))
}

function updateFromPointer(event: PointerEvent): void {
  const container = containerRef.value
  if (!container) {
    return
  }

  const rect = container.getBoundingClientRect()
  const availableSize = props.direction === 'horizontal' ? rect.height : rect.width
  if (availableSize <= 0) {
    return
  }

  const offset = props.direction === 'horizontal' ? event.clientY - rect.top : event.clientX - rect.left
  emit('update:modelValue', clamp((offset / availableSize) * 100))
}

function stopDragging(): void {
  dragging.value = false
  document.body.style.userSelect = ''
  document.body.style.cursor = ''

  if (moveListener) {
    window.removeEventListener('pointermove', moveListener)
    moveListener = null
  }

  if (upListener) {
    window.removeEventListener('pointerup', upListener)
    window.removeEventListener('pointercancel', upListener)
    upListener = null
  }
}

function startDragging(event: PointerEvent): void {
  if (event.button !== 0) {
    return
  }

  event.preventDefault()
  dragging.value = true
  document.body.style.userSelect = 'none'
  document.body.style.cursor = props.direction === 'horizontal' ? 'ns-resize' : 'ew-resize'

  moveListener = (moveEvent: PointerEvent) => {
    updateFromPointer(moveEvent)
  }
  upListener = () => {
    stopDragging()
  }

  window.addEventListener('pointermove', moveListener)
  window.addEventListener('pointerup', upListener)
  window.addEventListener('pointercancel', upListener)

  updateFromPointer(event)
}

const wrapperClass = computed(() =>
  props.direction === 'horizontal'
    ? 'flex h-full min-h-0 flex-col overflow-hidden'
    : 'flex h-full min-h-0 flex-row overflow-hidden',
)

const beforeStyle = computed(() =>
  props.direction === 'horizontal'
    ? {
        height: `calc(${props.modelValue}% - ${dividerOffset})`,
        minHeight: '0',
        flexShrink: '0',
      }
    : {
        width: `calc(${props.modelValue}% - ${dividerOffset})`,
        minWidth: '0',
        flexShrink: '0',
      },
)

const afterStyle = computed(() =>
  props.direction === 'horizontal'
    ? {
        height: `calc(${100 - props.modelValue}% - ${dividerOffset})`,
        minHeight: '0',
        flexShrink: '0',
      }
    : {
        width: `calc(${100 - props.modelValue}% - ${dividerOffset})`,
        minWidth: '0',
        flexShrink: '0',
      },
)

const dividerClass = computed(() =>
  props.direction === 'horizontal'
    ? 'flex shrink-0 cursor-ns-resize items-center justify-center'
    : 'flex shrink-0 cursor-ew-resize items-center justify-center',
)

onBeforeUnmount(() => {
  stopDragging()
})
</script>

<template>
  <div ref="containerRef" :class="wrapperClass">
    <section :style="beforeStyle" class="min-h-0 min-w-0 flex-none overflow-hidden">
      <slot name="before" />
    </section>

    <button
      type="button"
      class="group relative shrink-0 select-none touch-none outline-none"
      :class="dividerClass"
      aria-label="Resize panes"
      :aria-orientation="direction"
      :data-dragging="dragging"
      :style="direction === 'horizontal' ? { height: dividerSize } : { width: dividerSize }"
      @pointerdown="startDragging"
    >
      <span
        class="absolute rounded-full border border-[rgba(var(--line-soft),0.08)] bg-[rgb(var(--bg-elevated))] shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition"
        :class="
          direction === 'horizontal'
            ? 'h-4 w-full max-w-40 px-3 py-1'
            : 'h-full max-h-40 w-4 py-3'
        "
      >
        <span
          class="absolute inset-x-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[rgba(var(--line-soft),0.32)]"
          :class="direction === 'horizontal' ? 'h-1.5 w-10' : 'h-10 w-1.5'"
        />
      </span>
    </button>

    <section :style="afterStyle" class="min-h-0 min-w-0 flex-none overflow-hidden">
      <slot name="after" />
    </section>
  </div>
</template>
