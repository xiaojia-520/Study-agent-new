import type { RealtimeEvent, WebSocketState } from '../types/study'

import { buildWebSocketUrl, defaultBackendBaseUrl } from './studyAgent'

export interface RealtimeSocketClientOptions {
  onEvent: (payload: RealtimeEvent) => void
  onStateChange: (state: WebSocketState) => void
  onError: (message: string) => void
}

export class RealtimeSocketClient {
  private websocket: WebSocket | null = null
  private connectPromise: Promise<void> | null = null

  constructor(private readonly options: RealtimeSocketClientOptions) {}

  get isOpen(): boolean {
    return this.websocket?.readyState === WebSocket.OPEN
  }

  async connect(sessionId: string, baseUrl = defaultBackendBaseUrl): Promise<void> {
    if (this.websocket?.readyState === WebSocket.OPEN) {
      return
    }
    if (this.connectPromise) {
      return this.connectPromise
    }

    this.options.onStateChange('connecting')
    const currentSocket = new WebSocket(buildWebSocketUrl(sessionId, baseUrl))
    this.websocket = currentSocket

    this.connectPromise = new Promise<void>((resolve, reject) => {
      let handshakeCompleted = false

      currentSocket.onopen = () => {
        handshakeCompleted = true
        this.options.onStateChange('open')
        this.connectPromise = null
        resolve()
      }

      currentSocket.onmessage = (message) => {
        if (typeof message.data !== 'string') {
          return
        }

        try {
          this.options.onEvent(JSON.parse(message.data) as RealtimeEvent)
        } catch {
          // Ignore non-JSON messages from the backend.
        }
      }

      currentSocket.onerror = () => {
        this.options.onError('WebSocket connection failed.')
        if (!handshakeCompleted) {
          this.options.onStateChange('closed')
          this.websocket = null
          this.connectPromise = null
          reject(new Error('WebSocket connection failed.'))
        }
      }

      currentSocket.onclose = (event) => {
        if (this.websocket === currentSocket) {
          this.websocket = null
        }
        this.options.onStateChange('closed')
        this.connectPromise = null
        if (!handshakeCompleted) {
          reject(new Error(event.reason || 'WebSocket closed.'))
        }
      }
    })

    return this.connectPromise
  }

  async disconnect(): Promise<void> {
    if (this.websocket) {
      const currentSocket = this.websocket
      this.websocket = null
      this.connectPromise = null

      if (
        currentSocket.readyState === WebSocket.CONNECTING ||
        currentSocket.readyState === WebSocket.OPEN
      ) {
        currentSocket.close(1000, 'client disconnect')
      }
    }

    this.options.onStateChange('closed')
  }

  sendAudio(audioBuffer: ArrayBufferLike): void {
    if (!this.isOpen || !this.websocket) {
      return
    }
    this.websocket.send(audioBuffer)
  }
}
