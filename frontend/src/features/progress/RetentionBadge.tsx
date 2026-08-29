import { Badge } from '@/components/ui/Badge';
import type { RetentionStatus } from '@/services/api/retention';

const TONES: Record<RetentionStatus, 'neutral' | 'success' | 'caution' | 'danger'> = {
  new: 'neutral',
  fresh: 'success',
  review_soon: 'caution',
  due: 'caution',
  overdue: 'danger',
};

/**
 * Review timing, shown alongside — not instead of — the mastery band.
 *
 * "Strong" and "Due" are both true of a well-known topic left for a month, and
 * collapsing them into one badge would either hide the review or imply the student
 * had got worse.
 */
export function RetentionBadge({
  status,
  label,
}: {
  status: RetentionStatus;
  label: string;
}) {
  // Fresh and new need no badge: the absence of one already means "nothing to do".
  if (status === 'fresh' || status === 'new') return null;

  return <Badge tone={TONES[status]}>{label}</Badge>;
}
