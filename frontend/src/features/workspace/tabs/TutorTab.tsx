import { AlertCircle, FileStack, Loader2, MessagesSquare, SendHorizontal } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { FormError } from '@/components/ui/ErrorState';
import { Spinner } from '@/components/ui/Spinner';
import { CitationList } from '@/features/workspace/CitationList';
import type { WorkspaceTab } from '@/features/workspace/workspaceTabs';
import { useAskTutor } from '@/hooks/queries/useTutor';
import { cn } from '@/lib/cn';
import { toErrorMessage } from '@/services/api/client';
import type { Citation } from '@/services/api/rag';
import type { CourseDocument } from '@/types/domain';

/** Mirrors MAX_QUESTION_CHARS in backend/app/core/config.py. */
const MAX_QUESTION_CHARS = 1000;

interface Exchange {
  id: string;
  question: string;
  answer: string;
  citations: Citation[];
  /** False when the material did not cover the question and no model was called. */
  isGrounded: boolean;
}

interface TutorTabProps {
  courseId: string;
  documents: CourseDocument[];
  isLoadingDocuments: boolean;
  onOpenTab: (tab: WorkspaceTab) => void;
}

export function TutorTab({
  courseId,
  documents,
  isLoadingDocuments,
  onOpenTab,
}: TutorTabProps) {
  const askTutor = useAskTutor(courseId);
  const [question, setQuestion] = useState('');
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [error, setError] = useState<string | null>(null);
  const transcriptEnd = useRef<HTMLDivElement>(null);

  const readyCount = documents.filter(
    (document) => document.processingStatus === 'ready',
  ).length;
  const pendingCount = documents.filter(
    (document) =>
      document.processingStatus === 'uploaded' || document.processingStatus === 'processing',
  ).length;

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [exchanges.length, askTutor.isPending]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || askTutor.isPending) return;

    setError(null);
    setQuestion('');

    try {
      const result = await askTutor.mutateAsync(trimmed);
      setExchanges((previous) => [
        ...previous,
        {
          id: `${Date.now()}`,
          question: trimmed,
          answer: result.answer,
          citations: result.citations,
          isGrounded: result.isGrounded,
        },
      ]);
    } catch (caught) {
      setError(toErrorMessage(caught));
      // Put the question back so it is not lost to a transient failure.
      setQuestion(trimmed);
    }
  }

  if (isLoadingDocuments) {
    return (
      <Card>
        <div className="flex items-center justify-center gap-2.5 py-12 text-sm text-ink-500">
          <Spinner className="text-ink-400" label="Loading" />
          Checking this course's materials
        </div>
      </Card>
    );
  }

  if (readyCount === 0) {
    return (
      <Card>
        <EmptyState
          icon={pendingCount > 0 ? Loader2 : FileStack}
          title={
            pendingCount > 0
              ? 'Your materials are still being processed'
              : 'Upload and process course materials before using AI Tutor'
          }
          description={
            pendingCount > 0
              ? `${pendingCount} ${pendingCount === 1 ? 'document is' : 'documents are'} being read and indexed. The tutor becomes available as soon as that finishes.`
              : 'The tutor answers only from this course’s own documents, so there is nothing for it to draw on yet.'
          }
          action={
            pendingCount > 0 ? undefined : (
              <Button onClick={() => onOpenTab('materials')}>Go to Materials</Button>
            )
          }
        />
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {pendingCount > 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-paper-300 bg-paper-50 px-4 py-2.5 text-sm text-ink-500">
          <Loader2 className="size-3.5 shrink-0 animate-spin text-ink-400" aria-hidden />
          {pendingCount} more {pendingCount === 1 ? 'document is' : 'documents are'} still
          processing, so answers may not cover them yet.
        </p>
      ) : null}

      {exchanges.length === 0 && !askTutor.isPending ? (
        <Card>
          <EmptyState
            icon={MessagesSquare}
            title="Ask about your course material"
            description={`Answers are drawn only from the ${readyCount} processed ${readyCount === 1 ? 'document' : 'documents'} in this course, and cite the file and page they came from.`}
          />
        </Card>
      ) : null}

      <div className="space-y-4">
        {exchanges.map((exchange) => (
          <div key={exchange.id} className="space-y-4">
            <div className="flex justify-end">
              <div className="max-w-2xl rounded-card bg-ink-900 px-4 py-3 text-[15px] leading-relaxed text-paper-100">
                {exchange.question}
              </div>
            </div>

            <div className="flex justify-start">
              <div
                className={cn(
                  'max-w-2xl rounded-card border px-4 py-3',
                  exchange.isGrounded
                    ? 'border-paper-300 bg-white text-ink-800'
                    : 'border-dashed border-paper-400 bg-paper-50 text-ink-600',
                )}
              >
                {!exchange.isGrounded ? (
                  <p className="mb-2 flex items-center gap-1.5 text-xs font-medium tracking-wide text-ink-400 uppercase">
                    <AlertCircle className="size-3.5" strokeWidth={2} aria-hidden />
                    Not found in your materials
                  </p>
                ) : null}
                <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
                  {exchange.answer}
                </p>
                <CitationList citations={exchange.citations} />
              </div>
            </div>
          </div>
        ))}

        {askTutor.isPending ? (
          <div className="flex justify-start">
            <div className="flex items-center gap-2.5 rounded-card border border-paper-300 bg-white px-4 py-3 text-sm text-ink-500">
              <Spinner className="text-ink-400" label="Thinking" />
              Reading your course material…
            </div>
          </div>
        ) : null}

        <div ref={transcriptEnd} />
      </div>

      {error ? <FormError message={error} /> : null}

      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-3 rounded-card border border-paper-300 bg-white p-3"
      >
        <input
          type="text"
          value={question}
          maxLength={MAX_QUESTION_CHARS}
          disabled={askTutor.isPending}
          placeholder="Ask a question about this course…"
          aria-label="Ask a question about this course"
          onChange={(event) => setQuestion(event.target.value)}
          className="flex-1 bg-transparent px-2 text-sm text-ink-900 placeholder:text-ink-300 focus:outline-none disabled:cursor-not-allowed"
        />
        <Button type="submit" size="sm" disabled={askTutor.isPending || !question.trim()}>
          Ask
          <SendHorizontal className="size-3.5" strokeWidth={2} aria-hidden />
        </Button>
      </form>
    </div>
  );
}
