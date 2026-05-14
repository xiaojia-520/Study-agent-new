import { ref } from 'vue'
import { defineStore } from 'pinia'

import { querySession as querySessionRequest } from '../api/studyAgent'
import type {
  ChatMessage,
  QueryResponse,
  QueryResult,
  QueryScope,
  RetrievalResult,
} from '../types/study'
import { useSessionStore } from './session'

function buildWelcomeMessage(): ChatMessage {
  return {
    id: `assistant-welcome-${Date.now()}`,
    role: 'assistant',
    text: '已切换到课堂问答。先录音拿到课堂内容，再在这里直接提问。',
    createdAt: Date.now(),
  }
}

function mapQueryResultToRetrieval(result: QueryResult, index: number): RetrievalResult {
  return {
    id: `retrieval-${result.doc_id}-${index}`,
    title: result.subject || `检索片段 ${index + 1}`,
    snippet: result.content,
    source:
      result.source_kind && result.session_id
        ? `${result.source_kind} · ${result.session_id}`
        : result.source_kind || result.source_type || result.session_id || 'session retrieval',
    score: typeof result.score === 'number' ? result.score : null,
    docId: result.doc_id,
    sessionId: result.session_id,
    sourceType: result.source_type,
    sourceKind: result.source_kind,
    metadata: result.metadata,
  }
}

function buildAssistantAnswer(response: QueryResponse): string {
  if (response.answer && response.answer.trim()) {
    return response.answer.trim()
  }

  return '当前未返回 LLM 答案，请检查后端 LLM 配置。'
}

export const useRagChatStore = defineStore('ragChat', () => {
  const retrievalResults = ref<RetrievalResult[]>([])
  const chatMessages = ref<ChatMessage[]>([buildWelcomeMessage()])
  const currentQuestion = ref('')
  const sending = ref(false)
  const errorMessage = ref('')
  const queryScope = ref<QueryScope>('auto')
  const topK = ref(5)
  const includeRagContext = ref(false)
  const selectedAssetIds = ref<string[]>([])
  const lastResponse = ref<QueryResponse | null>(null)

  function resetForSession(): void {
    retrievalResults.value = []
    currentQuestion.value = ''
    sending.value = false
    errorMessage.value = ''
    includeRagContext.value = false
    lastResponse.value = null
    chatMessages.value = [buildWelcomeMessage()]
  }

  function toggleSelectedAsset(assetId: string): void {
    const cleanId = assetId.trim()
    if (!cleanId) {
      return
    }
    selectedAssetIds.value = selectedAssetIds.value.includes(cleanId)
      ? selectedAssetIds.value.filter((item) => item !== cleanId)
      : [...selectedAssetIds.value, cleanId]
  }

  async function runQuery(question: string): Promise<QueryResponse> {
    const sessionStore = useSessionStore()
    const sessionId = sessionStore.currentSessionId

    if (!sessionId) {
      throw new Error('请先开始录音，创建课堂会话后再提问。')
    }

    return querySessionRequest(
      sessionId,
      {
        query: question,
        scope: queryScope.value,
        top_k: topK.value,
        with_llm: true,
        include_rag_context: includeRagContext.value,
        asset_ids: selectedAssetIds.value,
      },
      sessionStore.backendBaseUrl,
    )
  }

  async function sendCurrentQuestion(): Promise<void> {
    const question = currentQuestion.value.trim()
    if (!question || sending.value) {
      return
    }

    const sessionStore = useSessionStore()
    if (!sessionStore.currentSessionId) {
      errorMessage.value = '请先开始录音，创建课堂会话后再提问。'
      chatMessages.value.push({
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        text: errorMessage.value,
        createdAt: Date.now(),
        error: true,
      })
      return
    }

    chatMessages.value.push({
      id: `user-${Date.now()}`,
      role: 'user',
      text: question,
      createdAt: Date.now(),
    })

    currentQuestion.value = ''
    sending.value = true
    errorMessage.value = ''

    try {
      const response = await runQuery(question)

      lastResponse.value = response
      retrievalResults.value = response.results.map(mapQueryResultToRetrieval)

      chatMessages.value.push({
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: buildAssistantAnswer(response),
        createdAt: Date.now(),
        relatedSources: retrievalResults.value.slice(0, 3).map((item) => item.docId),
      })
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : '查询课堂内容失败。'
      chatMessages.value.push({
        id: `assistant-error-${Date.now()}`,
        role: 'assistant',
        text: `查询失败：${errorMessage.value}`,
        createdAt: Date.now(),
        error: true,
      })
    } finally {
      sending.value = false
    }
  }

  return {
    chatMessages,
    currentQuestion,
    errorMessage,
    includeRagContext,
    lastResponse,
    queryScope,
    resetForSession,
    retrievalResults,
    selectedAssetIds,
    sendCurrentQuestion,
    sending,
    topK,
    toggleSelectedAsset,
  }
})
