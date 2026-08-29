import type { ISODateString } from '@/types/domain';

/** Renders a 0–1 mastery score as a whole percentage. */
export function formatMastery(score: number): string {
  return `${Math.round(score * 100)}%`;
}

export function formatDate(value: ISODateString): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value));
}

const RELATIVE_UNITS: ReadonlyArray<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 365 * 24 * 60 * 60 * 1000],
  ['month', 30 * 24 * 60 * 60 * 1000],
  ['day', 24 * 60 * 60 * 1000],
  ['hour', 60 * 60 * 1000],
  ['minute', 60 * 1000],
];

/** "3 days ago", "20 minutes ago". Falls back to "just now" under a minute. */
export function formatRelativeTime(value: ISODateString, now: Date = new Date()): string {
  const elapsed = new Date(value).getTime() - now.getTime();
  const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

  for (const [unit, msPerUnit] of RELATIVE_UNITS) {
    if (Math.abs(elapsed) >= msPerUnit) {
      return formatter.format(Math.round(elapsed / msPerUnit), unit);
    }
  }
  return 'just now';
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let size = bytes / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size < 10 ? 1 : 0)} ${units[unitIndex]}`;
}
