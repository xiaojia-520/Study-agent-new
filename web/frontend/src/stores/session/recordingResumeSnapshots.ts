import type { SessionInfo } from '../../types/study'
import {
  recordingResumeStorageKey,
  recordingResumeStorageTtlMs,
} from './constants'
import type {
  RecordingResumeSnapshot,
  RecordingResumeSnapshotStatus,
} from './types'

let expiryTimerId: number | undefined

function canUseBrowserStorage(): boolean {
  return typeof window !== 'undefined' && typeof window.localStorage !== 'undefined'
}

function normalizeSubject(value?: string | null): string {
  return (value || '').trim()
}

function isUsableSnapshot(value: unknown): value is RecordingResumeSnapshot {
  if (!value || typeof value !== 'object') {
    return false
  }
  const snapshot = value as Partial<RecordingResumeSnapshot>
  return Boolean(
    snapshot.session_id
      && snapshot.course_id
      && snapshot.lesson_id
      && snapshot.subject
      && typeof snapshot.saved_at === 'number'
      && typeof snapshot.expires_at === 'number',
  )
}

function scheduleSnapshotExpiry(snapshot: RecordingResumeSnapshot): void {
  if (!canUseBrowserStorage()) {
    return
  }
  if (expiryTimerId !== undefined) {
    window.clearTimeout(expiryTimerId)
    expiryTimerId = undefined
  }

  const delayMs = Math.max(0, snapshot.expires_at - Date.now())
  expiryTimerId = window.setTimeout(() => {
    const latest = loadRecordingResumeSnapshot()
    if (!latest || latest.expires_at <= Date.now()) {
      clearRecordingResumeSnapshot()
    }
  }, delayMs + 50)
}

export function clearRecordingResumeSnapshot(): void {
  if (!canUseBrowserStorage()) {
    return
  }
  if (expiryTimerId !== undefined) {
    window.clearTimeout(expiryTimerId)
    expiryTimerId = undefined
  }
  window.localStorage.removeItem(recordingResumeStorageKey)
}

export function loadRecordingResumeSnapshot(now = Date.now()): RecordingResumeSnapshot | null {
  if (!canUseBrowserStorage()) {
    return null
  }

  const rawValue = window.localStorage.getItem(recordingResumeStorageKey)
  if (!rawValue) {
    return null
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(rawValue)
  } catch {
    clearRecordingResumeSnapshot()
    return null
  }

  if (!isUsableSnapshot(parsed) || parsed.expires_at <= now) {
    clearRecordingResumeSnapshot()
    return null
  }

  scheduleSnapshotExpiry(parsed)
  return parsed
}

export function saveRecordingResumeSnapshot(args: {
  sessionInfo: SessionInfo | null
  subject: string
  status: RecordingResumeSnapshotStatus
  now?: number
}): void {
  if (!canUseBrowserStorage() || !args.sessionInfo) {
    return
  }

  const snapshotSubject = normalizeSubject(args.subject || args.sessionInfo.subject)
  if (!snapshotSubject || !args.sessionInfo.course_id || !args.sessionInfo.lesson_id) {
    return
  }

  const now = args.now ?? Date.now()
  const snapshot: RecordingResumeSnapshot = {
    session_id: args.sessionInfo.session_id,
    course_id: args.sessionInfo.course_id,
    lesson_id: args.sessionInfo.lesson_id,
    subject: snapshotSubject,
    status: args.status,
    saved_at: now,
    expires_at: now + recordingResumeStorageTtlMs,
  }

  window.localStorage.setItem(recordingResumeStorageKey, JSON.stringify(snapshot))
  scheduleSnapshotExpiry(snapshot)
}

export function confirmRecordingResumeSnapshot(subject: string): RecordingResumeSnapshot | null {
  const normalizedSubject = normalizeSubject(subject)
  if (!normalizedSubject || typeof window === 'undefined') {
    return null
  }

  const snapshot = loadRecordingResumeSnapshot()
  if (!snapshot || normalizeSubject(snapshot.subject) !== normalizedSubject) {
    return null
  }

  const shouldResume = window.confirm(
    `检测到课程「${snapshot.subject}」15 分钟内有上一次录音结果，是否接着上一次继续录音？`,
  )
  if (!shouldResume) {
    clearRecordingResumeSnapshot()
    return null
  }

  return snapshot
}
