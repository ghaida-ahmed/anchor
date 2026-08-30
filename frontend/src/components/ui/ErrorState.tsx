import { AlertTriangle, RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/Button';

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

/** Shows the API's own message — never a stack trace or a raw status code. */
export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="flex size-11 items-center justify-center rounded-full bg-red-50">
        <AlertTriangle className="size-5 text-signal-danger" strokeWidth={1.75} aria-hidden />
      </div>
      <h2 className="mt-4 font-serif text-lg text-ink-900">{title}</h2>
      <p className="mt-1 max-w-sm text-sm text-ink-500">{message}</p>
      {onRetry ? (
        <Button variant="secondary" size="sm" className="mt-5" onClick={onRetry}>
          <RefreshCw className="size-3.5" strokeWidth={2} aria-hidden />
          Try again
        </Button>
      ) : null}
    </div>
  );
}

/** Compact inline variant for forms and dialogs. */
export function FormError({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-signal-danger"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" strokeWidth={2} aria-hidden />
      {message}
    </p>
  );
}
