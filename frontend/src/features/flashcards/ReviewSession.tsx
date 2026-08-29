import { Check, ChevronsRight, RotateCw } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { FormError } from '@/components/ui/ErrorState';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { Spinner } from '@/components/ui/Spinner';
import { SourceLine } from '@/features/quiz/SourceLine';
import { useSubmitReview } from '@/hooks/queries/useRetention';
import { cn } from '@/lib/cn';
import { toErrorMessage } from '@/services/api/client';
import type { Flashcard } from '@/services/api/learning';
import type { ReviewRating } from '@/services/api/retention';

const RATINGS: ReadonlyArray<{
  rating: ReviewRating;
  label: string;
  hint: string;
  tone: string;
}> = [
  {
    rating: 'again',
    label: 'Again',
    hint: 'Forgot it',
    tone: 'border-red-300 text-signal-danger hover:bg-red-50',
  },
  {
    rating: 'hard',
    label: 'Hard',
    hint: 'Struggled',
    tone: 'border-amber-300 text-signal-caution hover:bg-amber-50',
  },
  {
    rating: 'good',
    label: 'Good',
    hint: 'Recalled it',
    tone: 'border-paper-400 text-ink-700 hover:bg-paper-100',
  },
  {
    rating: 'easy',
    label: 'Easy',
    hint: 'Instant',
    tone: 'border-emerald-300 text-signal-success hover:bg-emerald-50',
  },
];

interface ReviewSessionProps {
  courseId: string;
  queue: Flashcard[];
  onFinished: () => void;
  onExit: () => void;
}

/**
 * Works through a queue of due cards.
 *
 * The rating is the student's own judgement — nothing here asks a model whether
 * they remembered, which would be both slower and less accurate than the person who
 * just tried.
 */
export function ReviewSession({
  courseId,
  queue,
  onFinished,
  onExit,
}: ReviewSessionProps) {
  const submitReview = useSubmitReview(courseId);

  const [index, setIndex] = useState(0);
  const [revealed, setRevealed] = useState(false);
  const [lastLabel, setLastLabel] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const card = queue[index];
  const isLast = index === queue.length - 1;

  async function rate(rating: ReviewRating) {
    if (!card) return;
    setError(null);
    try {
      const result = await submitReview.mutateAsync({ flashcardId: card.id, rating });
      setLastLabel(result.nextReviewLabel);

      if (isLast) {
        onFinished();
        return;
      }
      setIndex((current) => current + 1);
      setRevealed(false);
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  if (!card) return null;

  return (
    <div className="space-y-4">
      <div>
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="tabular text-ink-500">
            Card {index + 1} of {queue.length}
          </span>
          <button
            type="button"
            onClick={onExit}
            className="text-ink-400 transition-colors hover:text-ink-800"
          >
            End session
          </button>
        </div>
        <ProgressBar value={index / queue.length} label="Review progress" />
      </div>

      {error ? <FormError message={error} /> : null}

      {lastLabel ? (
        <p className="flex items-center gap-1.5 rounded-lg border border-paper-300 bg-paper-50 px-3 py-2 text-xs text-ink-500">
          <Check className="size-3.5 text-signal-success" strokeWidth={2.5} aria-hidden />
          Last card scheduled {lastLabel}.
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        <Badge tone="neutral">{card.topicName}</Badge>
      </div>

      <button
        type="button"
        onClick={() => setRevealed(true)}
        disabled={revealed}
        aria-label={revealed ? 'Answer shown' : 'Reveal the answer'}
        className={cn(
          'flex min-h-52 w-full flex-col items-center justify-center rounded-card border px-8 py-10 text-center transition-colors',
          revealed
            ? 'cursor-default border-ink-300 bg-white'
            : 'border-paper-300 bg-paper-50 hover:border-ink-300',
        )}
      >
        <span className="text-xs font-medium tracking-wide text-ink-400 uppercase">
          {revealed ? 'Answer' : 'Prompt'}
        </span>
        <span
          className={cn(
            'mt-4 leading-relaxed text-ink-900',
            revealed ? 'text-[15px]' : 'font-serif text-xl',
          )}
        >
          {revealed ? card.back : card.front}
        </span>
        {!revealed ? (
          <span className="mt-6 flex items-center gap-1.5 text-xs text-ink-400">
            <RotateCw className="size-3" strokeWidth={2} aria-hidden />
            Click to reveal
          </span>
        ) : null}
      </button>

      {revealed ? (
        <>
          <Card>
            <CardBody className="py-3">
              <SourceLine source={card.source} />
            </CardBody>
          </Card>

          <div>
            <p className="mb-2 text-sm text-ink-500">How well did you recall it?</p>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {RATINGS.map((option) => (
                <button
                  key={option.rating}
                  type="button"
                  disabled={submitReview.isPending}
                  onClick={() => void rate(option.rating)}
                  className={cn(
                    'flex flex-col items-center rounded-lg border px-3 py-3 transition-colors disabled:opacity-50',
                    option.tone,
                  )}
                >
                  <span className="text-sm font-medium">{option.label}</span>
                  <span className="mt-0.5 text-xs text-ink-400">{option.hint}</span>
                </button>
              ))}
            </div>
            {submitReview.isPending ? (
              <p className="mt-2 flex items-center gap-2 text-xs text-ink-400">
                <Spinner className="size-3" label="Saving" />
                Scheduling the next review…
              </p>
            ) : null}
          </div>
        </>
      ) : (
        <Button variant="secondary" onClick={() => setRevealed(true)} className="w-full">
          Reveal answer
          <ChevronsRight className="size-4" strokeWidth={2} aria-hidden />
        </Button>
      )}
    </div>
  );
}
