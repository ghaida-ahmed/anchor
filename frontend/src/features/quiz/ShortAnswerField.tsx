import { useId } from 'react';

import { cn } from '@/lib/cn';

/** Mirrors MAX_RESPONSE_CHARS in backend/app/schemas/learning.py. */
export const MAX_RESPONSE_CHARS = 2000;

interface ShortAnswerFieldProps {
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}

/**
 * The written-answer input.
 *
 * Nothing here inspects or scores what is typed. The answer is sent verbatim and
 * marked on the server, where the grading pipeline can treat it as the untrusted
 * input it is.
 */
export function ShortAnswerField({ value, onChange, disabled }: ShortAnswerFieldProps) {
  const id = useId();
  const remaining = MAX_RESPONSE_CHARS - value.length;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium text-ink-700">
        Your answer
      </label>
      <textarea
        id={id}
        rows={5}
        value={value}
        disabled={disabled}
        maxLength={MAX_RESPONSE_CHARS}
        onChange={(event) => onChange(event.target.value)}
        placeholder="Answer in your own words — two or three sentences is plenty."
        className={cn(
          'w-full resize-y rounded-lg border px-3.5 py-3 text-sm leading-relaxed text-ink-900',
          'placeholder:text-ink-400 focus:outline-none focus:ring-2 focus:ring-ink-900/10',
          disabled
            ? 'cursor-default border-paper-300 bg-paper-100'
            : 'border-paper-400 bg-paper-50 focus:border-ink-500',
        )}
      />
      <p className="tabular text-right text-xs text-ink-400">
        {remaining < 200 ? `${remaining} characters left` : `${value.length} characters`}
      </p>
    </div>
  );
}
