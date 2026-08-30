import { AlertCircle, FileText, Loader2, RotateCw, Trash2, UploadCloud } from 'lucide-react';
import { useRef, useState, type DragEvent } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState, FormError } from '@/components/ui/ErrorState';
import { SectionSpinner, Spinner } from '@/components/ui/Spinner';
import {
  useCourseDocuments,
  useDeleteDocument,
  useReprocessDocument,
  useUploadDocument,
} from '@/hooks/queries/useDocuments';
import { cn } from '@/lib/cn';
import { formatDate, formatFileSize } from '@/lib/format';
import { toErrorMessage } from '@/services/api/client';
import { DOCUMENT_FILE_TYPES, type CourseDocument, type ProcessingStatus } from '@/types/domain';

/** Mirrors MAX_UPLOAD_BYTES in backend/app/core/config.py. */
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

const ACCEPT = DOCUMENT_FILE_TYPES.map((type) => `.${type}`).join(',');
const EXTENSIONS_LABEL = DOCUMENT_FILE_TYPES.map((type) => type.toUpperCase()).join(', ');

const STATUS_TONE: Record<ProcessingStatus, 'neutral' | 'caution' | 'success' | 'danger'> = {
  uploaded: 'neutral',
  processing: 'caution',
  ready: 'success',
  failed: 'danger',
};

/**
 * Wording tracks what has actually happened to the file. `ready` is the only state
 * that means the text has been extracted and indexed for search.
 */
const STATUS_LABEL: Record<ProcessingStatus, string> = {
  uploaded: 'Uploaded — awaiting processing',
  processing: 'Processing',
  ready: 'Ready — searchable',
  failed: 'Processing failed',
};

const IN_PROGRESS: ReadonlySet<ProcessingStatus> = new Set(['uploaded', 'processing']);

function DocumentRow({
  document,
  onDelete,
  onRetry,
  isDeleting,
  isRetrying,
}: {
  document: CourseDocument;
  onDelete: () => void;
  onRetry: () => void;
  isDeleting: boolean;
  isRetrying: boolean;
}) {
  return (
    <li className="flex items-center gap-4 px-5 py-4">
      <FileText className="size-4 shrink-0 text-ink-400" strokeWidth={1.75} aria-hidden />

      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-ink-900">{document.filename}</p>
        <p className="tabular mt-0.5 text-xs text-ink-400">
          {document.fileType.toUpperCase()} · {formatFileSize(document.fileSize)} · added{' '}
          {formatDate(document.createdAt)}
        </p>
        {document.processingStatus === 'failed' && document.processingError ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-xs text-signal-danger">
            <AlertCircle className="mt-px size-3 shrink-0" strokeWidth={2} aria-hidden />
            {document.processingError}
          </p>
        ) : null}
      </div>

      <Badge tone={STATUS_TONE[document.processingStatus]}>
        {IN_PROGRESS.has(document.processingStatus) ? (
          <Loader2 className="size-3 animate-spin" aria-hidden />
        ) : null}
        {STATUS_LABEL[document.processingStatus]}
      </Badge>

      {document.processingStatus === 'failed' ? (
        <button
          type="button"
          onClick={onRetry}
          disabled={isRetrying}
          aria-label={`Retry processing ${document.filename}`}
          title="Try processing again"
          className="rounded p-1.5 text-ink-400 transition-colors hover:bg-paper-200 hover:text-ink-800 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isRetrying ? (
            <Spinner className="size-3.5" label="Retrying" />
          ) : (
            <RotateCw className="size-3.5" strokeWidth={1.75} aria-hidden />
          )}
        </button>
      ) : null}

      <button
        type="button"
        onClick={onDelete}
        disabled={isDeleting}
        aria-label={`Delete ${document.filename}`}
        className="rounded p-1.5 text-ink-400 transition-colors hover:bg-red-50 hover:text-signal-danger disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isDeleting ? (
          <Spinner className="size-3.5" label="Deleting" />
        ) : (
          <Trash2 className="size-3.5" strokeWidth={1.75} aria-hidden />
        )}
      </button>
    </li>
  );
}

