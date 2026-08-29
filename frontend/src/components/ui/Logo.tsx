import { cn } from '@/lib/cn';

interface LogoProps {
  className?: string;
  /** Renders the wordmark next to the anchor glyph. */
  withWordmark?: boolean;
}

export function Logo({ className, withWordmark = true }: LogoProps) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <svg viewBox="0 0 32 32" className="size-7 shrink-0" fill="none" aria-hidden>
        <rect width="32" height="32" rx="7" className="fill-ink-900" />
        <path
          d="M16 8.5v15M16 8.5a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM11 12h10M8 17.5a8 8 0 0 0 16 0"
          className="stroke-brass-400"
          strokeWidth={1.9}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {withWordmark ? (
        <span className="text-[15px] font-semibold tracking-[0.18em] text-ink-900">
          ANCHOR
        </span>
      ) : null}
    </span>
  );
}
