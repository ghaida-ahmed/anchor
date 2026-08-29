import { Badge } from '@/components/ui/Badge';
import { BAND_BADGE_TONE } from '@/features/quiz/masteryTone';
import type { MasteryBand } from '@/services/api/learning';

export function MasteryBadge({ band, label }: { band: MasteryBand; label: string }) {
  return <Badge tone={BAND_BADGE_TONE[band]}>{label}</Badge>;
}
