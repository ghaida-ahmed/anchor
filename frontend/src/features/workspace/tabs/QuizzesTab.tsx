import { ListChecks, Target } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { SectionHeading } from '@/components/ui/SectionHeading';
import { SectionSpinner } from '@/components/ui/Spinner';
import { QuizResults } from '@/features/quiz/QuizResults';
import { QuizRunner } from '@/features/quiz/QuizRunner';
import { QuizSetup } from '@/features/quiz/QuizSetup';
import type { WorkspaceTab } from '@/features/workspace/workspaceTabs';
import {
  useGenerateQuiz,
  useQuizzes,
  useTopics,
} from '@/hooks/queries/useLearning';
import { formatRelativeTime } from '@/lib/format';
import { toErrorMessage } from '@/services/api/client';
import * as learningApi from '@/services/api/learning';
import type { AttemptSummary, GenerateQuizInput, Quiz } from '@/services/api/learning';

type View =
  | { name: 'browse' }
  | { name: 'taking'; quiz: Quiz }
  | { name: 'results'; quiz: Quiz; summary: AttemptSummary };

interface QuizzesTabProps {
  courseId: string;
  readyCount: number;
  onOpenTab: (tab: WorkspaceTab) => void;
}

export function QuizzesTab({ courseId, readyCount, onOpenTab }: QuizzesTabProps) {
  const topics = useTopics(courseId);
  const quizzes = useQuizzes(courseId);
  const generateQuiz = useGenerateQuiz(courseId);

  const [view, setView] = useState<View>({ name: 'browse' });
  const [error, setError] = useState<string | null>(null);
  const [openingId, setOpeningId] = useState<string | null>(null);

  async function handleGenerate(input: GenerateQuizInput) {
    setError(null);
    try {
      setView({ name: 'taking', quiz: await generateQuiz.mutateAsync(input) });
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  async function handleRetake(quizId: string) {
    setError(null);
    setOpeningId(quizId);
    try {
      // Re-reads the stored quiz; generation is never repeated on a retake.
      setView({ name: 'taking', quiz: await learningApi.fetchQuiz(quizId) });
    } catch (caught) {
      setError(toErrorMessage(caught));
    } finally {
      setOpeningId(null);
    }
  }

  if (view.name === 'taking') {
    return (
      <QuizRunner
        quiz={view.quiz}
        courseId={courseId}
        onFinished={(summary) => setView({ name: 'results', quiz: view.quiz, summary })}
        onExit={() => setView({ name: 'browse' })}
      />
    );
  }

  if (view.name === 'results') {
    return (
      <QuizResults
        summary={view.summary}
        quiz={view.quiz}
        onDone={() => setView({ name: 'browse' })}
        onViewProgress={() => {
          setView({ name: 'browse' });
          onOpenTab('progress');
        }}
      />
    );
  }

  if (readyCount === 0) {
    return (
      <Card>
        <EmptyState
          icon={ListChecks}
          title="Upload and process course materials first"
          description="Quizzes are written from your own documents, so there is nothing to build questions from yet."
          action={<Button onClick={() => onOpenTab('materials')}>Go to Materials</Button>}
        />
      </Card>
    );
  }

  if (topics.isPending) return <SectionSpinner label="Loading topics" />;

  if (topics.isError) {
    return (
      <Card>
        <ErrorState
          message={toErrorMessage(topics.error)}
          onRetry={() => void topics.refetch()}
        />
      </Card>
    );
  }

  if ((topics.data ?? []).length === 0) {
    return (
      <Card>
        <EmptyState
          icon={Target}
          title="Extract topics before generating a quiz"
          description="ANCHOR needs to know what your course covers before it can build questions and track mastery."
          action={<Button onClick={() => onOpenTab('overview')}>Go to Overview</Button>}
        />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <QuizSetup
        topics={topics.data ?? []}
        isGenerating={generateQuiz.isPending}
        error={error}
        onGenerate={(input) => void handleGenerate(input)}
      />

      <div>
        <SectionHeading
          title="Your quizzes"
          description="Generated quizzes are saved, so retaking one costs nothing."
        />

        {quizzes.isPending ? <SectionSpinner label="Loading quizzes" /> : null}

        {quizzes.data && quizzes.data.length === 0 ? (
          <Card>
            <EmptyState
              icon={ListChecks}
              title="No quizzes yet"
              description="Generate one above to start building your mastery record."
            />
          </Card>
        ) : null}

        {quizzes.data && quizzes.data.length > 0 ? (
          <Card>
            <ul className="divide-y divide-paper-200">
              {quizzes.data.map((quiz) => (
                <li key={quiz.id} className="flex flex-wrap items-center gap-4 px-5 py-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <p className="truncate text-sm font-medium text-ink-900">
                        {quiz.title}
                      </p>
                      {quiz.mode === 'adaptive' ? (
                        <Badge tone="brass">
                          <Target className="size-3" strokeWidth={2} aria-hidden />
                          Adaptive
                        </Badge>
                      ) : null}
                    </div>
                    <p className="mt-0.5 text-xs text-ink-400">
                      {quiz.questionCount} questions · {formatRelativeTime(quiz.createdAt)}
                    </p>
                    {quiz.selectionRationale ? (
                      <p className="mt-1 text-xs text-ink-500">{quiz.selectionRationale}</p>
                    ) : null}
                  </div>
                  <Button
                    variant="secondary"
                    size="sm"
                    disabled={openingId === quiz.id}
                    onClick={() => void handleRetake(quiz.id)}
                  >
                    {openingId === quiz.id ? 'Opening…' : 'Take'}
                  </Button>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </div>
    </div>
  );
}
