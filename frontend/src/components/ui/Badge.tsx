import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

type BadgeTone = 'neutral' | 'brass' | 'success' | 'caution' | 'danger';

const TONES: Record<BadgeTone, string> = {
  neutral: 'bg-paper-200 text-ink-600 ring-paper-400',
  brass: 'bg-brass-100 text-brass-600 ring-brass-200',
  success: 'bg-emerald-50 text-signal-success ring-emerald-200',
  caution: 'bg-amber-50 text-signal-caution ring-amber-200',
  danger: 'bg-red-50 text-signal-danger ring-red-200',
};

interface BadgeProps {
  tone?: BadgeTone;
  className?: string;
  children: ReactNode;
}

export function Badge({ tone = 'neutral', className, children }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
