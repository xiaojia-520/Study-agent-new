import type { ModelOption } from '../../types/study'

export const sessionModelOptions: ModelOption[] = [
  { label: 'paraformer-zh', value: 'paraformer-zh' },
  { label: 'paraformer-zh-streaming', value: 'paraformer-zh-streaming' },
  { label: 'paraformer-zh-streaming-2pass', value: 'paraformer-zh-streaming-2pass' },
]

export const sessionClientId = 'web-frontend'
export const defaultSampleRate = 16000
export const defaultChannels = 1
export const lastLessonStorageKey = 'study-agent:last-active-lesson'