export function MaterialsTab({ courseId }: { courseId: string }) {
  const { data: documents, isPending, isError, error, refetch } = useCourseDocuments(courseId);
  const uploadDocument = useUploadDocument(courseId);
  const deleteDocument = useDeleteDocument(courseId);
  const reprocessDocument = useReprocessDocument(courseId);

  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setUploadError(null);

    // Uploaded one at a time so a single rejection does not discard the rest.
    for (const file of Array.from(files)) {
      const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
      if (!DOCUMENT_FILE_TYPES.includes(extension as never)) {
        setUploadError(`“${file.name}” is not a supported format. Accepts ${EXTENSIONS_LABEL}.`);
        continue;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        setUploadError(`“${file.name}” is larger than ${formatFileSize(MAX_UPLOAD_BYTES)}.`);
        continue;
      }

      try {
        await uploadDocument.mutateAsync(file);
      } catch (caught) {
        setUploadError(toErrorMessage(caught));
      }
    }

    if (inputRef.current) inputRef.current.value = '';
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    void handleFiles(event.dataTransfer.files);
  }

  async function handleDelete(documentId: string) {
    setDeletingId(documentId);
    setUploadError(null);
    try {
      await deleteDocument.mutateAsync(documentId);
    } catch (caught) {
      setUploadError(toErrorMessage(caught));
    } finally {
      setDeletingId(null);
    }
  }

  async function handleRetry(documentId: string) {
    setRetryingId(documentId);
    setUploadError(null);
    try {
      await reprocessDocument.mutateAsync(documentId);
    } catch (caught) {
      setUploadError(toErrorMessage(caught));
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
        className={cn(
          'flex flex-col items-center rounded-card border border-dashed px-6 py-10 text-center transition-colors',
          isDragging
            ? 'border-ink-500 bg-ink-50'
            : 'border-paper-400 bg-paper-50 hover:border-ink-300',
        )}
      >
        <UploadCloud
          className={cn('size-6', isDragging ? 'text-ink-700' : 'text-ink-400')}
          strokeWidth={1.5}
          aria-hidden
        />
        <p className="mt-3 text-[15px] font-medium text-ink-900">
          Drop lecture notes or readings here
        </p>
        <p className="mt-1 text-sm text-ink-500">
          {EXTENSIONS_LABEL} · up to {formatFileSize(MAX_UPLOAD_BYTES)}
        </p>
        <p className="mt-2 max-w-md text-xs text-ink-400">
          Uploaded files are read and indexed in the background. A document becomes
          searchable by the AI Tutor once it reaches “Ready”.
        </p>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          multiple
          // Visually hidden and driven by the button below, but still in the tab
          // order — without a name a keyboard user focuses an unlabelled control.
          aria-label={`Upload course materials (${EXTENSIONS_LABEL})`}
          className="sr-only"
          onChange={(event) => void handleFiles(event.target.files)}
        />

        <Button
          variant="secondary"
          size="sm"
          className="mt-5"
          disabled={uploadDocument.isPending}
          onClick={() => inputRef.current?.click()}
        >
          {uploadDocument.isPending ? <Spinner label="Uploading" /> : null}
          {uploadDocument.isPending ? 'Uploading…' : 'Select files'}
        </Button>
      </div>

      {uploadError ? <FormError message={uploadError} /> : null}

      {isPending ? <SectionSpinner label="Loading materials" /> : null}

      {isError ? (
        <Card>
          <ErrorState
            title="Could not load materials"
            message={toErrorMessage(error)}
            onRetry={() => void refetch()}
          />
        </Card>
      ) : null}

      {documents ? (
        <Card>
          {documents.length > 0 ? (
            <ul className="divide-y divide-paper-200">
              {documents.map((document) => (
                <DocumentRow
                  key={document.id}
                  document={document}
                  isDeleting={deletingId === document.id}
                  isRetrying={retryingId === document.id}
                  onDelete={() => void handleDelete(document.id)}
                  onRetry={() => void handleRetry(document.id)}
                />
              ))}
            </ul>
          ) : (
            <EmptyState
              icon={FileText}
              title="No materials yet"
              description="Upload the lectures and notes for this course. Each one is indexed so the AI Tutor can answer from it."
            />
          )}
        </Card>
      ) : null}
    </div>
  );
}
