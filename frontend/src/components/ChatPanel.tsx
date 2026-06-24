import { useEffect, useRef } from 'react'
import { MessageBubble } from './MessageBubble'
import { QueryResponse } from '../api'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
}

interface ChatPanelProps {
  messages: Message[]
  isLoading: boolean
  onSendMessage: (message: string) => Promise<void>
}

export function ChatPanel({ messages, isLoading, onSendMessage }: ChatPanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const input = inputRef.current
    if (!input || !input.value.trim()) return

    const message = input.value.trim()
    input.value = ''

    try {
      await onSendMessage(message)
    } catch (error) {
      console.error('Failed to send message:', error)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-lg">
      {/* Header */}
      <div className="border-b border-gray-200 p-4">
        <h1 className="text-2xl font-bold text-gray-900">NL Query Layer</h1>
        <p className="text-sm text-gray-600 mt-1">Ask questions about Olist orders</p>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full text-gray-400">
            <div className="text-center">
              <div className="text-4xl mb-2">💬</div>
              <p>Ask a question to get started</p>
              <p className="text-sm mt-2">Examples:</p>
              <p className="text-sm italic">"How many delivered orders in São Paulo?"</p>
              <p className="text-sm italic">"What is the status of order abc123?"</p>
            </div>
          </div>
        ) : (
          <>
            {messages.map(msg => (
              <MessageBubble
                key={msg.id}
                role={msg.role}
                content={msg.content}
                response={msg.response}
              />
            ))}
            {isLoading && (
              <div className="flex justify-start">
                <div className="bg-gray-100 text-gray-900 rounded-3xl rounded-tl-none px-4 py-2">
                  <div className="flex space-x-2">
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100"></div>
                    <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200"></div>
                  </div>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-gray-200 p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <input
            ref={inputRef}
            type="text"
            placeholder="Ask a question..."
            disabled={isLoading}
            className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-50 disabled:text-gray-500"
          />
          <button
            type="submit"
            disabled={isLoading}
            className="px-6 py-2 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? (
              <span className="inline-flex items-center">
                <span className="animate-spin mr-2">⏳</span>
              </span>
            ) : (
              'Send'
            )}
          </button>
        </form>
      </div>
    </div>
  )
}
