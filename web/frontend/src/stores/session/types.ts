export type RefineStatusToastKind = 'syncing' | 'processing' | 'error'

export interface RefineStatusToast {
  id: number
  visible: boolean
  kind: RefineStatusToastKind
  title: string
  message: string
  detail?: string
}

export type RecordingResumeSnapshotStatus = 'active' | 'stopped' | 'interrupted'

export interface RecordingResumeSnapshot {
  session_id: string
  course_id: string
  lesson_id: string
  subject: string
  status: RecordingResumeSnapshotStatus
  saved_at: number
  expires_at: number
}
