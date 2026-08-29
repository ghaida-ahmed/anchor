import { Clock, Target, TrendingDown, TrendingUp } from 'lucide-react';

import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { SectionSpinner } from '@/components/ui/Spinner';
import { StatTile } from '@/components/ui/StatTile';
import { RecommendationList } from '@/features/progress/RecommendationList';
import { ActivityBars } from '@/features/progress/ActivityBars';
import { Sparkline } from '@/features/progress/Sparkline';
import { RetentionBadge } from '@/features/progress/RetentionBadge';
import { MasteryBadge } from '@/features/quiz/MasteryBadge';
import { BAND_BAR_TONE } from '@/features/quiz/masteryTone';
import { useAttempts, useRecommendations } from '@/hooks/queries/useLearning';
import { useAnalytics, useDueSummary, useMastery } from '@/hooks/queries/useRetention';
import { cn } from '@/lib/cn';
import { formatRelativeTime } from '@/lib/format';
import { toErrorMessage } from '@/services/api/client';
import type { TopicRetention } from '@/services/api/retention';

export function ProgressTab({ courseId }: { courseId: string }) {
  const mastery = useMastery(courseId);
  const analytics = useAnalytics(courseId);
  const due = useDueSummary(courseId);
  const recommendations = useRecommendations(courseId);
  const attempts = useAttempts(courseId);

  if (mastery.isPending) return <SectionSpinner label="Loading your progress" />;

  if (mastery.isError || !mastery.data) {
    return (
      <Card>
        <ErrorState
          title="Could not load your progress"
          message={toErrorMessage(mastery.error)}
          onRetry={() => void mastery.refetch()}
        />
      </Card>
    );
  }

  const data = mastery.data;

  if (data.topicsTotal === 0) {
    return (
      <Card>
        <EmptyState
          icon={Target}
          title="No topics yet"
          description="Extract topics from your course materials, then take a quiz to start building a mastery record."
        />
      </Card>
    );
  }

  const hasAttempted = data.questionsAnswered > 0 || data.topicsStarted > 0;

  // Weakest by present estimate first; never-started topics last, since they are
  // not failures and burying them keeps the top of the list actionable.
  const ordered = [...data.topics].sort((a, b) => {
    const aNew = a.retentionStatus === 'new';
    const bNew = b.retentionStatus === 'new';
    if (aNew !== bNew) return aNew ? 1 : -1;
    return a.effectiveMastery - b.effectiveMastery;
  });

  const masteryTrend = (analytics.data?.daily ?? []).map((point) => ({
    label: point.day,
    value: point.meanMastery,
  }));
  const scoreTrend = (analytics.data?.attemptScores ?? []).map((score) => ({
    label: new Date(score.completedAt).toLocaleDateString('en-GB', {
      day: 'numeric',
      month: 'short',
    }),
    value: score.scorePercent,
  }));

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Course mastery"
          value={hasAttempted ? `${data.courseMastery.toFixed(0)}%` : '—'}
          hint={
            hasAttempted
              ? `Across all ${data.topicsTotal} topics`
              : 'No quiz data yet'
          }
        />
        <StatTile
          label="On what you've studied"
          value={
            data.practisedMastery === null
              ? '—'
              : `${data.practisedMastery.toFixed(0)}%`
          }
          hint={`${data.topicsStarted} of ${data.topicsTotal} topics started`}
        />
        <StatTile
          label="Questions answered"
          value={String(data.questionsAnswered)}
          hint={
            data.questionsAnswered > 0
              ? `${data.correctAnswers} correct`
              : 'No quiz data yet'
          }
        />
        <StatTile
          label="Due for review"
          value={String(due.data?.dueNow ?? 0)}
          hint={
            (due.data?.overdue ?? 0) > 0
              ? `${due.data?.overdue} overdue`
              : `${due.data?.upcoming ?? 0} coming up`
          }
        />
      </div>

      {!hasAttempted ? (
        <p className="rounded-lg border border-paper-300 bg-paper-50 px-4 py-3 text-sm text-ink-500">
          No quiz data yet. Take a quiz and your mastery will appear here — a topic
          you have not practised shows as <span className="font-medium">Not started</span>,
          not as zero.
        </p>
      ) : null}

      <RecommendationList
        recommendations={recommendations.data ?? []}
        isPending={recommendations.isPending}
      />

      {hasAttempted ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="Am I improving?"
              description="Quiz scores, oldest first."
            />
            <CardBody>
              <Sparkline
                points={scoreTrend}
                caption="Quiz score over time, as a percentage"
              />
            </CardBody>
          </Card>

          <Card>
            <CardHeader
              title="How much have I practised?"
              description="Questions answered per active day."
            />
            <CardBody>
              <ActivityBars days={analytics.data?.daily ?? []} />
            </CardBody>
          </Card>
        </div>
      ) : null}

      {masteryTrend.length > 1 ? (
        <Card>
          <CardHeader
            title="Mastery over time"
            description="Average mastery recorded on each day you practised."
          />
          <CardBody>
            <Sparkline points={masteryTrend} caption="Mean mastery per active day" />
          </CardBody>
        </Card>
      ) : null}

      {hasAttempted && (data.strongestTopic || data.needsReviewTopic) ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {data.strongestTopic ? (
            <Highlight
              icon={TrendingUp}
              tone="success"
              label="Strongest topic"
              value={data.strongestTopic}
            />
          ) : null}
          {data.needsReviewTopic ? (
            <Highlight
              icon={TrendingDown}
              tone="danger"
              label="What to review next"
              value={data.needsReviewTopic}
            />
          ) : null}
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="Topic mastery"
          description="Current estimate first. Every figure comes from your own answers."
        />
        <ul className="divide-y divide-paper-200">
          {ordered.map((topic) => (
            <TopicRow key={topic.topicId} topic={topic} />
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader title="Recent attempts" description="Your last completed quizzes." />
        {attempts.data && attempts.data.length > 0 ? (
          <ul className="divide-y divide-paper-200">
            {attempts.data.map((attempt) => (
              <li key={attempt.id} className="flex items-center gap-4 px-5 py-3.5 text-sm">
                <span className="tabular w-14 font-medium text-ink-900">
                  {attempt.scorePercent === null
                    ? '—'
                    : `${attempt.scorePercent.toFixed(0)}%`}
                </span>
                <span className="text-ink-500">{attempt.correctCount} correct</span>
                <span className="ml-auto text-xs text-ink-400">
                  {attempt.completedAt
                    ? formatRelativeTime(attempt.completedAt)
                    : 'In progress'}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <CardBody>
            <p className="text-sm text-ink-500">No completed quizzes yet.</p>
          </CardBody>
        )}
      </Card>
    </div>
  );
}

function TopicRow({ topic }: { topic: TopicRetention }) {
  const notStarted = topic.retentionStatus === 'new';
  // Only mention a gap when the estimate has actually moved, and phrase it as
  // elapsed time rather than as knowledge lost.
  const hasDecayed = !notStarted && topic.masteryScore - topic.effectiveMastery >= 3;

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-ink-800">{topic.topicName}</span>
        <MasteryBadge band={topic.effectiveBand} label={topic.bandLabel} />
        <RetentionBadge status={topic.retentionStatus} label={topic.retentionLabel} />
        <span className="tabular ml-auto text-xs text-ink-400">
          {notStarted
            ? 'Not practised'
            : `${topic.questionsAttempted} answered · ${topic.accuracy?.toFixed(0)}% accuracy`}
        </span>
        <span className="tabular w-12 shrink-0 text-right text-sm font-medium text-ink-900">
          {notStarted ? '—' : `${topic.effectiveMastery.toFixed(0)}%`}
        </span>
      </div>

      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-paper-300">
        <div
          className={cn(
            'h-full rounded-full transition-[width]',
            BAND_BAR_TONE[topic.effectiveBand],
          )}
          style={{ width: `${notStarted ? 0 : topic.effectiveMastery}%` }}
          role="progressbar"
          aria-valuenow={Math.round(topic.effectiveMastery)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`${topic.topicName} current estimate`}
        />
      </div>

      {hasDecayed && topic.daysSincePractice !== null ? (
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-ink-400">
          <Clock className="size-3" strokeWidth={2} aria-hidden />
          Review recommended — last practised {Math.round(topic.daysSincePractice)} days
          ago. You scored {topic.masteryScore.toFixed(0)}% at the time.
        </p>
      ) : null}
    </li>
  );
}

function Highlight({
  icon: Icon,
  tone,
  label,
  value,
}: {
  icon: typeof TrendingUp;
  tone: 'success' | 'danger';
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-card border border-paper-300 bg-white px-5 py-4">
      <p className="flex items-center gap-1.5 text-xs font-medium tracking-wide text-ink-400 uppercase">
        <Icon
          className={cn(
            'size-3.5',
            tone === 'success' ? 'text-signal-success' : 'text-signal-danger',
          )}
          strokeWidth={2}
          aria-hidden
        />
        {label}
      </p>
      <p className="mt-2 font-serif text-lg text-ink-900">{value}</p>
    </div>
  );
}
