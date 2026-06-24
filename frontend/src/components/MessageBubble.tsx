import { QueryResponse } from '../api'
import { ResultCard } from './ResultCard'

interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  response?: QueryResponse
}

export function MessageBubble({ role, content, response }: MessageBubbleProps) {
  const isUser = role === 'user'

  if (isUser) {
    return (
      <div className="flex justify-end mb-4">
        <div className="max-w-md bg-blue-600 text-white rounded-3xl rounded-tr-none px-4 py-2">
          <p className="text-sm">{content}</p>
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="mb-4">
      <div className="flex justify-start mb-2">
        <div className="max-w-md bg-gray-100 text-gray-900 rounded-3xl rounded-tl-none px-4 py-2">
          <p className="text-sm">{content}</p>
        </div>
      </div>
      {response && <ResultCard response={response} />}
    </div>
  )
}
