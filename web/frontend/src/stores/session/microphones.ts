import type { Ref } from 'vue'

import type { MicrophoneOption } from '../../types/study'

export function createMicrophoneActions(args: {
  microphone: Ref<string>
  microphones: Ref<MicrophoneOption[]>
  loadingMicrophones: Ref<boolean>
  errorMessage: Ref<string>
}) {
  const { microphone, microphones, loadingMicrophones, errorMessage } = args

  async function fetchMicrophones(): Promise<void> {
    loadingMicrophones.value = true
    try {
      if (!navigator.mediaDevices?.enumerateDevices) {
        microphones.value = [{ id: 'default', label: '当前浏览器不支持设备枚举' }]
        microphone.value = 'default'
        return
      }

      try {
        const permissionStream = await navigator.mediaDevices.getUserMedia({ audio: true })
        permissionStream.getTracks().forEach((track) => track.stop())
      } catch {
        // 即使没有拿到权限，也继续尝试列出设备。
      }

      const devices = await navigator.mediaDevices.enumerateDevices()
      const inputs = devices
        .filter((device) => device.kind === 'audioinput')
        .map((device, index) => ({
          id: device.deviceId || `microphone-${index + 1}`,
          label: device.label || `麦克风 ${index + 1}`,
        }))

      microphones.value = inputs.length > 0 ? inputs : [{ id: 'default', label: '默认麦克风' }]
      if (!microphones.value.some((item) => item.id === microphone.value)) {
        microphone.value = microphones.value[0]?.id || 'default'
      }
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '获取麦克风列表失败。'
    } finally {
      loadingMicrophones.value = false
    }
  }

  return {
    fetchMicrophones,
  }
}
