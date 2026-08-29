import { ArrowRight, Check, Target, X } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody } from '@/components/ui/Card';
import { FormError } from '@/components/ui/ErrorState';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { Spinner } from '@/components/ui/Spinner';
import { AnswerFeedback } from '@/features/quiz/AnswerFeedback';
import { ShortAnswerField } from '@/features/quiz/ShortAnswerField';
import { SourceLine } from '@/features/quiz/SourceLine';
import { cn } from '@/lib/cn';
import { toErrorMessage } from '@/services/api/client';
import type { AnswerResult, AttemptSummary, Quiz } from '@/services/api/learning';
import {
  useCompleteAttempt,
  useStartAttempt,
  useSubmitAnswer,
  useSubmitShortAnswer,
} from '@/hooks/queries/useLearning';

interface QuizRunnerProps {
  quiz: Quiz;
  courseId: string;
  onFinished: (summary: AttemptSummary) => void;
  onExit: () => void;
}

/**
 * Takes one quiz, one question at a time, in either format.
 *
 * The correct answer is not present in the data this component receives — for a
 * multiple-choice question that means no `correct_index`, and for a written one no
 * reference answer and no rubric. All of it arrives only in the response to
 * submitting, which is what makes the "no answers before submission" guarantee
 * hold on the client too.
 */
