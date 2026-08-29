import { useApiHealth } from '@/hooks/useApiHealth';
import { cn } from '@/lib/cn';

const LABELS: Record<ReturnType<typeof useApiHealth>, string> = {
  checking: 'Checking API…',
  online: 'API connected',
  unreachable: 'API offline',
};

const DOTS: Record<ReturnType<typeof useApiHealth>, string> = {
  checking: 'bg-ink-300',
  online: 'bg-signal-success',
  unreachable: 'bg-signal-danger',
};

/**
 * Live read of `GET /api/health`, so a backend that is not running is obvious
 * rather than showing up as a page of failed requests.
 */
export function ApiStatusIndicator() {
  const status = useApiHealth();

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-ink-500">
      <span className={cn('size-1.5 rounded-full', DOTS[status])} aria-hidden />
      {LABELS[status]}
    </div>
  );
}
