import { ClarifyBlock } from '../api'

/**
 * Renders the backend's fail-closed clarification: when a follow-up can't be
 * safely resolved (e.g. the inherited operation can't filter by the place the
 * user named), the backend returns options instead of a number. Each option is
 * a quick-reply chip that resubmits a disambiguated question in the same
 * session. This is the UI half of "decline honestly beats a confident proxy".
 */
export function ClarifyPrompt({
  clarify,
  disabled,
  onPick,
}: {
  clarify: ClarifyBlock
  disabled: boolean
  onPick: (option: string) => void
}) {
  if (!clarify.options || clarify.options.length === 0) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {clarify.options.map(opt => (
        <button
          key={opt}
          type="button"
          onClick={() => onPick(opt)}
          disabled={disabled}
          className="rounded-full border border-amber-200 bg-amber-50 px-3 py-1 text-xs font-medium text-amber-800 transition hover:border-amber-300 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {opt}
        </button>
      ))}
    </div>
  )
}
