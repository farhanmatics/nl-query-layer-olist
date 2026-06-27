import { useState, useEffect } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { query, checkHealth, QueryResponse } from './api'

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
  at: number
}

type Health = 'checking' | 'online' | 'offline'

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [health, setHealth] = useState<Health>('checking')

  // Poll backend health on mount and periodically so the status pill stays live.
  useEffect(() => {
    let active = true
    const ping = async () => {
      try {
        const h = await checkHealth()
        if (active) setHealth(h?.db === 'ok' && h?.llm === 'ok' ? 'online' : 'offline')
      } catch {
        if (active) setHealth('offline')
      }
    }
    ping()
    const id = setInterval(ping, 15000)
    return () => {
      active = false
      clearInterval(id)
    }
  }, [])

  const handleSendMessage = async (text: string) => {
    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: text,
      at: Date.now(),
    }
    setMessages(prev => [...prev, userMsg])
    setIsLoading(true)

    try {
      const response = await query(text)
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content:
            response.formatted_answer ||
            response.error ||
            `Query executed: ${response.operation}`,
          response,
          at: Date.now(),
        },
      ])
    } catch (error) {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: `Couldn't reach the backend: ${
            error instanceof Error ? error.message : 'unknown error'
          }`,
          at: Date.now(),
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="h-full w-full bg-gradient-to-b from-slate-100 to-slate-200/60 text-slate-900">
      <div className="mx-auto flex h-full max-w-3xl flex-col px-4">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          health={health}
          onSendMessage={handleSendMessage}
        />
      </div>
    </div>
  )
}

export default App