export function QuizRunner({ quiz, courseId, onFinished, onExit }: QuizRunnerProps) {
  const startAttempt = useStartAttempt();
  const submitAnswer = useSubmitAnswer();
  const submitShortAnswer = useSubmitShortAnswer();
  const completeAttempt = useCompleteAttempt(courseId);

  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [response, setResponse] = useState('');
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const question = quiz.questions[index];
  const isLast = index === quiz.questions.length - 1;
  const isWritten = question?.questionType === 'short_answer';
  const isSubmitting = submitAnswer.isPending || submitShortAnswer.isPending;
  const canSubmit = isWritten ? response.trim().length > 0 : selected !== null;

  useEffect(() => {
    let cancelled = false;
    startAttempt
      .mutateAsync(quiz.id)
      .then((attempt) => {
        if (!cancelled) setAttemptId(attempt.id);
      })
      .catch((caught) => {
        if (!cancelled) setError(toErrorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
    // Starting an attempt is a one-shot side effect for this quiz.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quiz.id]);

  async function handleSubmit() {
    if (!attemptId || !question || !canSubmit) return;
    setError(null);
    try {
      setResult(
        isWritten
          ? await submitShortAnswer.mutateAsync({
              attemptId,
              questionId: question.id,
              responseText: response,
            })
          : await submitAnswer.mutateAsync({
              attemptId,
              questionId: question.id,
              // `canSubmit` already established this is a real choice.
              selectedIndex: selected as number,
            }),
      );
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  async function handleNext() {
    if (!attemptId) return;
    if (!isLast) {
      setIndex((current) => current + 1);
      setSelected(null);
      setResponse('');
      setResult(null);
      return;
    }
    setError(null);
    try {
      onFinished(await completeAttempt.mutateAsync(attemptId));
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  if (!attemptId && !error) {
    return (
      <Card>
        <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-ink-500">
          <Spinner className="text-ink-400" label="Starting" />
          Starting your attempt…
        </div>
      </Card>
    );
  }

  if (!question) return null;

  return (
    <div className="space-y-5">
      <div>
        <div className="mb-2 flex items-center justify-between text-sm">
          <span className="tabular text-ink-500">
            Question {index + 1} of {quiz.questions.length}
          </span>
          <button
            type="button"
            onClick={onExit}
            className="text-ink-400 transition-colors hover:text-ink-800"
          >
            Leave quiz
          </button>
        </div>
        <ProgressBar
          value={(index + (result ? 1 : 0)) / quiz.questions.length}
          label="Quiz progress"
        />
      </div>

      {error ? <FormError message={error} /> : null}

      <Card>
        <CardBody className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="neutral">{question.topicName}</Badge>
            <Badge tone="brass">{question.difficulty}</Badge>
            {isWritten ? <Badge tone="neutral">Written answer</Badge> : null}
          </div>

          <p className="text-[17px] leading-relaxed text-ink-900">
            {question.questionText}
          </p>

          {isWritten ? (
            <ShortAnswerField
              value={response}
              onChange={setResponse}
              disabled={result !== null}
            />
          ) : (
            <ul className="space-y-2">
              {(question.options ?? []).map((option, optionIndex) => (
                <li key={option}>
                  <OptionButton
                    option={option}
                    index={optionIndex}
                    selected={selected === optionIndex}
                    result={result}
                    disabled={result !== null}
                    onSelect={() => setSelected(optionIndex)}
                  />
                </li>
              ))}
            </ul>
          )}

          {result && isWritten ? <AnswerFeedback result={result} /> : null}

          {result && !isWritten ? (
            <div
              className={cn(
                'rounded-card border px-4 py-3',
                result.isCorrect
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-red-200 bg-red-50',
              )}
            >
              <p
                className={cn(
                  'flex items-center gap-2 text-sm font-medium',
                  result.isCorrect ? 'text-signal-success' : 'text-signal-danger',
                )}
              >
                {result.isCorrect ? (
                  <Check className="size-4" strokeWidth={2.5} aria-hidden />
                ) : (
                  <X className="size-4" strokeWidth={2.5} aria-hidden />
                )}
                {result.isCorrect ? 'Correct' : 'Not quite'}
              </p>
              <p className="mt-2 text-sm leading-relaxed text-ink-700">
                {result.explanation}
              </p>
              <SourceLine source={result.source} />
            </div>
          ) : null}

          <div className="flex justify-end">
            {result ? (
              <Button onClick={() => void handleNext()} disabled={completeAttempt.isPending}>
                {completeAttempt.isPending ? <Spinner label="Finishing" /> : null}
                {isLast ? 'Finish quiz' : 'Next question'}
                {!isLast ? <ArrowRight className="size-4" strokeWidth={2} aria-hidden /> : null}
              </Button>
            ) : (
              <Button onClick={() => void handleSubmit()} disabled={!canSubmit || isSubmitting}>
                {isSubmitting ? <Spinner label="Checking" /> : null}
                {isSubmitting && isWritten ? 'Marking your answer…' : 'Submit answer'}
              </Button>
            )}
          </div>
        </CardBody>
      </Card>

      {quiz.mode === 'adaptive' && quiz.selectionRationale ? (
        <p className="flex items-start gap-2 rounded-lg border border-paper-300 bg-paper-50 px-4 py-2.5 text-sm text-ink-500">
          <Target className="mt-0.5 size-3.5 shrink-0 text-brass-500" strokeWidth={2} aria-hidden />
          {quiz.selectionRationale}
        </p>
      ) : null}
    </div>
  );
}

function OptionButton({
  option,
  index,
  selected,
  result,
  disabled,
  onSelect,
}: {
  option: string;
  index: number;
  selected: boolean;
  result: AnswerResult | null;
  disabled: boolean;
  onSelect: () => void;
}) {
  const isCorrect = result !== null && index === result.correctIndex;
  const isWrongChoice = result !== null && selected && !result.isCorrect;

  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={cn(
        'flex w-full items-start gap-3 rounded-lg border px-4 py-3 text-left text-sm transition-colors',
        'disabled:cursor-default',
        isCorrect
          ? 'border-emerald-300 bg-emerald-50 text-ink-900'
          : isWrongChoice
            ? 'border-red-300 bg-red-50 text-ink-900'
            : selected
              ? 'border-ink-900 bg-paper-100 text-ink-900'
              : 'border-paper-300 text-ink-700 hover:border-ink-300',
      )}
    >
      <span
        className={cn(
          'mt-px flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px] font-medium',
          isCorrect
            ? 'border-signal-success text-signal-success'
            : isWrongChoice
              ? 'border-signal-danger text-signal-danger'
              : selected
                ? 'border-ink-900 bg-ink-900 text-paper-50'
                : 'border-paper-400 text-ink-400',
        )}
      >
        {String.fromCharCode(65 + index)}
      </span>
      {option}
    </button>
  );
}
