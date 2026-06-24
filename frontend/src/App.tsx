import { useState, useEffect } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { query, checkHealth, QueryResponse } from './api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isHealthy, setIsHealthy] = useState(false)

  // Check health on mount
  useEffect(() => {
    const checkBackend = async () => {
      try {
        await checkHealth()
        setIsHealthy(true)
      } catch (error) {
        console.error('Backend health check failed:', error)
        setIsHealthy(false)
      }
    }

    checkBackend()
  }, [])

  const handleSendMessage = async (text: string) => {
    if (!isHealthy) {
      setMessages(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          role: 'assistant',
          content: 'Backend is not available. Please check that the server is running.',
        },
      ])
      return
    }

    // Add user message
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text,
    }
    setMessages(prev => [...prev, userMsg])

    setIsLoading(true)
    try {
      const response = await query(text)

      // Add assistant response
      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content:
          response.formatted_answer ||
          response.error ||
          `Query executed: ${response.operation}`,
        response,
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (error) {
      console.error('Query failed:', error)
      setMessages(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
        },
      ])
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="w-full h-screen flex items-center justify-center bg-gray-50 p-4">
      {!isHealthy && (
        <div className="fixed top-4 right-4 bg-red-50 border border-red-200 rounded-lg p-4 max-w-sm">
          <p className="text-red-700 font-semibold text-sm">⚠️ Backend Unavailable</p>
          <p className="text-red-600 text-xs mt-1">
            Please ensure the backend server is running on http://localhost:8000
          </p>
        </div>
      )}
      <div className="w-full max-w-2xl h-full">
        <ChatPanel
          messages={messages}
          isLoading={isLoading}
          onSendMessage={handleSendMessage}
        />
      </div>
    </div>
  )
}

export default App
