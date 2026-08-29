import { ArrowLeft, MoreHorizontal, Pencil, Trash2 } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { formatDate } from '@/lib/format';
import { paths } from '@/routes/paths';
import type { Course } from '@/types/domain';

interface CourseWorkspaceHeaderProps {
  course: Course;
  onEdit: () => void;
  onDelete: () => void;
}

export function CourseWorkspaceHeader({
  course,
  onEdit,
  onDelete,
}: CourseWorkspaceHeaderProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  const stats = [
    {
      label: 'Documents',
      value: String(course.documentCount),
    },
    { label: 'Added', value: formatDate(course.createdAt) },
    { label: 'Updated', value: formatDate(course.updatedAt) },
  ];

  return (
    <header>
      <Link
        to={paths.courses}
        className="inline-flex items-center gap-1.5 text-sm text-ink-500 transition-colors hover:text-ink-900"
      >
        <ArrowLeft className="size-3.5" strokeWidth={2} aria-hidden />
        Courses
      </Link>

      <div className="mt-4 flex flex-wrap items-start justify-between gap-6">
        <div className="max-w-2xl">
          {course.code ? (
            <p className="text-xs font-medium tracking-[0.15em] text-brass-600 uppercase">
              {course.code}
            </p>
          ) : null}
          <h1 className="mt-2 font-serif text-3xl text-ink-900">{course.title}</h1>
          {course.description ? (
            <p className="mt-2 leading-relaxed text-ink-600">{course.description}</p>
          ) : null}
        </div>

        <div className="flex items-start gap-6">
          <dl className="grid grid-cols-3 gap-x-6 gap-y-3">
            {stats.map((stat) => (
              <div key={stat.label}>
                <dt className="text-xs tracking-wide text-ink-400 uppercase">
                  {stat.label}
                </dt>
                <dd className="tabular mt-1 text-sm font-medium text-ink-900">
                  {stat.value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="relative">
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              aria-label="Course actions"
              aria-expanded={menuOpen}
              className="rounded-lg border border-paper-400 bg-white p-2 text-ink-500 transition-colors hover:border-ink-300 hover:text-ink-900"
            >
              <MoreHorizontal className="size-4" strokeWidth={2} aria-hidden />
            </button>

            {menuOpen ? (
              <>
                {/* Click-away layer, so the menu closes without a global listener. */}
                <div
                  className="fixed inset-0 z-10"
                  onClick={() => setMenuOpen(false)}
                  aria-hidden
                />
                <div className="absolute right-0 z-20 mt-1 w-44 overflow-hidden rounded-lg border border-paper-300 bg-white py-1 shadow-lift">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onEdit();
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink-700 transition-colors hover:bg-paper-100"
                  >
                    <Pencil className="size-3.5" strokeWidth={1.75} aria-hidden />
                    Edit course
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false);
                      onDelete();
                    }}
                    className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-signal-danger transition-colors hover:bg-red-50"
                  >
                    <Trash2 className="size-3.5" strokeWidth={1.75} aria-hidden />
                    Delete course
                  </button>
                </div>
              </>
            ) : null}
          </div>
        </div>
      </div>
    </header>
  );
}
