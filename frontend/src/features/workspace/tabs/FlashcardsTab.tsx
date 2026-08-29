import {
  AlarmClock,
  ChevronLeft,
  ChevronRight,
  Layers,
  RotateCw,
  Sparkles,
  Target,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState, FormError } from '@/components/ui/ErrorState';
import { SectionSpinner, Spinner } from '@/components/ui/Spinner';
import { ReviewSession } from '@/features/flashcards/ReviewSession';
import { SourceLine } from '@/features/quiz/SourceLine';
import type { WorkspaceTab } from '@/features/workspace/workspaceTabs';
import {
  useFlashcards,
  useGenerateFlashcards,
  useTopics,
} from '@/hooks/queries/useLearning';
import { useDueSummary } from '@/hooks/queries/useRetention';
import { cn } from '@/lib/cn';
import { toErrorMessage } from '@/services/api/client';

interface FlashcardsTabProps {
  courseId: string;
  readyCount: number;
  onOpenTab: (tab: WorkspaceTab) => void;
}

export function FlashcardsTab({ courseId, readyCount, onOpenTab }: FlashcardsTabProps) {
  const topics = useTopics(courseId);
  const cards = useFlashcards(courseId);
  const generate = useGenerateFlashcards(courseId);

  const due = useDueSummary(courseId);

  const [topicFilter, setTopicFilter] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isReviewing, setIsReviewing] = useState(false);

  const visible = useMemo(
    () =>
      (cards.data ?? []).filter(
        (card) => topicFilter === null || card.topicId === topicFilter,
      ),
    [cards.data, topicFilter],
  );

  const card = visible[index];

  // The review queue is due-first. Never-reviewed cards count as due, so a freshly
  // generated set is immediately reviewable.
  const reviewQueue = useMemo(() => {
    const pool = cards.data ?? [];
    return topicFilter === null
      ? pool
      : pool.filter((item) => item.topicId === topicFilter);
  }, [cards.data, topicFilter]);

  const dueCount = due.data?.dueNow ?? 0;
  const overdueCount = due.data?.overdue ?? 0;

  async function handleGenerate(input: { topicIds?: string[]; weakTopicsOnly?: boolean }) {
    setError(null);
    try {
      await generate.mutateAsync(input);
      setIndex(0);
      setFlipped(false);
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  function move(delta: number) {
    setFlipped(false);
    setIndex((current) => {
      if (visible.length === 0) return 0;
      return (current + delta + visible.length) % visible.length;
    });
  }

  if (readyCount === 0) {
    return (
      <Card>
        <EmptyState
          icon={Layers}
          title="Upload and process course materials first"
          description="Flashcards are written from your own documents."
          action={<Button onClick={() => onOpenTab('materials')}>Go to Materials</Button>}
        />
      </Card>
    );
  }

  if (topics.isPending || cards.isPending) return <SectionSpinner label="Loading flashcards" />;

  if (cards.isError) {
    return (
      <Card>
        <ErrorState
          message={toErrorMessage(cards.error)}
          onRetry={() => void cards.refetch()}
        />
      </Card>
    );
  }

  if ((topics.data ?? []).length === 0) {
    return (
      <Card>
        <EmptyState
          icon={Target}
          title="Extract topics before generating flashcards"
          description="Cards are grouped by topic, so ANCHOR needs to know what your course covers."
          action={<Button onClick={() => onOpenTab('overview')}>Go to Overview</Button>}
        />
      </Card>
    );
  }

  if (isReviewing && reviewQueue.length > 0) {
    return (
      <ReviewSession
        courseId={courseId}
        queue={reviewQueue}
        onFinished={() => setIsReviewing(false)}
        onExit={() => setIsReviewing(false)}
      />
    );
  }

  return (
    <div className="space-y-6">
      {(cards.data ?? []).length > 0 ? (
        <Card>
          <CardBody>
            <div className="flex flex-wrap items-center gap-6">
              <DueStat label="Due today" value={dueCount} emphasis={dueCount > 0} />
              <DueStat label="Overdue" value={overdueCount} emphasis={overdueCount > 0} />
              <DueStat label="Upcoming" value={due.data?.upcoming ?? 0} />
              <Button
                className="ml-auto"
                disabled={reviewQueue.length === 0}
                onClick={() => setIsReviewing(true)}
              >
                <AlarmClock className="size-4" strokeWidth={2} aria-hidden />
                {dueCount > 0 ? `Review ${dueCount} due` : 'Review all'}
              </Button>
            </div>
            {dueCount === 0 && (cards.data ?? []).length > 0 ? (
              <p className="mt-3 text-sm text-ink-500">
                Nothing is due right now — your next cards come back in a few days.
                You can still review them all.
              </p>
            ) : null}
          </CardBody>
        </Card>
      ) : null}

      <Card>
        <CardBody className="space-y-4">
          {error ? <FormError message={error} /> : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={generate.isPending}
              onClick={() => void handleGenerate({ weakTopicsOnly: true })}
            >
              {generate.isPending ? <Spinner label="Generating" /> : (
                <Target className="size-4" strokeWidth={2} aria-hidden />
              )}
              Generate for weak topics
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={generate.isPending || topicFilter === null}
              onClick={() =>
                void handleGenerate({ topicIds: topicFilter ? [topicFilter] : [] })
              }
              title={
                topicFilter === null
                  ? 'Select a topic below first'
                  : 'Regenerate this topic'
              }
            >
              <Sparkles className="size-4" strokeWidth={2} aria-hidden />
              Generate for selected topic
            </Button>
          </div>

          <div className="flex flex-wrap gap-2">
            <FilterChip
              label="All topics"
              selected={topicFilter === null}
              onSelect={() => {
                setTopicFilter(null);
                setIndex(0);
                setFlipped(false);
              }}
            />
            {(topics.data ?? []).map((topic) => (
              <FilterChip
                key={topic.id}
                label={topic.name}
                selected={topicFilter === topic.id}
                onSelect={() => {
                  setTopicFilter(topic.id);
                  setIndex(0);
                  setFlipped(false);
                }}
              />
            ))}
          </div>
        </CardBody>
      </Card>

      {visible.length === 0 ? (
        <Card>
          <EmptyState
            icon={Layers}
            title="No flashcards yet"
            description="Generate a set above. Cards are saved, so opening this tab again costs nothing."
          />
        </Card>
      ) : card ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between text-sm text-ink-500">
            <Badge tone="neutral">{card.topicName}</Badge>
            <span className="tabular">
              {index + 1} of {visible.length}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setFlipped((current) => !current)}
            aria-label={flipped ? 'Show the prompt' : 'Reveal the answer'}
            className={cn(
              'flex min-h-56 w-full flex-col items-center justify-center rounded-card border px-8 py-10 text-center transition-colors',
              flipped
                ? 'border-ink-300 bg-white'
                : 'border-paper-300 bg-paper-50 hover:border-ink-300',
            )}
          >
            <span className="text-xs font-medium tracking-wide text-ink-400 uppercase">
              {flipped ? 'Answer' : 'Prompt'}
            </span>
            <span
              className={cn(
                'mt-4 leading-relaxed text-ink-900',
                flipped ? 'text-[15px]' : 'font-serif text-xl',
              )}
            >
              {flipped ? card.back : card.front}
            </span>
            {!flipped ? (
              <span className="mt-6 flex items-center gap-1.5 text-xs text-ink-400">
                <RotateCw className="size-3" strokeWidth={2} aria-hidden />
                Click to reveal
              </span>
            ) : null}
          </button>

          {/* The source is shown with the answer, where it can be checked. */}
          {flipped ? (
            <div className="rounded-card border border-paper-300 bg-white px-5 py-3">
              <SourceLine source={card.source} />
            </div>
          ) : null}

          <div className="flex items-center justify-between">
            <Button variant="secondary" size="sm" onClick={() => move(-1)}>
              <ChevronLeft className="size-4" strokeWidth={2} aria-hidden />
              Previous
            </Button>
            <Button variant="secondary" size="sm" onClick={() => move(1)}>
              Next
              <ChevronRight className="size-4" strokeWidth={2} aria-hidden />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function DueStat({
  label,
  value,
  emphasis = false,
}: {
  label: string;
  value: number;
  emphasis?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">{label}</p>
      <p
        className={cn(
          'tabular mt-1 font-serif text-2xl',
          emphasis ? 'text-ink-900' : 'text-ink-400',
        )}
      >
        {value}
      </p>
    </div>
  );
}

function FilterChip({
  label,
  selected,
  onSelect,
}: {
  label: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'rounded-full border px-3 py-1 text-sm transition-colors',
        selected
          ? 'border-ink-900 bg-ink-900 text-paper-50'
          : 'border-paper-400 text-ink-700 hover:border-ink-300',
      )}
    >
      {label}
    </button>
  );
}
