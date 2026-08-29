import { FileQuestion, FileText, Layers, MessagesSquare, Sparkles, Target } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { FormError } from '@/components/ui/ErrorState';
import { SectionSpinner, Spinner } from '@/components/ui/Spinner';
import { RecommendationList } from '@/features/progress/RecommendationList';
import type { WorkspaceTab } from '@/features/workspace/workspaceTabs';
import { useExtractTopics, useRecommendations, useTopics } from '@/hooks/queries/useLearning';
import { useDueSummary, useMastery } from '@/hooks/queries/useRetention';
import { toErrorMessage } from '@/services/api/client';

interface OverviewTabProps {
  courseId: string;
  documentCount: number;
  readyCount: number;
  onOpenTab: (tab: WorkspaceTab) => void;
}

const QUICK_ACTIONS: ReadonlyArray<{
  tab: WorkspaceTab;
  icon: typeof Sparkles;
  title: string;
  body: string;
}> = [
  {
    tab: 'materials',
    icon: FileText,
    title: 'Add materials',
    body: 'Upload the lectures and notes this course is built from.',
  },
  {
    tab: 'tutor',
    icon: MessagesSquare,
    title: 'Ask the tutor',
    body: 'Put a question to your own material and get a cited answer.',
  },
  {
    tab: 'quizzes',
    icon: FileQuestion,
    title: 'Practise with a quiz',
    body: 'Adaptive quizzes target the topics your mastery says need work.',
  },
  {
    tab: 'flashcards',
    icon: Layers,
    title: 'Review flashcards',
    body: 'Grounded cards, generated from your own documents.',
  },
];

export function OverviewTab({
  courseId,
  documentCount,
  readyCount,
  onOpenTab,
}: OverviewTabProps) {
  const topics = useTopics(courseId);
  const recommendations = useRecommendations(courseId);
  const mastery = useMastery(courseId);
  const due = useDueSummary(courseId);
  const extractTopics = useExtractTopics(courseId);
  const [error, setError] = useState<string | null>(null);

  async function handleExtract() {
    setError(null);
    try {
      await extractTopics.mutateAsync();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  const hasTopics = (topics.data ?? []).length > 0;

  return (
    <div className="space-y-6">
      {documentCount > 0 ? (
        <p className="text-sm text-ink-500">
          {readyCount} of {documentCount}{' '}
          {documentCount === 1 ? 'document is' : 'documents are'} processed and
          searchable.
        </p>
      ) : null}

      <Card>
        <CardHeader
          title="Topics"
          description="Derived from this course's own material — the unit ANCHOR tracks mastery against."
          action={
            <Button
              variant="secondary"
              size="sm"
              disabled={extractTopics.isPending || readyCount === 0}
              onClick={() => void handleExtract()}
              title={
                readyCount === 0
                  ? 'Upload and process a document first'
                  : hasTopics
                    ? 'Re-derive topics from the latest material'
                    : 'Derive topics from your material'
              }
            >
              {extractTopics.isPending ? <Spinner label="Extracting" /> : (
                <Target className="size-4" strokeWidth={2} aria-hidden />
              )}
              {hasTopics ? 'Regenerate' : 'Extract topics'}
            </Button>
          }
        />
        <CardBody className="space-y-3">
          {error ? <FormError message={error} /> : null}

          {topics.isPending ? <SectionSpinner label="Loading topics" /> : null}

          {hasTopics ? (
            <ul className="flex flex-wrap gap-2">
              {(topics.data ?? []).map((topic) => (
                <li
                  key={topic.id}
                  title={topic.description}
                  className="rounded-full border border-paper-300 bg-paper-100 px-3 py-1 text-sm text-ink-700"
                >
                  {topic.name}
                </li>
              ))}
            </ul>
          ) : topics.isPending ? null : (
            <EmptyState
              icon={Target}
              title={readyCount === 0 ? 'No processed material yet' : 'No topics yet'}
              description={
                readyCount === 0
                  ? 'Upload a document and wait for it to reach Ready, then extract topics.'
                  : 'Extract topics to unlock quizzes, mastery tracking and flashcards.'
              }
            />
          )}

          {hasTopics ? (
            <p className="text-xs text-ink-400">
              Regenerating after new uploads keeps your mastery history — a topic that
              disappears is retired, not deleted.
            </p>
          ) : null}
        </CardBody>
      </Card>

      {hasTopics ? (
        <RecommendationList
          recommendations={recommendations.data ?? []}
          isPending={recommendations.isPending}
        />
      ) : null}

      {hasTopics ? (
        <Card>
          <CardHeader
            title="Where you stand"
            description="Live figures from your own practice record."
          />
          <CardBody>
            {mastery.isPending ? (
              <SectionSpinner label="Loading" />
            ) : mastery.data && mastery.data.topicsStarted > 0 ? (
              <dl className="grid gap-4 sm:grid-cols-4">
                <Metric
                  label="Course mastery"
                  value={`${mastery.data.courseMastery.toFixed(0)}%`}
                  hint={`across ${mastery.data.topicsTotal} topics`}
                />
                <Metric
                  label="Topics started"
                  value={`${mastery.data.topicsStarted}/${mastery.data.topicsTotal}`}
                  hint="coverage"
                />
                <Metric
                  label="Questions answered"
                  value={String(mastery.data.questionsAnswered)}
                  hint={
                    mastery.data.accuracy === null
                      ? "no answers yet"
                      : `${mastery.data.accuracy.toFixed(0)}% accuracy`
                  }
                />
                <Metric
                  label="Due for review"
                  value={String(due.data?.dueNow ?? 0)}
                  hint={
                    (due.data?.overdue ?? 0) > 0
                      ? `${due.data?.overdue} overdue`
                      : "flashcards"
                  }
                />
              </dl>
            ) : (
              <p className="text-sm text-ink-500">
                Nothing practised yet. Take a quiz and your figures will appear here.
              </p>
            )}
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {QUICK_ACTIONS.map((action) => (
          <button
            key={action.tab}
            onClick={() => onOpenTab(action.tab)}
            className="rounded-card border border-paper-300 bg-white p-5 text-left transition-colors hover:border-ink-300"
          >
            <action.icon className="size-5 text-ink-700" strokeWidth={1.75} aria-hidden />
            <h3 className="mt-3 text-[15px] font-semibold text-ink-900">{action.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-ink-500">{action.body}</p>
          </button>
        ))}
      </div>
    </div>
  );
}


function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div>
      <dt className="text-xs font-medium tracking-wide text-ink-400 uppercase">
        {label}
      </dt>
      <dd className="tabular mt-1 font-serif text-2xl text-ink-900">{value}</dd>
      <dd className="mt-0.5 text-xs text-ink-400">{hint}</dd>
    </div>
  );
}
