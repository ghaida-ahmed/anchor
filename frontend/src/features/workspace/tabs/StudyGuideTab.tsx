import { AlertTriangle, BookOpen, RefreshCw, Sparkles } from 'lucide-react';
import { useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState, FormError } from '@/components/ui/ErrorState';
import { SectionSpinner, Spinner } from '@/components/ui/Spinner';
import { BAND_BADGE_TONE } from '@/features/quiz/masteryTone';
import { SourceLine } from '@/features/quiz/SourceLine';
import { useGenerateStudyGuide, useStudyGuide } from '@/hooks/queries/useKnowledge';
import { formatDate } from '@/lib/format';
import { toErrorMessage } from '@/services/api/client';
import type { MasteryBand } from '@/services/api/learning';
import type { StudyGuideSection } from '@/services/api/studyGuide';

/**
 * The course study guide.
 *
 * Written once from the material and read back; the mastery badges beside each
 * section are overlaid live, so studying updates them without rewriting a word of
 * the guide. A guide whose material has changed is labelled stale and stays
 * readable — it is not silently regenerated, because that would spend the
 * student's quota without asking.
 */
export function StudyGuideTab({ courseId }: { courseId: string }) {
  const guide = useStudyGuide(courseId);
  const generate = useGenerateStudyGuide(courseId);
  const [error, setError] = useState<string | null>(null);

  async function handleGenerate() {
    setError(null);
    try {
      await generate.mutateAsync();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  if (guide.isPending) return <SectionSpinner label="Loading your study guide" />;

  if (guide.isError) {
    return (
      <Card>
        <ErrorState
          title="Could not load the study guide"
          message={toErrorMessage(guide.error)}
          onRetry={() => void guide.refetch()}
        />
      </Card>
    );
  }

  const data = guide.data;

  const generateButton = (
    <Button
      variant={data ? 'secondary' : 'primary'}
      size="sm"
      onClick={() => void handleGenerate()}
      disabled={generate.isPending}
    >
      {generate.isPending ? (
        <Spinner label="Writing" />
      ) : data ? (
        <RefreshCw className="size-3.5" strokeWidth={2} aria-hidden />
      ) : (
        <Sparkles className="size-3.5" strokeWidth={2} aria-hidden />
      )}
      {generate.isPending ? 'Writing your guide…' : data ? 'Regenerate' : 'Build the guide'}
    </Button>
  );

  if (!data) {
    return (
      <div className="space-y-6">
        {error ? <FormError message={error} /> : null}
        <Card>
          <CardHeader
            title="Study guide"
            description="A written guide to this course, drawn from your own materials."
            action={generateButton}
          />
          <EmptyState
            icon={BookOpen}
            title="No guide yet"
            description="ANCHOR writes one section per topic from the passages that cover it, then an overview tying them together. Every section cites what it came from."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error ? <FormError message={error} /> : null}

      {data.isStale ? (
        <p className="flex items-start gap-2 rounded-card border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-ink-700">
          <AlertTriangle
            className="mt-0.5 size-4 shrink-0 text-signal-caution"
            strokeWidth={2}
            aria-hidden
          />
          <span>
            Your materials or topics have changed since this guide was written, so it
            may no longer cover everything. Regenerate it when you are ready.
          </span>
        </p>
      ) : null}

      {data.status === 'failed' && data.errorMessage ? (
        <FormError message={data.errorMessage} />
      ) : null}

      <Card>
        <CardHeader
          title="Study guide"
          description={
            data.generatedAt
              ? `Written from your materials on ${formatDate(data.generatedAt)}.`
              : 'Written from your materials.'
          }
          action={generateButton}
        />
        {data.overview ? (
          <CardBody>
            <p className="text-[15px] leading-relaxed text-ink-700">{data.overview}</p>
          </CardBody>
        ) : null}
      </Card>

      {data.keyTerms.length > 0 ? (
        <Card>
          <CardHeader
            title="Key terms"
            description="Defined by the material itself, not from general knowledge."
          />
          <ul className="divide-y divide-paper-200">
            {data.keyTerms.map((term) => (
              <li key={term.term} className="px-5 py-3.5">
                <p className="text-sm font-medium text-ink-900">{term.term}</p>
                <p className="mt-1 text-sm leading-relaxed text-ink-600">
                  {term.definition}
                </p>
                <SourceLine source={term.source} />
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {data.sections.map((section) => (
        <SectionCard key={section.topicId} section={section} />
      ))}
    </div>
  );
}

function SectionCard({ section }: { section: StudyGuideSection }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-paper-200 px-5 py-3.5">
        <h3 className="font-serif text-lg text-ink-900">{section.topicName}</h3>
        <Badge tone={BAND_BADGE_TONE[section.band as MasteryBand] ?? 'neutral'}>
          {section.bandLabel}
        </Badge>
        {section.isKnowledgeGap ? <Badge tone="caution">Worth reading first</Badge> : null}
      </div>

      <CardBody className="space-y-4">
        <p className="text-[15px] leading-relaxed text-ink-700">{section.summary}</p>

        {section.keyConcepts.length > 0 ? (
          <ul className="space-y-1.5">
            {section.keyConcepts.map((concept) => (
              <li
                key={concept}
                className="flex items-start gap-2 text-sm leading-relaxed text-ink-600"
              >
                <span
                  className="mt-1.5 size-1 shrink-0 rounded-full bg-brass-500"
                  aria-hidden
                />
                {concept}
              </li>
            ))}
          </ul>
        ) : null}

        {section.sources.map((source) => (
          <SourceLine key={source.chunkId} source={source} />
        ))}
      </CardBody>
    </Card>
  );
}
