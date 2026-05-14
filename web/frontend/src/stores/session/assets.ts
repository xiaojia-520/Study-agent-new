import type { Ref } from 'vue'

import {
  fetchLessonAssets,
  fetchLessonAsset,
  uploadLessonAsset as uploadLessonAssetRequest,
} from '../../api/studyAgent'
import type { LessonAssetItem } from '../../types/study'

export function createLessonAssetActions(args: {
  backendBaseUrl: Ref<string>
  subject: Ref<string>
  recording: Ref<boolean>
  assetList: Ref<LessonAssetItem[]>
  assetUploading: Ref<boolean>
  assetErrorMessage: Ref<string>
}) {
  const {
    backendBaseUrl,
    subject,
    recording,
    assetList,
    assetUploading,
    assetErrorMessage,
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

  async function refreshLessonAssets(): Promise<void> {
    const response = await fetchLessonAssets(100, backendBaseUrl.value)
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
        return
      }
      await new Promise((resolve) => window.setTimeout(resolve, 3000))
    }
  }

  async function uploadLessonAsset(file: File): Promise<void> {
    if (recording.value) {
      assetErrorMessage.value = '录音中不能上传资料，请先停止录音。'
      return
    }

    assetUploading.value = true
    assetErrorMessage.value = ''
    try {
      const response = await uploadLessonAssetRequest(file, subject.value, backendBaseUrl.value)
      upsertAsset(response.item)
      void pollAssetStatus(response.item.asset_id)
    } catch (error) {
      assetErrorMessage.value = error instanceof Error ? error.message : '上传资料失败。'
    } finally {
      assetUploading.value = false
    }
  }

  return {
    refreshLessonAssets,
    uploadLessonAsset,
  }
}
