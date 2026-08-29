import { ArrowUpRight, FileText } from 'lucide-react';
import { Link } from 'react-router-dom';

import { formatRelativeTime } from '@/lib/format';
import { paths } from '@/routes/paths';
import type { Course } from '@/types/domain';

export function CourseCard({ course }: { course: Course }) {
  const documentLabel = course.documentCount === 1 ? '1 document' : `${course.documentCount} documents`;

  return (
    <Link
      to={paths.course(course.id)}
      className="group flex flex-col rounded-card border border-paper-300 bg-white p-5 shadow-raise transition-colors hover:border-ink-300"
    >
      <div className="flex items-start justify-between gap-3">
        {course.code ? (
          <span className="rounded bg-ink-100 px-2 py-0.5 text-xs font-medium tracking-wide text-ink-700">
            {course.code}
          </span>
        ) : (
          <span className="text-xs text-ink-300">No code</span>
        )}
        <ArrowUpRight
          className="size-4 text-ink-300 transition-colors group-hover:text-ink-700"
          strokeWidth={1.75}
          aria-hidden
        />
      </div>

      <h3 className="mt-3 font-serif text-lg text-ink-900">{course.title}</h3>
      {course.description ? (
        <p className="mt-1.5 line-clamp-2 text-sm leading-relaxed text-ink-500">
          {course.description}
        </p>
      ) : (
        <p className="mt-1.5 text-sm text-ink-300">No description yet.</p>
      )}

      <div className="mt-5 flex-1" />

      <div className="flex items-center gap-4 border-t border-paper-200 pt-3 text-xs text-ink-400">
        <span className="inline-flex items-center gap-1.5">
          <FileText className="size-3.5" strokeWidth={1.75} aria-hidden />
          {documentLabel}
        </span>
        <span className="ml-auto">Added {formatRelativeTime(course.createdAt)}</span>
      </div>
    </Link>
  );
}
