import type { MasteryBand } from '@/services/api/learning';

/** Badge tone per mastery band. */
export const BAND_BADGE_TONE: Record<
  MasteryBand,
  'neutral' | 'danger' | 'caution' | 'success'
> = {
  not_started: 'neutral',
  needs_practice: 'danger',
  developing: 'caution',
  strong: 'success',
};

/** Progress-bar fill per mastery band. */
export const BAND_BAR_TONE: Record<MasteryBand, string> = {
  not_started: 'bg-paper-400',
  needs_practice: 'bg-signal-danger',
  developing: 'bg-signal-caution',
  strong: 'bg-signal-success',
};
