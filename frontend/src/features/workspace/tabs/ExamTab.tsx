import { CalendarClock, Info, Target } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState, FormError } from '@/components/ui/ErrorState';
import { SectionSpinner, Spinner } from '@/components/ui/Spinner';
import { StatTile } from '@/components/ui/StatTile';
import type { WorkspaceTab } from '@/features/workspace/workspaceTabs';
import { useGenerateQuiz, useTopics } from '@/hooks/queries/useLearning';
import { useExamStatus, useSetExamDate } from '@/hooks/queries/useRetention';
import { cn } from '@/lib/cn';
import { toErrorMessage } from '@/services/api/client';

interface ExamTabProps {
  courseId: string;
  onOpenTab: (tab: WorkspaceTab) => void;
}

export function ExamTab({ courseId, onOpenTab }: ExamTabProps) {
  const exam = useExamStatus(courseId);
  const setExamDate = useSetExamDate(courseId);
  const topics = useTopics(courseId);
  const generateQuiz = useGenerateQuiz(courseId);

  const [draftDate, setDraftDate] = useState('');
  const [error, setError] = useState<string | null>(null);

  async function save(value: string | null) {
    setError(null);
    try {
      await setExamDate.mutateAsync(value);
      setDraftDate('');
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  async function startExamQuiz() {
    setError(null);
    try {
      await generateQuiz.mutateAsync({ mode: 'exam', questionCount: 8 });
      onOpenTab('quizzes');
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  if (exam.isPending) return <SectionSpinner label="Loading exam preparation" />;

  if (exam.isError || !exam.data) {
    return (
      <Card>
        <ErrorState
          message={toErrorMessage(exam.error)}
          onRetry={() => void exam.refetch()}
        />
      </Card>
    );
  }

  const status = exam.data;
  const hasTopics = (topics.data ?? []).length > 0;

  if (!status.examDate) {
    return (
      <div className="space-y-6">
        {error ? <FormError message={error} /> : null}
        <Card>
          <EmptyState
            icon={CalendarClock}
            title="Set an exam date to get a preparation plan"
            description="ANCHOR will work out what to prioritise from your mastery and review history. Exam dates are optional — courses without one work exactly as before."
            action={
              <div className="flex items-center gap-2">
                <input
                  type="date"
                  value={draftDate}
                  onChange={(event) => setDraftDate(event.target.value)}
                  aria-label="Exam date"
                  className="h-10 rounded-lg border border-paper-400 bg-white px-3 text-sm text-ink-900 focus:outline-none focus-visible:border-ink-500"
                />
                <Button
                  disabled={!draftDate || setExamDate.isPending}
                  onClick={() => void save(draftDate)}
                >
                  {setExamDate.isPending ? <Spinner label="Saving" /> : null}
                  Set date
                </Button>
              </div>
            }
          />
        </Card>
      </div>
    );
  }

  const readiness = status.readiness;
  const daysLabel = describeDays(status.daysRemaining, status.hasPassed);

  return (
    <div className="space-y-6">
      {error ? <FormError message={error} /> : null}

      {status.hasPassed ? (
        <p className="rounded-lg border border-paper-300 bg-paper-50 px-4 py-3 text-sm text-ink-500">
          This exam date has passed. Practice still works normally — set a new date if
          you have another exam coming up.
        </p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Exam Readiness"
          value={`${readiness.readiness.toFixed(0)}%`}
          hint="An indicator, not a predicted grade"
        />
        <StatTile label="Exam date" value={formatDate(status.examDate)} hint={daysLabel} />
        <StatTile
          label="Coverage"
          value={`${Math.round(readiness.coverage * 100)}%`}
          hint={`${readiness.topicsStarted} of ${readiness.topicsTotal} topics started`}
        />
        <StatTile
          label="Overdue reviews"
          value={String(readiness.overdueCards)}
          hint={
            readiness.totalCards > 0
              ? `of ${readiness.totalCards} cards`
              : 'No flashcards yet'
          }
        />
      </div>

      <p className="flex items-start gap-2 rounded-lg border border-paper-300 bg-paper-50 px-4 py-3 text-sm text-ink-500">
        <Info className="mt-0.5 size-3.5 shrink-0 text-ink-400" strokeWidth={2} aria-hidden />
        <span>
          <span className="font-medium text-ink-700">Exam Readiness</span> combines
          your estimated mastery, how much of the course you have covered, and how
          many reviews are overdue. It reflects your practice record — it does not
          predict your result.
        </span>
      </p>

      <Card>
        <CardHeader
          title="What to focus on"
          description="Chosen from your mastery record, weighted for coverage."
        />
        <CardBody className="space-y-4">
          {status.topicsNeedingAttention.length > 0 ? (
            <ul className="flex flex-wrap gap-2">
              {status.topicsNeedingAttention.map((name) => (
                <li key={name}>
                  <Badge tone="caution">{name}</Badge>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-ink-500">
              Nothing is standing out — keep practising to build more evidence.
            </p>
          )}

          <Button
            disabled={!hasTopics || generateQuiz.isPending}
            onClick={() => void startExamQuiz()}
            title={hasTopics ? undefined : 'Extract topics first'}
          >
            {generateQuiz.isPending ? <Spinner label="Generating" /> : (
              <Target className="size-4" strokeWidth={2} aria-hidden />
            )}
            Start exam prep quiz
          </Button>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Exam date" description="Change or remove it at any time." />
        <CardBody>
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="date"
              value={draftDate || status.examDate}
              onChange={(event) => setDraftDate(event.target.value)}
              aria-label="Exam date"
              className="h-10 rounded-lg border border-paper-400 bg-white px-3 text-sm text-ink-900 focus:outline-none focus-visible:border-ink-500"
            />
            <Button
              variant="secondary"
              disabled={setExamDate.isPending || !draftDate}
              onClick={() => void save(draftDate)}
            >
              Update
            </Button>
            <button
              type="button"
              disabled={setExamDate.isPending}
              onClick={() => void save(null)}
              className={cn(
                'text-sm text-ink-400 transition-colors hover:text-signal-danger',
                setExamDate.isPending && 'opacity-50',
              )}
            >
              Remove exam date
            </button>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

function describeDays(days: number | null, hasPassed: boolean): string {
  if (days === null) return '';
  if (hasPassed) return `${Math.abs(days)} days ago`;
  if (days === 0) return 'Today';
  if (days === 1) return 'Tomorrow';
  return `${days} days away`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(`${value}T00:00:00Z`));
}
