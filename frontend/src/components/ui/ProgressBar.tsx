import { cn } from '@/lib/cn';

export type ProgressTone = 'ink' | 'brass' | 'caution';

const TONES: Record<ProgressTone, string> = {
  ink: 'bg-ink-700',
  brass: 'bg-brass-500',
  caution: 'bg-signal-caution',
};

interface ProgressBarProps {
  /** 0–1. Values outside the range are clamped. */
  value: number;
  tone?: ProgressTone;
  className?: string;
  label?: string;
}

export function ProgressBar({ value, tone = 'ink', className, label }: ProgressBarProps) {
  const percent = Math.round(Math.min(Math.max(value, 0), 1) * 100);

  return (
    <div
      className={cn('h-1.5 w-full overflow-hidden rounded-full bg-paper-300', className)}
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? 'Progress'}
    >
      <div
        className={cn('h-full rounded-full transition-[width] duration-500', TONES[tone])}
        style={{ width: `${percent}%` }}
      />
    </div>
  );
}
