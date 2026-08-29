import { Loader2 } from 'lucide-react';

import { cn } from '@/lib/cn';

interface SpinnerProps {
  className?: string | undefined;
  label?: string | undefined;
}

export function Spinner({ className, label = 'Loading' }: SpinnerProps) {
  return (
    <Loader2
      className={cn('size-4 animate-spin', className)}
      strokeWidth={2}
      role="status"
      aria-label={label}
    />
  );
}

export function FullPageSpinner({ label }: { label?: string | undefined }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-3">
      <Spinner className="size-5 text-ink-400" label={label} />
      {label ? <p className="text-sm text-ink-500">{label}</p> : null}
    </div>
  );
}

/** Inline loading block for a section of a page. */
export function SectionSpinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-ink-500">
      <Spinner className="text-ink-400" label={label} />
      {label}
    </div>
  );
}
