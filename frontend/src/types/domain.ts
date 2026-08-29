/**
 * Core domain entities.
 *
 * These are the shapes the app works in — camelCase, unlike the API's snake_case
 * wire format. `services/api` owns the translation between the two, so the wire
 * format never leaks into components.
 */

/** ISO-8601 timestamp, e.g. `2026-08-25T14:03:00Z`. */
export type ISODateString = string;

export interface User {
  id: string;
  name: string;
  email: string;
  /**
   * IANA timezone identifier, e.g. `Europe/London`. Never a fixed offset: an
   * offset cannot express daylight saving, so it would be an hour wrong for half
   * the year. Only day boundaries use it — every timestamp stays UTC.
   */
  timezone: string;
  createdAt: ISODateString;
}

export interface Course {
  id: string;
  userId: string;
  title: string;
  /** Institutional course code, e.g. `CS340`. Empty when the user omitted it. */
  code: string;
  description: string;
  documentCount: number;
  createdAt: ISODateString;
  updatedAt: ISODateString;
}

/**
 * Formats ANCHOR accepts. Mirrors `DocumentFileType` in
 * `backend/app/models/document.py` — the backend is the source of truth.
 */
export const DOCUMENT_FILE_TYPES = ['pdf', 'txt', 'md'] as const;

export type DocumentFileType = (typeof DOCUMENT_FILE_TYPES)[number];

/**
 * Ingestion lifecycle. Phase 2 only ever produces `uploaded`; the rest arrive with
 * the processing pipeline in Phase 3.
 */
export const PROCESSING_STATUSES = ['uploaded', 'processing', 'ready', 'failed'] as const;

export type ProcessingStatus = (typeof PROCESSING_STATUSES)[number];

export interface CourseDocument {
  id: string;
  courseId: string;
  filename: string;
  originalFilename: string;
  fileType: DocumentFileType;
  fileSize: number;
  processingStatus: ProcessingStatus;
  /** Set only when `processingStatus` is `failed`; safe to show to the student. */
  processingError: string | null;
  createdAt: ISODateString;
  updatedAt: ISODateString;
}

export interface StudyProgress {
  id: string;
  userId: string;
  courseId: string;
  /** Free-text topic label, e.g. `TCP Congestion Control`. */
  topic: string;
  /** Mastery on a 0–1 scale. */
  masteryScore: number;
  updatedAt: ISODateString;
}
