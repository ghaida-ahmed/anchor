import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { SourceLine } from '@/features/quiz/SourceLine';
import { GRADING_FAILED_STYLE, VERDICT_STYLES } from '@/features/quiz/verdict';
import { cn } from '@/lib/cn';
import type { AnswerResult, AttemptSummary, Quiz } from '@/services/api/learning';

/**
 * The marker beside each reviewed question.
 *
 * A written answer uses its verdict's own styling, so "not marked" is visibly
 * distinct from "wrong" here as well as in the runner. A multiple-choice answer
 * has only the two outcomes it ever had.
 */
function ResultMark({ result }: { result: AnswerResult }) {
  const style =
    result.questionType === 'short_answer'
      ? result.gradingFailed || result.verdict === null
        ? GRADING_FAILED_STYLE
        : VERDICT_STYLES[result.verdict]
      : result.isCorrect
        ? VERDICT_STYLES.correct
        : VERDICT_STYLES.incorrect;
  const Icon = style.icon;

  return (
    <span
      className={cn(
        'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border',
        style.border,
        style.background,
      )}
      title={style.label}
    >
      <Icon className={cn('size-3', style.text)} strokeWidth={3} aria-hidden />
      <span className="sr-only">{style.label}</span>
    </span>
  );
}

interface QuizResultsProps {
  summary: AttemptSummary;
  quiz: Quiz;
  onDone: () => void;
  onViewProgress: () => void;
}

export function QuizResults({ summary, quiz, onDone, onViewProgress }: QuizResultsProps) {
  const score = summary.scorePercent ?? 0;
  const questions = new Map(quiz.questions.map((question) => [question.id, question]));

  // Excluded from the denominator on the server; saying so here stops the score
  // reading as though those answers were counted wrong.
  const unmarked = summary.results.filter(
    (result) =>
      result.questionType === 'short_answer' &&
      (result.gradingFailed || result.verdict === 'uncertain'),
  ).length;

  return (
    <div className="space-y-5">
      <Card>
        <CardBody className="text-center">
          <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">
            {summary.quizTitle}
          </p>
          <p className="tabular mt-3 font-serif text-5xl text-ink-900">
            {score.toFixed(0)}%
          </p>
          <p className="mt-2 text-sm text-ink-500">
            {summary.correctCount} of {summary.questionCount} correct
          </p>
          {unmarked > 0 ? (
            <p className="mt-1 text-xs text-ink-400">
              {unmarked === 1 ? '1 answer' : `${unmarked} answers`} could not be marked
              with confidence, so {unmarked === 1 ? 'it is' : 'they are'} left out of
              this score — and out of your mastery.
            </p>
          ) : null}

          <div className="mt-6 flex justify-center gap-2">
            <Button variant="secondary" onClick={onDone}>
              Back to quizzes
            </Button>
            <Button onClick={onViewProgress}>See your progress</Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Review"
          description="Every answer, with the source it came from."
        />
        <ul className="divide-y divide-paper-200">
          {summary.results.map((result, index) => {
            const question = questions.get(result.questionId);
            if (!question) return null;

            const options = question.options ?? [];
            const chosen =
              result.selectedIndex !== null ? options[result.selectedIndex] : null;
            const isWritten = result.questionType === 'short_answer';

            return (
              <li key={result.questionId} className="px-5 py-4">
                <div className="flex items-start gap-3">
                  <ResultMark result={result} />

                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-ink-900">
                      {index + 1}. {question.questionText}
                    </p>

                    {isWritten ? (
                      <>
                        {result.responseText ? (
                          <p className="mt-2 text-sm text-ink-500">
                            <span className="text-ink-400">You wrote:</span>{' '}
                            {result.responseText}
                          </p>
                        ) : (
                          <p className="mt-2 text-sm text-ink-500">
                            <em>Not answered</em>
                          </p>
                        )}
                        {result.rubricResults.length > 0 ? (
                          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
                            {result.rubricResults.map((row) => (
                              <li
                                key={row.concept}
                                className={cn(
                                  'text-xs',
                                  row.satisfied
                                    ? 'text-signal-success'
                                    : 'text-ink-400 line-through',
                                )}
                              >
                                {row.concept}
                              </li>
                            ))}
                          </ul>
                        ) : null}
                        {result.feedback ? (
                          <p className="mt-2 text-sm leading-relaxed text-ink-600">
                            {result.feedback}
                          </p>
                        ) : null}
                        {result.referenceAnswer ? (
                          <p className="mt-2 text-sm text-ink-600">
                            <span className="text-ink-400">Model answer:</span>{' '}
                            {result.referenceAnswer}
                          </p>
                        ) : null}
                      </>
                    ) : (
                      <>
                        <p className="mt-2 text-sm text-ink-600">
                          <span className="text-ink-400">Correct:</span>{' '}
                          {result.correctIndex !== null
                            ? options[result.correctIndex]
                            : null}
                        </p>
                        {!result.isCorrect ? (
                          <p className="mt-0.5 text-sm text-ink-500">
                            <span className="text-ink-400">You chose:</span>{' '}
                            {chosen ?? <em>no answer</em>}
                          </p>
                        ) : null}
                        <p className="mt-2 text-sm leading-relaxed text-ink-600">
                          {result.explanation}
                        </p>
                      </>
                    )}

                    <SourceLine source={result.source} />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </Card>
    </div>
  );
}
