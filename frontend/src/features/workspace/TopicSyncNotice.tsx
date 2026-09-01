import { AlertTriangle, RefreshCw } from 'lucide-react';
import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Spinner } from '@/components/ui/Spinner';
import { useExtractTopics, useTopicSyncStatus } from '@/hooks/queries/useLearning';
import { toErrorMessage } from '@/services/api/client';

/**
 * Shown only when a course has processed material its topics were not built from.
 *
 * Topics update themselves once a document finishes processing, so in the normal
 * case this renders nothing and the student never learns that topic extraction is
 * a step. It exists for when that did not happen — no provider configured, a
 * provider outage, a restart mid-processing — because the alternative is a student
 * opening the Study Guide and finding it empty with no explanation.
 *
 * `hasPendingDocuments` keeps the banner quiet while processing is still running:
 * topics are genuinely about to update, and warning about it would be wrong.
 */
export function TopicSyncNotice({
  courseId,
  hasPendingDocuments = false,
}: {
  courseId: string;
  hasPendingDocuments?: boolean;
}) {
  const status = useTopicSyncStatus(courseId, hasPendingDocuments);
  const extractTopics = useExtractTopics(courseId);
  const [error, setError] = useState<string | null>(null);

  if (!status.data || status.data.topicsAreCurrent) return null;

  async function handleUpdate() {
    setError(null);
    try {
      await extractTopics.mutateAsync();
    } catch (caught) {
      setError(toErrorMessage(caught));
    }
  }

  const neverExtracted = status.data.topicCount === 0;

  return (
    <div className="rounded-card border border-amber-200 bg-amber-50 px-4 py-3.5">
      <div className="flex flex-wrap items-start gap-3">
        <AlertTriangle
          className="mt-0.5 size-4 shrink-0 text-signal-caution"
          strokeWidth={2}
          aria-hidden
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm leading-relaxed text-ink-700">
            {neverExtracted
              ? 'New course material has been added. Update topics to include the latest material before continuing.'
              : 'New course material has been added since these topics were built. Update topics to include the latest material — anything generated before then may not cover it.'}
          </p>
          {error ? <p className="mt-2 text-sm text-signal-danger">{error}</p> : null}
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => void handleUpdate()}
          disabled={extractTopics.isPending}
        >
          {extractTopics.isPending ? (
            <Spinner label="Updating" />
          ) : (
            <RefreshCw className="size-3.5" strokeWidth={2} aria-hidden />
          )}
          {extractTopics.isPending ? 'Reading your material…' : 'Update Topics'}
        </Button>
      </div>
    </div>
  );
}
