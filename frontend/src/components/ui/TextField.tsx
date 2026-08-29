import { useId, type InputHTMLAttributes } from 'react';

import { cn } from '@/lib/cn';

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  hint?: string;
  error?: string;
}

export function TextField({ label, hint, error, className, ...props }: TextFieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;

  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-sm font-medium text-ink-800">
        {label}
      </label>
      <input
        id={id}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy}
        className={cn(
          'h-10 w-full rounded-lg border bg-white px-3 text-sm text-ink-900 transition-colors',
          'placeholder:text-ink-300 focus:outline-none focus-visible:border-ink-500',
          'disabled:cursor-not-allowed disabled:bg-paper-100',
          error ? 'border-red-300' : 'border-paper-400 hover:border-ink-300',
        )}
        {...props}
      />
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-xs text-signal-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-xs text-ink-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

interface TextAreaFieldProps {
  label: string;
  hint?: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  maxLength?: number;
  placeholder?: string;
  disabled?: boolean;
}

export function TextAreaField({
  label,
  hint,
  value,
  onChange,
  rows = 3,
  maxLength,
  placeholder,
  disabled,
}: TextAreaFieldProps) {
  const id = useId();

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-ink-800">
        {label}
      </label>
      <textarea
        id={id}
        value={value}
        rows={rows}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className={cn(
          'w-full resize-y rounded-lg border border-paper-400 bg-white px-3 py-2 text-sm text-ink-900',
          'placeholder:text-ink-300 transition-colors hover:border-ink-300',
          'focus:outline-none focus-visible:border-ink-500 disabled:cursor-not-allowed disabled:bg-paper-100',
        )}
      />
      {hint ? (
        <p id={`${id}-hint`} className="text-xs text-ink-400">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
