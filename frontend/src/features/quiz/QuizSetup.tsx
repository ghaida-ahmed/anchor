import { Sparkles, Target } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { cn } from '@/lib/cn';
import type {
  Difficulty,
  GenerateQuizInput,
  QuizFormat,
  QuizMode,
  Topic,
} from '@/services/api/learning';
import { DIFFICULTIES } from '@/services/api/learning';

const QUESTION_COUNTS = [5, 8, 12] as const;

/**
 * What each answer format asks of the student, in their words.
 *
 * The trade-off is stated plainly rather than hidden: writing an answer is
 * slower to mark and harder to do, and it is worth more towards mastery for
 * exactly that reason.
 */
const FORMATS: ReadonlyArray<{ value: QuizFormat; label: string; body: string }> = [
  {
    value: 'mcq',
    label: 'Multiple choice',
    body: 'Pick from four options. Marked instantly.',
  },
  {
    value: 'mixed',
    label: 'Mixed',
    body: 'Mostly multiple choice, with the harder questions written out.',
  },
  {
    value: 'short_answer',
    label: 'Written answers',
    body: 'Answer in your own words. Slower to mark, and worth more towards mastery.',
  },
];

interface QuizSetupProps {
  topics: Topic[];
  isGenerating: boolean;
  error: string | null;
  onGenerate: (input: GenerateQuizInput) => void;
}

export function QuizSetup({ topics, isGenerating, error, onGenerate }: QuizSetupProps) {
  const [mode, setMode] = useState<QuizMode>('adaptive');
  const [questionCount, setQuestionCount] = useState<number>(8);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [difficulty, setDifficulty] = useState<Difficulty | null>(null);
  const [quizFormat, setQuizFormat] = useState<QuizFormat>('mcq');

  function toggleTopic(topicId: string) {
    setSelectedTopics((current) =>
      current.includes(topicId)
        ? current.filter((id) => id !== topicId)
        : [...current, topicId],
    );
  }

  function handleGenerate() {
    onGenerate({
      mode,
      questionCount,
      quizFormat,
      ...(mode === 'standard' ? { topicIds: selectedTopics, difficulty } : {}),
    });
  }

  return (
    <Card>
      <CardHeader
        title="New quiz"
        description="Questions are written from your own uploaded material."
      />
      <CardBody className="space-y-6">
        {error ? <FormError message={error} /> : null}

        <fieldset>
          <legend className="text-sm font-medium text-ink-800">Mode</legend>
          <div className="mt-2 grid gap-3 sm:grid-cols-2">
            <ModeCard
              icon={Target}
              title="Adaptive"
              body="ANCHOR picks the topics that need work, based on your mastery."
              selected={mode === 'adaptive'}
              onSelect={() => setMode('adaptive')}
            />
            <ModeCard
              icon={Sparkles}
              title="Standard"
              body="Choose the topics and difficulty yourself."
              selected={mode === 'standard'}
              onSelect={() => setMode('standard')}
            />
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-ink-800">Questions</legend>
          <div className="mt-2 flex gap-2">
            {QUESTION_COUNTS.map((count) => (
              <button
                key={count}
                type="button"
                onClick={() => setQuestionCount(count)}
                className={cn(
                  'tabular rounded-lg border px-4 py-2 text-sm font-medium transition-colors',
                  questionCount === count
                    ? 'border-ink-900 bg-ink-900 text-paper-50'
                    : 'border-paper-400 text-ink-600 hover:border-ink-300',
                )}
              >
                {count}
              </button>
            ))}
          </div>
        </fieldset>

        <fieldset>
          <legend className="text-sm font-medium text-ink-800">Answer format</legend>
          <div className="mt-2 space-y-2">
            {FORMATS.map((format) => (
              <button
                key={format.value}
                type="button"
                onClick={() => setQuizFormat(format.value)}
                aria-pressed={quizFormat === format.value}
                className={cn(
                  'w-full rounded-lg border px-4 py-2.5 text-left transition-colors',
                  quizFormat === format.value
                    ? 'border-ink-900 bg-paper-100'
                    : 'border-paper-300 hover:border-ink-300',
                )}
              >
                <span className="text-sm font-medium text-ink-900">{format.label}</span>
                <span className="mt-0.5 block text-xs leading-relaxed text-ink-500">
                  {format.body}
                </span>
              </button>
            ))}
          </div>
        </fieldset>

        {quizFormat !== 'mcq' ? (
          <p className="rounded-lg border border-paper-300 bg-paper-50 px-4 py-2.5 text-xs leading-relaxed text-ink-500">
            Written answers are marked against key points taken from your own
            materials. Where a marking is not confident, the answer is left unmarked
            rather than counted wrong — it will not move your mastery either way.
          </p>
        ) : null}

        {mode === 'standard' ? (
          <>
            <fieldset>
              <legend className="text-sm font-medium text-ink-800">
                Topics{' '}
                <span className="font-normal text-ink-400">
                  {selectedTopics.length === 0 ? '(all)' : `(${selectedTopics.length})`}
                </span>
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {topics.map((topic) => (
                  <button
                    key={topic.id}
                    type="button"
                    onClick={() => toggleTopic(topic.id)}
                    className={cn(
                      'rounded-full border px-3 py-1 text-sm transition-colors',
                      selectedTopics.includes(topic.id)
                        ? 'border-ink-900 bg-ink-900 text-paper-50'
                        : 'border-paper-400 text-ink-700 hover:border-ink-300',
                    )}
                  >
                    {topic.name}
                  </button>
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend className="text-sm font-medium text-ink-800">Difficulty</legend>
              <div className="mt-2 flex gap-2">
                <DifficultyChip
                  label="Mixed"
                  selected={difficulty === null}
                  onSelect={() => setDifficulty(null)}
                />
                {DIFFICULTIES.map((level) => (
                  <DifficultyChip
                    key={level}
                    label={level}
                    selected={difficulty === level}
                    onSelect={() => setDifficulty(level)}
                  />
                ))}
              </div>
            </fieldset>
          </>
        ) : null}

        <Button onClick={handleGenerate} disabled={isGenerating}>
          {isGenerating ? <Spinner label="Generating" /> : null}
          {isGenerating ? 'Writing questions…' : 'Generate quiz'}
        </Button>
      </CardBody>
    </Card>
  );
}

function ModeCard({
  icon: Icon,
  title,
  body,
  selected,
  onSelect,
}: {
  icon: typeof Target;
  title: string;
  body: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'rounded-card border p-4 text-left transition-colors',
        selected
          ? 'border-ink-900 bg-paper-100'
          : 'border-paper-300 hover:border-ink-300',
      )}
    >
      <Icon
        className={cn('size-4', selected ? 'text-ink-900' : 'text-ink-500')}
        strokeWidth={1.75}
        aria-hidden
      />
      <p className="mt-2 text-sm font-semibold text-ink-900">{title}</p>
      <p className="mt-1 text-xs leading-relaxed text-ink-500">{body}</p>
    </button>
  );
}

function DifficultyChip({
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
        'rounded-lg border px-3 py-1.5 text-sm capitalize transition-colors',
        selected
          ? 'border-ink-900 bg-ink-900 text-paper-50'
          : 'border-paper-400 text-ink-600 hover:border-ink-300',
      )}
    >
      {label}
    </button>
  );
}
