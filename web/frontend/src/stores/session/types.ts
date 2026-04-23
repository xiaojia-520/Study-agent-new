export type LessonSnapshotStatus = 'active' | 'stopped' | 'interrupted'
export type RefineStatusToastKind = 'syncing' | 'processing' | 'error'

export interface LessonSnapshot {
  session_id: string
  course_id: string
  lesson_id: string
  subject?: string | null
  model_name?: string | null
  sample_rate: number
  channels: number
  status: LessonSnapshotStatus
  updated_at: number
}

export interface RefineStatusToast {
  id: number
  visible: boolean
  kind: RefineStatusToastKind
  title: string
  message: string
  detail?: string
}
