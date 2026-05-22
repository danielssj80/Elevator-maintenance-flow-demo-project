interface Props {
  inScope: boolean
}

export default function ScopeTag({ inScope }: Props) {
  if (inScope) return null
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-500 border border-gray-200">
      Out of scope
    </span>
  )
}
