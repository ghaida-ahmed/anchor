import { FileText } from 'lucide-react';

import type { QuizSource } from '@/services/api/learning';

/**
 * A citation, rendered from stored database rows.
 *
 * The page number is omitted rather than faked when the source format has no pages
 * — the backend sends null for TXT and Markdown.
 */
export function SourceLine({ source }: { source: QuizSource | null }) {
  if (!source) return null;

  return (
    <p className="mt-3 flex items-center gap-2 border-t border-paper-200 pt-3 text-xs text-ink-500">
      <FileText className="size-3.5 shrink-0 text-brass-500" strokeWidth={1.75} aria-hidden />
      <span className="font-medium text-ink-600">Source:</span>
      <span className="truncate">{source.documentName}</span>
      {source.pageNumber !== null ? (
        <span className="tabular text-ink-400">· Page {source.pageNumber}</span>
      ) : null}
    </p>
  );
}
