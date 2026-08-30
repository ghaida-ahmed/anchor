import { ExternalLink, FileText } from 'lucide-react';
import { useState } from 'react';

import { Spinner } from '@/components/ui/Spinner';
import { fetchDocumentBlobUrl } from '@/services/api/documents';
import type { Citation } from '@/services/api/rag';

/**
 * Sources behind an answer.
 *
 * Every field here comes from a stored chunk, not from the model's text — the
 * backend attaches citations from the rows it put in the prompt, so a page number
 * cannot be invented.
 */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;

  return (
    <div className="mt-4 space-y-2 border-t border-paper-200 pt-3">
      <p className="text-xs font-medium tracking-wide text-ink-400 uppercase">
        {citations.length === 1 ? 'Source' : 'Sources'}
      </p>
      {citations.map((citation) => (
        <CitationRow key={citation.chunkId} citation={citation} />
      ))}
    </div>
  );
}

function CitationRow({ citation }: { citation: Citation }) {
  const [isOpening, setIsOpening] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function openSource() {
    setIsOpening(true);
    setError(null);
    try {
      // The download needs the bearer token, so it is fetched as a blob rather
      // than linked directly, then handed to the browser as an object URL.
      const url = await fetchDocumentBlobUrl(citation.documentId);
      window.open(url, '_blank', 'noopener,noreferrer');
      // Revoked on a delay: revoking immediately can cancel the new tab's load.
      window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch {
      setError('That file could not be opened.');
    } finally {
      setIsOpening(false);
    }
  }

  return (
    <div className="rounded-lg bg-paper-100 px-3 py-2">
      <div className="flex items-start gap-2.5">
        <FileText className="mt-0.5 size-3.5 shrink-0 text-brass-500" strokeWidth={1.75} aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-ink-800">
            {citation.documentName}
            {/* Omitted for formats with no real pages (TXT, Markdown), where the
                backend sends null rather than a fabricated 1. Rendering it
                unconditionally would print a bare "page " with nothing after it. */}
            {citation.pageNumber !== null ? (
              <span className="tabular ml-2 font-normal text-ink-400">
                page {citation.pageNumber}
              </span>
            ) : null}
          </p>
          <p className="mt-0.5 line-clamp-2 text-xs text-ink-500">{citation.excerpt}</p>
          {error ? <p className="mt-1 text-xs text-signal-danger">{error}</p> : null}
        </div>
        <button
          type="button"
          onClick={() => void openSource()}
          disabled={isOpening}
          aria-label={`Open ${citation.documentName}`}
          title="Open the source document"
          className="shrink-0 rounded p-1 text-ink-400 transition-colors hover:bg-paper-300/60 hover:text-ink-800 disabled:opacity-50"
        >
          {isOpening ? (
            <Spinner className="size-3.5" label="Opening" />
          ) : (
            <ExternalLink className="size-3.5" strokeWidth={1.75} aria-hidden />
          )}
        </button>
      </div>
    </div>
  );
}
