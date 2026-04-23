import type { ModelKey, SessionInfo } from '../../types/study'
import {
  defaultChannels,
  defaultSampleRate,
  lastLessonStorageKey,
} from './constants'
import type { LessonSnapshot, LessonSnapshotStatus } from './types'

export function buildSessionConfigSignature(subject: string, model: ModelKey): string {
  return JSON.stringify({
    subject: subject.trim(),
    model,
    sampleRate: defaultSampleRate,
    channels: defaultChannels,
  })
}

export function buildLessonConfigSignature(subject: string): string {
  return JSON.stringify({
    subject: subject.trim(),
    sampleRate: defaultSampleRate,
    channels: defaultChannels,
  })
}

export function loadLastLessonSnapshot(): LessonSnapshot | null {
  if (typeof window === 'undefined') {
    return null
  }

  const raw = window.localStorage.getItem(lastLessonStorageKey)
  if (!raw) {
    return null
  }

  try {
    const payload = JSON.parse(raw) as Partial<LessonSnapshot>
    if (!payload.course_id || !payload.lesson_id || !payload.session_id) {
      return null
    }
    return {
      session_id: String(payload.session_id),
      course_id: String(payload.course_id),
      lesson_id: String(payload.lesson_id),
      subject: payload.subject ? String(payload.subject) : null,
      model_name: payload.model_name ? String(payload.model_name) : null,
      sample_rate: Number(payload.sample_rate || defaultSampleRate),
      channels: Number(payload.channels || defaultChannels),
      status: payload.status || 'stopped',
      updated_at: Number(payload.updated_at || Date.now()),
    }
  } catch {
    return null
  }
}

export function saveLessonSnapshot(args: {
  sessionInfo: SessionInfo | null
  subject: string
  model: ModelKey
  status: LessonSnapshotStatus
}): void {
  const { sessionInfo, subject, model, status } = args
  if (typeof window === 'undefined' || !sessionInfo) {
    return
  }

  const snapshot: LessonSnapshot = {
    session_id: sessionInfo.session_id,
    course_id: sessionInfo.course_id,
    lesson_id: sessionInfo.lesson_id,
    subject: sessionInfo.subject || subject.trim() || null,
    model_name: sessionInfo.model_name || model,
    sample_rate: sessionInfo.sample_rate || defaultSampleRate,
    channels: sessionInfo.channels || defaultChannels,
    status,
    updated_at: Date.now(),
  }
  window.localStorage.setItem(lastLessonStorageKey, JSON.stringify(snapshot))
}

export function buildCurrentLessonSnapshot(args: {
  sessionInfo: SessionInfo | null
  subject: string
  model: ModelKey
  recording: boolean
}): LessonSnapshot | null {
  const { sessionInfo, subject, model, recording } = args
  if (!sessionInfo) {
    return null
  }
  return {
    session_id: sessionInfo.session_id,
    course_id: sessionInfo.course_id,
    lesson_id: sessionInfo.lesson_id,
    subject: sessionInfo.subject || subject.trim() || null,
    model_name: sessionInfo.model_name || model,
    sample_rate: sessionInfo.sample_rate || defaultSampleRate,
    channels: sessionInfo.channels || defaultChannels,
    status: recording ? 'active' : 'stopped',
    updated_at: Date.now(),
  }
}

export function confirmContinueLesson(snapshot: LessonSnapshot): boolean {
  if (!snapshot) {
    return false
  }

  if (typeof window === 'undefined' || typeof window.confirm !== 'function') {
    return true
  }

  const updatedAt = new Date(snapshot.updated_at).toLocaleString('zh-CN', { hour12: false })
  const title = snapshot.subject || snapshot.course_id
  return window.confirm(
    [
      `检测到上一次课程：${title}`,
      `Lesson: ${snapshot.lesson_id}`,
      `最后记录时间：${updatedAt}`,
      '',
      '是否继续上一次课程？',
      '确定：继续同一节课；取消：开始新一节课。',
    ].join('\n'),
  )
}

export function chooseResumeSnapshot(): LessonSnapshot | null {
  const snapshot = loadLastLessonSnapshot()
  if (!snapshot) {
    return null
  }
  return confirmContinueLesson(snapshot) ? snapshot : null
}
