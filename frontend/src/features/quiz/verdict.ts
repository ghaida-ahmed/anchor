import { AlertCircle, Check, CircleHelp, CircleSlash, X } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type { AnswerVerdict } from '@/services/api/learning';

/**
 * How each verdict is presented.
 *
 * `uncertain` deliberately does not use the danger tone. The grader could not
 * judge the answer, which is a limitation of the marking, not a mistake by the
 * student — showing it in red would say the opposite of what happened.
 */
export interface VerdictStyle {
  label: string;
  /** One line explaining what the verdict means for the student's record. */
  note: string;
  icon: LucideIcon;
  text: string;
  border: string;
  background: string;
}

export const VERDICT_STYLES: Record<AnswerVerdict, VerdictStyle> = {
  correct: {
    label: 'Correct',
    note: 'Counts in full towards this topic.',
    icon: Check,
    text: 'text-signal-success',
    border: 'border-emerald-200',
    background: 'bg-emerald-50',
  },
  partially_correct: {
    label: 'Partly correct',
    note: 'Counts as half a mark, and moves this topic part of the way.',
    icon: CircleSlash,
    text: 'text-signal-caution',
    border: 'border-amber-200',
    background: 'bg-amber-50',
  },
  incorrect: {
    label: 'Not quite',
    note: 'Counts as incorrect for this topic.',
    icon: X,
    text: 'text-signal-danger',
    border: 'border-red-200',
    background: 'bg-red-50',
  },
  uncertain: {
    label: 'Not marked',
    note: 'Left unmarked, so it has not changed your mastery either way.',
    icon: CircleHelp,
    text: 'text-ink-600',
    border: 'border-paper-300',
    background: 'bg-paper-100',
  },
};

export const GRADING_FAILED_STYLE: VerdictStyle = {
  label: 'Could not be marked',
  note: 'Your answer was saved. Nothing has changed in your mastery.',
  icon: AlertCircle,
  text: 'text-ink-600',
  border: 'border-paper-300',
  background: 'bg-paper-100',
};
