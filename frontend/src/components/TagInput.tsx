import { useState, useCallback } from 'react'
import type { FC } from 'react'

const SUGGESTED_TAGS = [
  'И26',
  'И9',
  'И15',
  'MPRS',
  'MNPR',
  'PRH2',
  'БАГ',
  'ТЕХДОЛГ',
  'СРОЧНО',
]

interface TagInputProps {
  tags: string[]
  onChange: (tags: string[]) => void
  placeholder?: string
  className?: string
}

export const TagInput: FC<TagInputProps> = ({
  tags,
  onChange,
  placeholder = 'Введите тег и нажмите Enter',
  className = '',
}) => {
  const [inputValue, setInputValue] = useState('')

  const handleAddTag = useCallback(
    (tag: string) => {
      const normalized = tag.trim().toUpperCase()
      if (normalized && !tags.includes(normalized)) {
        onChange([...tags, normalized])
      }
      setInputValue('')
    },
    [tags, onChange]
  )

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleAddTag(inputValue)
    }
  }

  const removeTag = (tagToRemove: string) => {
    onChange(tags.filter((t) => t !== tagToRemove))
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-700"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(tag)}
              className="ml-1 rounded-full p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600"
              aria-label={`Удалить тег ${tag}`}
            >
              ✕
            </button>
          </span>
        ))}
        <div className="flex flex-wrap items-center gap-1">
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            className="rounded border border-slate-300 px-2 py-1 text-sm w-32"
          />
          <button
            type="button"
            onClick={() => handleAddTag(inputValue)}
            className="rounded bg-slate-100 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
          >
            + добавить
          </button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {SUGGESTED_TAGS.filter((t) => !tags.includes(t)).map((tag) => (
          <button
            key={tag}
            type="button"
            onClick={() => handleAddTag(tag)}
            className="rounded-full bg-slate-50 px-2.5 py-0.5 text-xs font-medium text-slate-600 hover:bg-slate-200"
          >
            {tag}
          </button>
        ))}
      </div>
    </div>
  )
}
