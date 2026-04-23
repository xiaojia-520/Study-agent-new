import type { Ref } from 'vue'

import {
  fetchLessonAsset,
  fetchSessionAssets,
  uploadSessionAsset,
} from '../../api/studyAgent'
import type { LessonAssetItem, SessionInfo } from '../../types/study'

export function createLessonAssetActions(args: {
  backendBaseUrl: Ref<string>
  sessionInfo: Ref<SessionInfo | null>
  assetList: Ref<LessonAssetItem[]>
  assetUploading: Ref<boolean>
  assetErrorMessage: Ref<string>
  ensureSession: () => Promise<SessionInfo>
  hydrateTranscriptsFromServer: () => Promise<void>
}) {
  const {
    backendBaseUrl,
    sessionInfo,
    assetList,
    assetUploading,
    assetErrorMessage,
    ensureSession,
    hydrateTranscriptsFromServer,
  } = args

  function upsertAsset(asset: LessonAssetItem): void {
    const next = [...assetList.value]
    const index = next.findIndex((item) => item.asset_id === asset.asset_id)
    if (index >= 0) {
      next[index] = asset
    } else {
      next.unshift(asset)
    }
    assetList.value = next
  }

  async function refreshSessionAssets(): Promise<void> {
    if (!sessionInfo.value) {
      assetList.value = []
      return
    }
    const response = await fetchSessionAssets(sessionInfo.value.session_id, backendBaseUrl.value)
    assetList.value = response.items
  }

  async function pollAssetStatus(assetId: string): Promise<void> {
    const startedAt = Date.now()
    const timeoutMs = 10 * 60 * 1000
    const finalStatuses = new Set(['done', 'failed', 'indexing_failed'])

    while (Date.now() - startedAt < timeoutMs) {
      const response = await fetchLessonAsset(assetId, backendBaseUrl.value)
      upsertAsset(response.item)
      if (finalStatuses.has(response.item.status)) {
        if (response.item.status === 'done') {
          await hydrateTranscriptsFromServer()
        }
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 3000))
    }
  }

  async function uploadLessonAsset(file: File): Promise<void> {
    assetUploading.value = true
    assetErrorMessage.value = ''
    try {
      const activeSession = await ensureSession()
      const response = await uploadSessionAsset(activeSession.session_id, file, backendBaseUrl.value)
      upsertAsset(response.item)
      void pollAssetStatus(response.item.asset_id)
    } catch (error) {
      assetErrorMessage.value = error instanceof Error ? error.message : '上传课堂素材失败。'
    } finally {
      assetUploading.value = false
    }
  }

  return {
    refreshSessionAssets,
    uploadLessonAsset,
  }
}
