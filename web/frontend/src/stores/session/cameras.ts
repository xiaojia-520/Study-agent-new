import type { Ref } from 'vue'

import type { CameraOption } from '../../types/study'

export function createCameraActions(args: {
  camera: Ref<string>
  cameras: Ref<CameraOption[]>
  loadingCameras: Ref<boolean>
  errorMessage: Ref<string>
}) {
  const { camera, cameras, loadingCameras, errorMessage } = args

  async function fetchCameras(): Promise<void> {
    loadingCameras.value = true
    try {
      if (!navigator.mediaDevices?.enumerateDevices) {
        cameras.value = [{ id: 'default', label: '当前浏览器不支持设备枚举' }]
        camera.value = 'default'
        return
      }

      try {
        const permissionStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false })
        permissionStream.getTracks().forEach((track) => track.stop())
      } catch {
        // 即使没有权限，也继续尝试列出设备。
      }

      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs = devices
        .filter((device) => device.kind === 'videoinput')
        .map((device, index) => ({
          id: device.deviceId || `camera-${index + 1}`,
          label: device.label || `摄像头 ${index + 1}`,
        }))

      cameras.value = inputs.length > 0 ? inputs : [{ id: 'default', label: '默认摄像头' }]
      if (!cameras.value.some((item) => item.id === camera.value)) {
        camera.value = cameras.value[0]?.id || 'default'
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '获取摄像头列表失败。'
    } finally {
      loadingCameras.value = false
    }
  }

  return {
    fetchCameras,
  }
}
