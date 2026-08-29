import { Check, X } from 'lucide-react';

import { SourceLine } from '@/features/quiz/SourceLine';
import { GRADING_FAILED_STYLE, VERDICT_STYLES } from '@/features/quiz/verdict';
import { cn } from '@/lib/cn';
import type { AnswerResult } from '@/services/api/learning';

/**
 * What the student sees after submitting a written answer.
 *
 * Three states, kept visually distinct on purpose:
 *
 *   graded            a verdict, the rubric breakdown, and feedback
 *   graded uncertain  explicitly unmarked, with mastery untouched
 *   failed            the answer was saved but could not be marked
 *
 * The last two must never look like "wrong". A student penalised by a grader
 * outage, or by an answer nobody could judge, would have no way to tell.
 */
export function AnswerFeedback({ result }: { result: AnswerResult }) {
  const style =
    result.gradingFailed || result.verdict === null
      ? GRADING_FAILED_STYLE
      : VERDICT_STYLES[result.verdict];
  const Icon = style.icon;

  return (
    <div className={cn('rounded-card border px-4 py-3.5', style.border, style.background)}>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p className={cn('flex items-center gap-2 text-sm font-medium', style.text)}>
          <Icon className="size-4" strokeWidth={2.5} aria-hidden />
          {style.label}
        </p>
        <p className="text-xs text-ink-500">{style.note}</p>
      </div>

      {result.rubricResults.length > 0 ? (
        <ul className="mt-3 space-y-1.5">
          {result.rubricResults.map((row) => (
            <li key={row.concept} className="flex items-start gap-2 text-sm">
              {row.satisfied ? (
                <Check
                  className="mt-0.5 size-3.5 shrink-0 text-signal-success"
                  strokeWidth={2.5}
                  aria-hidden
                />
              ) : (
                <X
                  className="mt-0.5 size-3.5 shrink-0 text-ink-400"
                  strokeWidth={2.5}
                  aria-hidden
                />
              )}
              <span className={row.satisfied ? 'text-ink-700' : 'text-ink-500'}>
                {row.concept}
              </span>
            </li>
          ))}
        </ul>
      ) : null}

      {result.feedback ? (
        <p className="mt-3 text-sm leading-relaxed text-ink-700">{result.feedback}</p>
      ) : null}

      {result.referenceAnswer ? (
        <div className="mt-3 border-t border-paper-300/70 pt-3">
          <p className="text-xs font-medium tracking-wide text-ink-500 uppercase">
            Model answer
          </p>
          <p className="mt-1 text-sm leading-relaxed text-ink-700">
            {result.referenceAnswer}
          </p>
        </div>
      ) : null}

      <SourceLine source={result.source} />
    </div>
  );
}
